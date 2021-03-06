import uuid

from snuba.datasets.factory import enforce_table_writer, get_dataset
from snuba.datasets.storages.factory import get_storage
from snuba.processor import ProcessedMessage, ProcessorAction
from snuba.query.query import Query
from snuba.request import Request
from snuba.request.schema import HTTPRequestSettings
from snuba.utils.clock import TestingClock
from snuba.utils.metrics.timer import Timer
from snuba.web.query_metadata import ClickhouseQueryMetadata, SnubaQueryMetadata

# TODO: Remove this once querylog is in prod and no longer disabled
from snuba import settings
settings.DISABLED_DATASETS = set()


def test_simple():
    request_body = {
        "selected_columns": ["event_id"],
        "orderby": "event_id",
        "sample": 0.1,
        "limit": 100,
        "offset": 50,
        "project": 1,
    }

    query = Query(
        request_body,
        get_storage("events").get_schemas().get_read_schema().get_data_source(),
    )

    request = Request(uuid.UUID("a" * 32).hex, query, HTTPRequestSettings(), {}, "search")

    time = TestingClock()

    timer = Timer("test", clock=time)
    time.sleep(0.01)

    message = SnubaQueryMetadata(
        request=request,
        dataset=get_dataset("events"),
        timer=timer,
        query_list=[ClickhouseQueryMetadata(
            sql="select event_id from sentry_dist sample 0.1 prewhere project_id in (1) limit 50, 100",
            stats={"sample": 10},
            status="success",
            trace_id="b" * 32
        )]
    ).to_dict()

    processor = (
        enforce_table_writer(get_dataset("querylog")).get_stream_loader().get_processor()
    )

    assert processor.process_message(message) == ProcessedMessage(
        ProcessorAction.INSERT,
        [{
            "request_id": str(uuid.UUID("a" * 32)),
            "request_body": '{"limit": 100, "offset": 50, "orderby": "event_id", "project": 1, "sample": 0.1, "selected_columns": ["event_id"]}',
            "referrer": "search",
            "dataset": get_dataset("events"),
            "projects": [1],
            "organization": None,
            "timestamp": timer.for_json()["timestamp"],
            "duration_ms": 10,
            "status": "success",
            "clickhouse_queries.sql": ["select event_id from sentry_dist sample 0.1 prewhere project_id in (1) limit 50, 100"],
            "clickhouse_queries.status": ["success"],
            "clickhouse_queries.trace_id": [str(uuid.UUID("b" * 32))],
            "clickhouse_queries.duration_ms": [0],
            "clickhouse_queries.stats": ['{"sample": 10}'],
            "clickhouse_queries.final": [0],
            "clickhouse_queries.cache_hit": [0],
            "clickhouse_queries.sample": [10.],
            "clickhouse_queries.max_threads": [0],
            "clickhouse_queries.num_days": [0],
            "clickhouse_queries.clickhouse_table": [""],
            "clickhouse_queries.query_id": [""],
            "clickhouse_queries.is_duplicate": [0],
            "clickhouse_queries.consistent": [0],
        }]
    )
