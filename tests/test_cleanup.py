from base import BaseTest

from datetime import datetime, timedelta

from snuba import cleanup


class TestCleanup(BaseTest):
    def test(self):
        def to_monday(d):
            return d - timedelta(days=d.weekday())

        base = datetime(1999, 12, 26)  # a sunday
        table = self.dataset.SCHEMA.QUERY_TABLE

        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == []

        # base, 90 retention
        self.write_processed_events(self.create_event_for_date(base))
        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [(to_monday(base), 90)]
        stale = cleanup.filter_stale_partitions(parts, as_of=base)
        assert stale == []

        # -40 days, 90 retention
        three_weeks_ago = base - timedelta(days=7 * 3)
        self.write_processed_events(self.create_event_for_date(three_weeks_ago))
        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [(to_monday(three_weeks_ago), 90), (to_monday(base), 90)]
        stale = cleanup.filter_stale_partitions(parts, as_of=base)
        assert stale == []

        # -100 days, 90 retention
        thirteen_weeks_ago = base - timedelta(days=7 * 13)
        self.write_processed_events(self.create_event_for_date(thirteen_weeks_ago))
        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [
            (to_monday(thirteen_weeks_ago), 90),
            (to_monday(three_weeks_ago), 90),
            (to_monday(base), 90)
        ]
        stale = cleanup.filter_stale_partitions(parts, as_of=base)
        assert stale == [(to_monday(thirteen_weeks_ago), 90)]

        # -1 week, 30 retention
        one_week_ago = base - timedelta(days=7)
        self.write_processed_events(self.create_event_for_date(one_week_ago, 30))
        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [
            (to_monday(thirteen_weeks_ago), 90),
            (to_monday(three_weeks_ago), 90),
            (to_monday(one_week_ago), 30),
            (to_monday(base), 90)
        ]
        stale = cleanup.filter_stale_partitions(parts, as_of=base)
        assert stale == [(to_monday(thirteen_weeks_ago), 90)]

        # -5 weeks, 30 retention
        five_weeks_ago = base - timedelta(days=7 * 5)
        self.write_processed_events(self.create_event_for_date(five_weeks_ago, 30))
        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [
            (to_monday(thirteen_weeks_ago), 90),
            (to_monday(five_weeks_ago), 30),
            (to_monday(three_weeks_ago), 90),
            (to_monday(one_week_ago), 30),
            (to_monday(base), 90)
        ]
        stale = cleanup.filter_stale_partitions(parts, as_of=base)
        assert stale == [
            (to_monday(thirteen_weeks_ago), 90),
            (to_monday(five_weeks_ago), 30)
        ]

        cleanup.drop_partitions(self.clickhouse, self.database, table, stale, dry_run=False)

        parts = cleanup.get_active_partitions(self.clickhouse, self.database, table)
        assert parts == [
            (to_monday(three_weeks_ago), 90),
            (to_monday(one_week_ago), 30),
            (to_monday(base), 90)
        ]
