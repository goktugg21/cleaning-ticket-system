from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from sla.business_hours import (
    add_business_seconds,
    business_seconds_between,
    is_business_open,
)


AMS = ZoneInfo("Europe/Amsterdam")


def ams_to_utc(year, month, day, hour, minute=0):
    """Build a tz-aware UTC datetime from a wall-clock Amsterdam local time."""
    local = datetime(year, month, day, hour, minute, tzinfo=AMS)
    return local.astimezone(timezone.utc)


class IsBusinessOpenTests(SimpleTestCase):
    def test_monday_10am_open(self):
        self.assertTrue(is_business_open(ams_to_utc(2026, 5, 4, 10, 0)))

    def test_saturday_closed(self):
        self.assertFalse(is_business_open(ams_to_utc(2026, 5, 2, 10, 0)))

    def test_sunday_closed(self):
        self.assertFalse(is_business_open(ams_to_utc(2026, 5, 3, 10, 0)))

    def test_weekday_before_window_closed(self):
        self.assertFalse(is_business_open(ams_to_utc(2026, 5, 4, 8, 30)))

    def test_window_close_exactly_is_closed(self):
        # Window is [09:00, 17:00). 17:00 sharp is outside.
        self.assertFalse(is_business_open(ams_to_utc(2026, 5, 4, 17, 0)))

    def test_window_open_exactly_is_open(self):
        self.assertTrue(is_business_open(ams_to_utc(2026, 5, 4, 9, 0)))

    def test_naive_datetime_raises(self):
        with self.assertRaises(ValueError):
            is_business_open(datetime(2026, 5, 4, 10, 0))


class AddBusinessSecondsTests(SimpleTestCase):
    def test_zero_seconds_inside_window_unchanged(self):
        start = ams_to_utc(2026, 5, 4, 10, 0)
        self.assertEqual(add_business_seconds(start, 0), start)

    def test_zero_seconds_outside_window_advances_to_next_open(self):
        start = ams_to_utc(2026, 5, 4, 8, 0)
        self.assertEqual(
            add_business_seconds(start, 0), ams_to_utc(2026, 5, 4, 9, 0)
        )

    def test_one_hour_within_same_day(self):
        start = ams_to_utc(2026, 5, 4, 10, 0)
        self.assertEqual(
            add_business_seconds(start, 3600), ams_to_utc(2026, 5, 4, 11, 0)
        )

    def test_eight_business_hours_lands_at_window_close(self):
        start = ams_to_utc(2026, 5, 4, 9, 0)
        self.assertEqual(
            add_business_seconds(start, 8 * 3600),
            ams_to_utc(2026, 5, 4, 17, 0),
        )

    def test_overflow_into_next_business_day(self):
        # Mon 16:00 + 2h business → Tue 10:00 (1h Mon + 1h Tue).
        start = ams_to_utc(2026, 5, 4, 16, 0)
        self.assertEqual(
            add_business_seconds(start, 2 * 3600),
            ams_to_utc(2026, 5, 5, 10, 0),
        )

    def test_24_business_hours_from_wednesday(self):
        # Wed 09:00 + 24h business = 3 full business days = Fri 17:00.
        start = ams_to_utc(2026, 5, 6, 9, 0)
        self.assertEqual(
            add_business_seconds(start, 24 * 3600),
            ams_to_utc(2026, 5, 8, 17, 0),
        )

    def test_24_business_hours_from_friday_skips_weekend(self):
        # Fri 09:00 + 24h business = Fri (8h) + Mon (8h) + Tue (8h) → Tue 17:00.
        start = ams_to_utc(2026, 5, 8, 9, 0)
        self.assertEqual(
            add_business_seconds(start, 24 * 3600),
            ams_to_utc(2026, 5, 12, 17, 0),
        )

    def test_starting_saturday_advances_to_monday(self):
        start = ams_to_utc(2026, 5, 2, 12, 0)
        self.assertEqual(
            add_business_seconds(start, 3600), ams_to_utc(2026, 5, 4, 10, 0)
        )

    def test_starting_after_close_advances_to_next_morning(self):
        start = ams_to_utc(2026, 5, 4, 18, 0)
        self.assertEqual(
            add_business_seconds(start, 3600), ams_to_utc(2026, 5, 5, 10, 0)
        )

    def test_starting_at_window_close_advances_to_next_morning(self):
        # 17:00 sharp counts as outside; advance to next day's 09:00.
        start = ams_to_utc(2026, 5, 4, 17, 0)
        self.assertEqual(
            add_business_seconds(start, 3600), ams_to_utc(2026, 5, 5, 10, 0)
        )

    def test_dst_spring_forward_transparent(self):
        # Spring-forward in Europe/Amsterdam: 2026-03-29 02:00 CET → 03:00 CEST.
        # Business window 09-17 unaffected; the engine reasons in business
        # seconds regardless of UTC-offset jumps. Fri 16:00 local + 9h
        # business = 1h Fri + 8h Mon = Mon 17:00 local.
        start = ams_to_utc(2026, 3, 27, 16, 0)
        self.assertEqual(
            add_business_seconds(start, 9 * 3600),
            ams_to_utc(2026, 3, 30, 17, 0),
        )

    def test_dst_fall_back_transparent(self):
        # Fall-back: 2026-10-25 03:00 CEST → 02:00 CET. Business window
        # unaffected. Fri 16:00 + 9h business = Mon 17:00 local.
        start = ams_to_utc(2026, 10, 23, 16, 0)
        self.assertEqual(
            add_business_seconds(start, 9 * 3600),
            ams_to_utc(2026, 10, 26, 17, 0),
        )

    def test_negative_seconds_raises(self):
        start = ams_to_utc(2026, 5, 4, 10, 0)
        with self.assertRaises(ValueError):
            add_business_seconds(start, -1)

    def test_naive_datetime_raises(self):
        with self.assertRaises(ValueError):
            add_business_seconds(datetime(2026, 5, 4, 10, 0), 3600)


