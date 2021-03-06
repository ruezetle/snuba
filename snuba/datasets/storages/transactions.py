from datetime import datetime
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from snuba.clickhouse.columns import (
    ColumnSet,
    ColumnType,
    Date,
    DateTime,
    IPv4,
    IPv6,
    LowCardinality,
    Materialized,
    Nested,
    Nullable,
    String,
    UInt,
    UUID,
    WithDefault,
)
from snuba.datasets.dataset_schemas import StorageSchemas
from snuba.query.processors.prewhere import PrewhereProcessor
from snuba.query.processors.tagsmap import NestedFieldConditionOptimizer
from snuba.query.processors.transaction_column_processor import TransactionColumnProcessor
from snuba.datasets.schemas.tables import ReplacingMergeTreeSchema
from snuba.datasets.storage import WritableTableStorage
from snuba.datasets.table_storage import TableWriter, KafkaStreamLoader
from snuba.datasets.transactions_processor import (
    TransactionsMessageProcessor,
    UNKNOWN_SPAN_STATUS,
)
from snuba.writer import BatchWriter

# This is the moment in time we started filling in flattened_tags and flattened_contexts
# columns. It is captured to use the flattened tags optimization only for queries that
# do not go back this much in time.
# Will be removed in february.
BEGINNING_OF_TIME = datetime(2019, 12, 11, 0, 0, 0)


class TransactionsTableWriter(TableWriter):
    def __update_options(
        self, options: Optional[MutableMapping[str, Any]] = None,
    ) -> MutableMapping[str, Any]:
        if options is None:
            options = {}
        if "insert_allow_materialized_columns" not in options:
            options["insert_allow_materialized_columns"] = 1
        return options

    def get_writer(
        self,
        options: Optional[MutableMapping[str, Any]] = None,
        table_name: Optional[str] = None,
        rapidjson_serialize=False,
    ) -> BatchWriter:
        return super().get_writer(
            self.__update_options(options), table_name, rapidjson_serialize
        )

    def get_bulk_writer(
        self,
        options: Optional[MutableMapping[str, Any]] = None,
        table_name: Optional[str] = None,
    ) -> BatchWriter:
        return super().get_bulk_writer(self.__update_options(options), table_name,)


def transactions_migrations(
    clickhouse_table: str, current_schema: Mapping[str, ColumnType]
) -> Sequence[str]:
    ret = []
    duration_col = current_schema.get("duration")
    if duration_col and Materialized in duration_col.get_all_modifiers():
        ret.append("ALTER TABLE %s MODIFY COLUMN duration UInt32" % clickhouse_table)

    if "sdk_name" not in current_schema:
        ret.append(
            "ALTER TABLE %s ADD COLUMN sdk_name LowCardinality(String) DEFAULT ''"
            % clickhouse_table
        )

    if "sdk_version" not in current_schema:
        ret.append(
            "ALTER TABLE %s ADD COLUMN sdk_version LowCardinality(String) DEFAULT ''"
            % clickhouse_table
        )

    if "transaction_status" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN transaction_status UInt8 DEFAULT {UNKNOWN_SPAN_STATUS} AFTER transaction_op"
        )

    if "_tags_flattened" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN _tags_flattened String DEFAULT ''"
        )

    if "_contexts_flattened" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN _contexts_flattened String DEFAULT ''"
        )

    if "_start_date" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN _start_date Date MATERIALIZED toDate(start_ts) AFTER start_ms"
        )

    if "_finish_date" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN _finish_date Date MATERIALIZED toDate(finish_ts) AFTER finish_ms"
        )

    if "user_hash" not in current_schema:
        ret.append(
            f"ALTER TABLE {clickhouse_table} ADD COLUMN user_hash UInt64 MATERIALIZED cityHash64(user) AFTER user"
        )

    low_cardinality_cols = [
        "transaction_name",
        "release",
        "dist",
        "sdk_name",
        "sdk_version",
        "environment",
    ]
    for col_name in low_cardinality_cols:
        col = current_schema.get(col_name)

        if col and LowCardinality not in col.get_all_modifiers():
            if isinstance(col, WithDefault):
                col.inner_type = LowCardinality(col.inner_type)
            else:
                col = LowCardinality(col)
            ret.append(
                f"ALTER TABLE {clickhouse_table} MODIFY COLUMN {col_name} {col.for_schema()}"
            )

    return ret


columns = ColumnSet(
    [
        ("project_id", UInt(64)),
        ("event_id", UUID()),
        ("trace_id", UUID()),
        ("span_id", UInt(64)),
        ("transaction_name", LowCardinality(String())),
        ("transaction_hash", Materialized(UInt(64), "cityHash64(transaction_name)",),),
        ("transaction_op", LowCardinality(String())),
        ("transaction_status", WithDefault(UInt(8), str(UNKNOWN_SPAN_STATUS))),
        ("start_ts", DateTime()),
        ("start_ms", UInt(16)),
        ("_start_date", Materialized(Date(), "toDate(start_ts)"),),
        ("finish_ts", DateTime()),
        ("finish_ms", UInt(16)),
        ("_finish_date", Materialized(Date(), "toDate(finish_ts)"),),
        ("duration", UInt(32)),
        ("platform", LowCardinality(String())),
        ("environment", LowCardinality(Nullable(String()))),
        ("release", LowCardinality(Nullable(String()))),
        ("dist", LowCardinality(Nullable(String()))),
        ("ip_address_v4", Nullable(IPv4())),
        ("ip_address_v6", Nullable(IPv6())),
        ("user", WithDefault(String(), "''",)),
        ("user_hash", Materialized(UInt(64), "cityHash64(user)"),),
        ("user_id", Nullable(String())),
        ("user_name", Nullable(String())),
        ("user_email", Nullable(String())),
        ("sdk_name", WithDefault(LowCardinality(String()), "''")),
        ("sdk_version", WithDefault(LowCardinality(String()), "''")),
        ("tags", Nested([("key", String()), ("value", String())])),
        ("_tags_flattened", String()),
        ("contexts", Nested([("key", String()), ("value", String())])),
        ("_contexts_flattened", String()),
        ("partition", UInt(16)),
        ("offset", UInt(64)),
        ("retention_days", UInt(16)),
        ("deleted", UInt(8)),
    ]
)

schema = ReplacingMergeTreeSchema(
    columns=columns,
    local_table_name="transactions_local",
    dist_table_name="transactions_dist",
    mandatory_conditions=[],
    prewhere_candidates=["event_id", "transaction_name",  "project_id"],
    order_by="(project_id, _finish_date, transaction_name, cityHash64(span_id))",
    partition_by="(retention_days, toMonday(_finish_date))",
    version_column="deleted",
    sample_expr=None,
    migration_function=transactions_migrations,
)

storage = WritableTableStorage(
    schemas=StorageSchemas(read_schema=schema, write_schema=schema),
    table_writer=TransactionsTableWriter(
        write_schema=schema,
        stream_loader=KafkaStreamLoader(
            processor=TransactionsMessageProcessor(), default_topic="events",
        ),
    ),
    query_processors=[
        NestedFieldConditionOptimizer(
            "tags", "_tags_flattened", {"start_ts", "finish_ts"}, BEGINNING_OF_TIME,
        ),
        NestedFieldConditionOptimizer(
            "contexts",
            "_contexts_flattened",
            {"start_ts", "finish_ts"},
            BEGINNING_OF_TIME,
        ),
        TransactionColumnProcessor(),
        PrewhereProcessor(),
    ],
)
