import logging
import signal

import click

from snuba import settings
from snuba.datasets.factory import get_dataset, DATASET_NAMES
from snuba.consumer_initializer import initialize_batching_consumer
from snuba.stateful_consumer.consumer_context import ConsumerContext, StateType


@click.command()
@click.option('--raw-events-topic', default=None,
              help='Topic to consume raw events from.')
@click.option('--replacements-topic', default=None,
              help='Topic to produce replacement messages info.')
@click.option('--commit-log-topic', default=None,
              help='Topic for committed offsets to be written to, triggering post-processing task(s)')
@click.option('--consumer-group', default='snuba-consumers',
              help='Consumer group use for consuming the raw events topic.')
@click.option('--bootstrap-server', default=None, multiple=True,
              help='Kafka bootstrap server to use.')
@click.option('--dataset', default='events', type=click.Choice(DATASET_NAMES),
              help='The dataset to target')
@click.option('--max-batch-size', default=settings.DEFAULT_MAX_BATCH_SIZE,
              help='Max number of messages to batch in memory before writing to Kafka.')
@click.option('--max-batch-time-ms', default=settings.DEFAULT_MAX_BATCH_TIME_MS,
              help='Max length of time to buffer messages in memory before writing to Kafka.')
@click.option('--auto-offset-reset', default='error', type=click.Choice(['error', 'earliest', 'latest']),
              help='Kafka consumer auto offset reset.')
@click.option('--queued-max-messages-kbytes', default=settings.DEFAULT_QUEUED_MAX_MESSAGE_KBYTES, type=int,
              help='Maximum number of kilobytes per topic+partition in the local consumer queue.')
@click.option('--queued-min-messages', default=settings.DEFAULT_QUEUED_MIN_MESSAGES, type=int,
              help='Minimum number of messages per topic+partition librdkafka tries to maintain in the local consumer queue.')
@click.option('--log-level', default=settings.LOG_LEVEL, help='Logging level to use.')
@click.option('--dogstatsd-host', default=settings.DOGSTATSD_HOST, help='Host to send DogStatsD metrics to.')
@click.option('--dogstatsd-port', default=settings.DOGSTATSD_PORT, type=int, help='Port to send DogStatsD metrics to.')
def snapshot_consumer(raw_events_topic, replacements_topic, commit_log_topic, consumer_group,
             bootstrap_server, dataset, max_batch_size, max_batch_time_ms,
             auto_offset_reset, queued_max_messages_kbytes, queued_min_messages, log_level,
             dogstatsd_host, dogstatsd_port):
    """
    Dataset consumer that is able to handle a consistent snapshot produced externally for the
    dataset it consumes.

    It is based on a stateful consumer that listens alternatively (depending on the state)
    on the main topic that produces data for the dataset or to the control topic that sends messages
    to coordinate the snapshot taking and that will be able to pause the main consumer and to
    provide transactions coordinates to restart consuming after the snapshot.
    """

    import sentry_sdk
    sentry_sdk.init(dsn=settings.SENTRY_DSN)

    logging.basicConfig(level=getattr(logging, log_level.upper()), format='%(asctime)s %(message)s')
    dataset_name = dataset
    dataset = get_dataset(dataset_name)

    consumer = initialize_batching_consumer(
        dataset=dataset,
        dataset_name=dataset_name,
        raw_topic=raw_events_topic,
        replacements_topic=replacements_topic,
        max_batch_size=max_batch_size,
        max_batch_time_ms=max_batch_time_ms,
        bootstrap_server=bootstrap_server,
        group_id=consumer_group,
        commit_log_topic=commit_log_topic,
        auto_offset_reset=auto_offset_reset,
        queued_max_messages_kbytes=queued_max_messages_kbytes,
        queued_min_messages=queued_min_messages,
        dogstatsd_host=dogstatsd_host,
        dogstatsd_port=dogstatsd_port
    )

    context = ConsumerContext(
        main_consumer=consumer
    )

    def handler(signum, frame):
        context.set_shutdown()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    context.run(input=None)