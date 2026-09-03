"""P-16 Part C — future-dated hours are FLAGGED, never blocked.

P-14 C1 filed it: TimeEntry 54 (7.00h dated tomorrow) was accepted with
no signal anywhere. Entering hours on the planned day ahead of time is
a real practice (the P-14 chains did it on purpose), so the rule is the
over-quote rule's: warn amber, let the person decide. The API's
`is_future` is the flag — computed against the SERVER's local date (a
browser in another timezone must not decide what "today" is, the P-3
rule), read-only on the wire.
"""
from datetime import timedelta

from django.utils import timezone

from .fixtures import ENTRIES_URL, TimesheetsFixture, entry_detail_url


class FutureFlagTests(TimesheetsFixture):
    def test_a_future_entry_is_accepted_and_flagged(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        resp = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": tomorrow.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "7.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["is_future"])

    def test_todays_and_yesterdays_entries_are_not_flagged(self):
        today = timezone.localdate()
        for day in (today, today - timedelta(days=1)):
            entry = self.make_entry(self.staff_a, day, self.normal_a)
            resp = self.api(self.staff_a).get(entry_detail_url(entry.id))
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertFalse(resp.data["is_future"], day)

    def test_the_flag_is_read_only_on_the_wire(self):
        """A client cannot store the flag; it is derived on every read."""
        tomorrow = timezone.localdate() + timedelta(days=1)
        resp = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": tomorrow.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "1.00",
                "is_future": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["is_future"])
