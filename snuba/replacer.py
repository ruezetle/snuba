import logging
import time
import simplejson as json

from typing import Optional, Sequence

from snuba.clickhouse.native import ClickhousePool
from snuba.datasets.storage import WritableTableStorage
from snuba.processor import InvalidMessageVersion
from snuba.replacers.replacer_processor import Replacement, ReplacementMessage
from snuba.utils.metrics.backends.abstract import MetricsBackend
from snuba.utils.streams.batching import AbstractBatchWorker
from snuba.utils.streams.kafka import KafkaPayload
from snuba.utils.streams.types import Message


logger = logging.getLogger("snuba.replacer")


class ReplacerWorker(AbstractBatchWorker[KafkaPayload, Replacement]):
    def __init__(
        self, clickhouse: ClickhousePool, storage: WritableTableStorage, metrics: MetricsBackend
    ) -> None:
        self.clickhouse = clickhouse
        self.metrics = metrics
        processor = storage.get_table_writer().get_replacer_processor()
        assert (
            processor
        ), f"This storage writer does not support replacements {type(storage)}"
        self.__replacer_processor = processor

    def process_message(self, message: Message[KafkaPayload]) -> Optional[Replacement]:
        seq_message = json.loads(message.payload.value)
        version = seq_message[0]

        if version == 2:
            return self.__replacer_processor.process_message(
                ReplacementMessage(seq_message[1], seq_message[2])
            )
        else:
            raise InvalidMessageVersion("Unknown message format: " + str(seq_message))

    def flush_batch(self, batch: Sequence[Replacement]) -> None:
        for replacement in batch:
            query_args = {
                **replacement.query_args,
                "dist_read_table_name": self.__replacer_processor.get_read_schema().get_table_name(),
                "dist_write_table_name": self.__replacer_processor.get_write_schema().get_table_name(),
            }
            count = self.clickhouse.execute_robust(
                replacement.count_query_template % query_args
            )[0][0]
            if count == 0:
                continue

            self.__replacer_processor.pre_replacement(replacement, count)

            t = time.time()
            query = replacement.insert_query_template % query_args
            logger.debug("Executing replace query: %s" % query)
            self.clickhouse.execute_robust(query)
            duration = int((time.time() - t) * 1000)

            self.__replacer_processor.post_replacement(replacement, duration, count)
            logger.info("Replacing %s rows took %sms" % (count, duration))
            self.metrics.timing("replacements.count", count)
            self.metrics.timing("replacements.duration", duration)
