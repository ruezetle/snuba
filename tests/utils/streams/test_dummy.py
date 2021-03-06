import contextlib
import uuid
from typing import Iterator, Optional
from unittest import TestCase

import pytest

from snuba.utils.streams.dummy import (
    DummyBroker,
    DummyConsumer,
    DummyProducer,
)
from snuba.utils.streams.types import Topic
from tests.utils.streams.mixins import StreamsTestMixin


class DummyStreamsTestCase(StreamsTestMixin, TestCase):
    def setUp(self) -> None:
        self.broker: DummyBroker[int] = DummyBroker()

    @contextlib.contextmanager
    def get_topic(self, partitions: int = 1) -> Iterator[Topic]:
        topic = Topic(uuid.uuid1().hex)
        self.broker.create_topic(topic, partitions)
        yield topic

    def get_consumer(
        self, group: Optional[str] = None, enable_end_of_partition: bool = True
    ) -> DummyConsumer[int]:
        return DummyConsumer(
            self.broker,
            group if group is not None else uuid.uuid1().hex,
            enable_end_of_partition=enable_end_of_partition,
        )

    def get_producer(self) -> DummyProducer[int]:
        return DummyProducer(self.broker)

    @pytest.mark.xfail(
        strict=True, reason="rebalancing not implemented", raises=NotImplementedError
    )
    def test_pause_resume_rebalancing(self) -> None:
        return super().test_pause_resume_rebalancing()