class BusinessSecondsBetweenTests(SimpleTestCase):
    def test_same_instant_zero(self):
        d = ams_to_utc(2026, 5, 4, 10, 0)
        self.assertEqual(business_seconds_between(d, d), 0)

    def test_one_hour_within_window(self):
        a = ams_to_utc(2026, 5, 4, 10, 0)
        b = ams_to_utc(2026, 5, 4, 11, 0)
        self.assertEqual(business_seconds_between(a, b), 3600)

    def test_overnight_only_window_counted(self):
        # Mon 16:00 → Tue 10:00 = 1h Mon (16-17) + 1h Tue (9-10).
        a = ams_to_utc(2026, 5, 4, 16, 0)
        b = ams_to_utc(2026, 5, 5, 10, 0)
        self.assertEqual(business_seconds_between(a, b), 2 * 3600)

    def test_weekend_zero(self):
        a = ams_to_utc(2026, 5, 2, 10, 0)
        b = ams_to_utc(2026, 5, 3, 10, 0)
        self.assertEqual(business_seconds_between(a, b), 0)

    def test_full_week(self):
        # Mon 09:00 to next Mon 09:00 = 5 * 8h business.
        a = ams_to_utc(2026, 5, 4, 9, 0)
        b = ams_to_utc(2026, 5, 11, 9, 0)
        self.assertEqual(business_seconds_between(a, b), 40 * 3600)

    def test_inverse_of_add_business_seconds(self):
        a = ams_to_utc(2026, 5, 4, 10, 30)
        b = add_business_seconds(a, 5 * 3600)
        self.assertEqual(business_seconds_between(a, b), 5 * 3600)

    def test_end_before_start_raises(self):
        a = ams_to_utc(2026, 5, 4, 10, 0)
        b = ams_to_utc(2026, 5, 4, 9, 0)
        with self.assertRaises(ValueError):
            business_seconds_between(a, b)

    def test_dst_spring_forward(self):
        # Fri 16:00 local + 9h business = Mon 17:00 local. The inverse must
        # also yield 9h business.
        a = ams_to_utc(2026, 3, 27, 16, 0)
        b = ams_to_utc(2026, 3, 30, 17, 0)
        self.assertEqual(business_seconds_between(a, b), 9 * 3600)
