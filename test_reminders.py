import json
import unittest
from datetime import date, datetime, timedelta, timezone
from reminders import daily_slots, schedule_at, slot_by_id
import test_app


class ScheduleTests(unittest.TestCase):
    def test_exactly_33_evenly_spaced_slots_with_midnight_endpoint(self):
        slots = daily_slots(date(2026, 11, 20))
        self.assertEqual(len(slots), 33)
        self.assertEqual(slots[0]["time"], "10:00")
        self.assertEqual(slots[-1]["time"], "00:00")
        times = [datetime.fromisoformat(s["due_at"]) for s in slots]
        self.assertEqual(times[-1].date(), date(2026, 11, 21))
        self.assertEqual(set(int((b-a).total_seconds()/60) for a,b in zip(times,times[1:])), {26,27})

    def test_clock_changes_keep_london_times(self):
        self.assertEqual(daily_slots(date(2026,3,28))[0]["due_at"], "2026-03-28T10:00:00Z")
        self.assertEqual(daily_slots(date(2026,3,29))[0]["due_at"], "2026-03-29T09:00:00Z")
        self.assertEqual(daily_slots(date(2026,10,24))[0]["due_at"], "2026-10-24T09:00:00Z")
        self.assertEqual(daily_slots(date(2026,10,25))[0]["due_at"], "2026-10-25T10:00:00Z")

    def test_midnight_is_last_slot_of_previous_posting_day(self):
        schedule = schedule_at(datetime(2026,11,21,0,0,tzinfo=timezone.utc))
        self.assertEqual(schedule["current"]["id"], "2026-11-20:33")
        self.assertEqual(schedule["next"]["id"], "2026-11-21:1")
        morning = schedule_at(datetime(2026,11,21,10,0,tzinfo=timezone.utc))
        self.assertEqual(morning["current"]["id"], "2026-11-21:1")

    def test_invalid_slot_ids_rejected(self):
        for value in (None, "2026-11-20:34", "../../secret", "2026-11-20:0"):
            with self.assertRaises(ValueError):
                slot_by_id(value)


class ReminderStorageTests(unittest.TestCase):
    setUp = test_app.DeskTests.setUp
    transport = test_app.DeskTests.transport
    account = test_app.DeskTests.account

    def test_claim_once_no_catchup(self):
        instant = datetime(2026,11,20,10,26,tzinfo=timezone.utc)
        self.desk.save_settings({"own_handle":"person", "enabled":True})
        self.desk.execute("UPDATE activity_tracker SET last_success=?,user_id='123'", (instant.timestamp(),))
        self.assertTrue(self.desk.claim_reminder("2026-11-20:2", instant))
        self.assertFalse(self.desk.claim_reminder("2026-11-20:2", instant + timedelta(seconds=10)))
        self.assertFalse(self.desk.claim_reminder("2026-11-20:3", instant))
        self.assertFalse(self.desk.claim_reminder("2026-11-19:1", instant))

    def test_disabled_reminders(self):
        self.desk.save_settings({"reminders_enabled": False})
        self.assertFalse(self.desk.claim_reminder("2026-11-20:1", datetime(2026,11,20,10,0,tzinfo=timezone.utc)))

    def test_account_search_cache(self):
        self.responses = [{"data":{"id":"123","name":"Example Person","username":"person"}}]
        self.assertEqual(self.desk.search_account("@person")["name"], "Example Person")
        self.desk.search_account("person")
        self.desk.add_account("person")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.account()["user_id"], "123")


if __name__ == "__main__":
    unittest.main()
