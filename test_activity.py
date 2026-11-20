import unittest
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

import test_app
from app import Desk, ServiceError
from reminders import day_window, reply_pace


def post(pid, parent=None, kind='replied_to', created='2026-11-20T11:00:00Z'):
    value = {'id': str(pid), 'text': 'A post', 'created_at': created}
    if parent:
        value['referenced_posts'] = [{'id': str(parent), 'type': kind}]
    return value


class ActivityTests(unittest.TestCase):
    setUp = test_app.DeskTests.setUp
    transport = test_app.DeskTests.transport
    add_post = test_app.DeskTests.add_post

    def configure(self):
        self.desk.save_settings({'own_handle': '@0xJaffa', 'enabled': True})
        self.desk.execute("UPDATE activity_tracker SET user_id='123'")

    def tracker(self):
        return self.desk.rows('SELECT * FROM activity_tracker')[0]

    def fresh_at(self, instant):
        self.desk.execute('UPDATE activity_tracker SET last_success=?', (instant.timestamp(),))

    def add_replies(self, count, created='2026-11-20T11:00:00Z'):
        for i in range(count):
            self.desk.execute('INSERT INTO activity_posts VALUES (?,?,?,?)', (str(900+i), '123', created, str(100+i)))

    def test_pagination_counts_once_and_matches_only_direct_replies(self):
        self.configure()
        self.add_post()
        self.desk.execute("UPDATE posts SET reply='My unsent edits',repurpose='My take'")
        self.responses = [
            {'data': [post(205, 101, 'quoted'), post(204), post(203, 999)], 'meta': {'next_token': 'page2'}, 'includes': {'posts': [{'id': '101'}, {'id': '999'}]}},
            {'data': [post(203, 999), post(202, 101)], 'meta': {}}]
        self.desk.poll_activity()
        self.assertIsNone(self.tracker()['since_id'])
        self.assertEqual(self.tracker()['newest_id'], '205')
        self.assertIsNone(self.desk.rows('SELECT replied_at FROM posts')[0]['replied_at'])
        self.assertTrue(self.desk.activity_progress()['syncing'])
        self.desk.poll_activity()
        self.assertEqual(self.tracker()['since_id'], '205')
        self.assertIsNone(self.tracker()['next_token'])
        saved = self.desk.rows('SELECT * FROM posts')[0]
        self.assertEqual(saved['detected_reply_id'], '202')
        self.assertEqual(saved['reply'], 'My unsent edits')
        self.assertEqual(saved['repurpose'], 'My take')
        progress = self.desk.activity_progress(datetime(2026,11,20,12,tzinfo=timezone.utc))
        self.assertEqual((progress['posts'], progress['replies'], progress['other_posts']), (4,2,2))
        query = parse_qs(urlparse(self.requests[0][0]).query)
        self.assertEqual(query['exclude'], ['retweets'])
        self.assertEqual(query['expansions'], ['referenced_posts'])
        self.assertIn('start_time', query)
        self.assertEqual(parse_qs(urlparse(self.requests[1][0]).query)['pagination_token'], ['page2'])
        self.assertEqual(self.desk.usage()['posts_read'], 7)
        self.assertEqual(self.desk.usage()['read_slots'], 7)

    def test_cached_reply_matches_post_added_later(self):
        self.configure()
        self.responses = [{'data': [post(202, 101)]}]
        self.desk.poll_activity()
        self.add_post()
        self.desk.match_detected_replies('123')
        self.assertEqual(self.desk.rows('SELECT detected_reply_id FROM posts')[0]['detected_reply_id'], '202')

    def test_failure_preserves_pagination_and_suppresses_nudges(self):
        self.configure()
        self.desk.execute("UPDATE activity_tracker SET since_id='100',next_token='next',newest_id='200'")
        self.responses = [ServiceError('Rate limited', 9999999999)]
        self.desk.poll_activity()
        tracker = self.tracker()
        self.assertEqual((tracker['since_id'], tracker['next_token'], tracker['newest_id']), ('100','next','200'))
        self.assertEqual(tracker['error'], 'Rate limited')
        self.assertEqual(self.desk.usage()['read_slots'], 100)
        self.assertFalse(self.desk.reminder_schedule()['needs_reply'])
        self.desk.poll_activity(force=True)
        self.assertEqual(len(self.requests), 1)

    def test_invalid_page_is_not_partly_counted(self):
        self.configure()
        self.responses = [{'data':[post(205,101), {'id':'206','text':'Missing timestamp'}]}]
        self.desk.poll_activity()
        self.assertTrue(self.tracker()['error'])
        self.assertIsNone(self.tracker()['since_id'])
        self.assertEqual(self.desk.rows('SELECT * FROM activity_posts'), [])

    def test_account_change_during_request_cannot_populate_new_tracker(self):
        self.configure()
        def changed_account(url, token, body=None):
            self.desk.save_settings({'own_handle':'someone_else'})
            return {'data':[post(205,101)]}
        self.desk.transport = changed_account
        self.desk.poll_activity()
        self.assertEqual(self.tracker()['handle'], 'someone_else')
        self.assertIsNone(self.tracker()['since_id'])
        self.assertEqual(self.desk.rows('SELECT * FROM activity_posts'), [])

    def test_cursor_and_counts_survive_restart(self):
        self.configure()
        self.responses = [{'data':[post(205,101)]}]
        self.desk.poll_activity()
        reopened = Desk(self.desk.directory,self.desk.env_path,self.transport)
        self.addCleanup(reopened.db.close)
        reopened.keys = dict(self.desk.keys)
        self.responses = [{'meta':{}}]
        reopened.poll_activity(force=True)
        self.assertEqual(parse_qs(urlparse(self.requests[-1][0]).query)['since_id'], ['205'])
        self.assertEqual(len(reopened.rows('SELECT * FROM activity_posts')), 1)

    def test_budget_and_interval_limit_requests(self):
        self.configure()
        self.desk.save_settings({'daily_reads': 5})
        self.desk.poll_activity()
        self.assertIn('allowance', self.tracker()['error'])
        self.assertEqual(self.requests, [])
        self.desk.execute("UPDATE activity_tracker SET retry_at=0,error=''")
        self.desk.save_settings({'daily_reads': 500})
        self.desk.poll_activity()
        self.assertEqual(self.requests, [])

    def test_goal_met_or_ahead_silences_nudges(self):
        self.configure()
        noon = datetime(2026,11,20,12,11,tzinfo=timezone.utc)
        self.fresh_at(noon)
        self.add_replies(5)
        self.assertFalse(self.desk.reminder_schedule(noon)['needs_reply'])
        self.desk.execute('DELETE FROM activity_posts')
        self.add_replies(30)
        progress = self.desk.activity_progress(noon)
        self.assertTrue(progress['goal_met'])
        self.assertEqual(progress['remaining'], 0)
        self.assertFalse(self.desk.claim_reminder('2026-11-20:6', noon))

    def test_stale_paused_or_partial_counts_never_nudge(self):
        self.configure()
        instant = datetime(2026,11,20,10,26,tzinfo=timezone.utc)
        self.fresh_at(instant - timedelta(minutes=10))
        self.assertFalse(self.desk.claim_reminder('2026-11-20:2', instant))
        self.fresh_at(instant)
        self.desk.execute("UPDATE activity_tracker SET next_token='page2'")
        self.assertFalse(self.desk.claim_reminder('2026-11-20:2', instant))
        self.desk.execute('UPDATE activity_tracker SET next_token=NULL')
        self.desk.save_settings({'enabled':False})
        self.assertFalse(self.desk.claim_reminder('2026-11-20:2', instant))

    def test_calendar_day_reset_and_london_summer_time(self):
        self.configure()
        self.add_replies(1, '2026-07-19T23:30:00Z')
        self.desk.execute("INSERT INTO activity_posts VALUES ('999','123','2026-07-19T22:59:59Z','100')")
        progress = self.desk.activity_progress(datetime(2026,7,20,11,tzinfo=timezone.utc))
        self.assertEqual(progress['replies'], 1)
        self.assertEqual(progress['day'], '2026-07-20')
        midnight = datetime(2026,7,20,23,tzinfo=timezone.utc)
        self.assertEqual(self.desk.activity_progress(midnight)['replies'], 0)
        self.assertFalse(self.desk.reminder_schedule(midnight)['needs_reply'])

    def test_fractional_seconds_at_midnight_count_in_the_new_day(self):
        self.configure()
        self.add_replies(1, '2026-11-20T00:00:00.123000Z')
        progress = self.desk.activity_progress(datetime(2026,11,20,12,tzinfo=timezone.utc))
        self.assertEqual(progress['replies'], 1)

    def test_goal_and_handle_validation(self):
        for change in ({'reply_goal':0}, {'reply_goal':True}, {'own_handle':'bad/name'}, {'own_handle':123}):
            with self.assertRaises(ValueError):
                self.desk.save_settings(change)
        self.configure()
        self.desk.save_settings({'own_handle':''})
        self.assertFalse(self.desk.activity_progress()['handle'])


class PaceTests(unittest.TestCase):
    def test_pace_has_quiet_mornings_and_goal_stops_all_nudges(self):
        noon = datetime(2026,11,20,12,tzinfo=timezone.utc)
        self.assertEqual(reply_pace(0,23,noon)['expected'],4)
        self.assertFalse(reply_pace(4,23,noon)['behind'])
        self.assertFalse(reply_pace(0,23,noon.replace(hour=9))['active_window'])
        self.assertTrue(reply_pace(30,23,noon)['goal_met'])
        self.assertEqual(reply_pace(30,23,noon)['needed_per_hour'],0)

    def test_dst_calendar_day_bounds(self):
        start,end = day_window(datetime(2026,3,29,12,tzinfo=timezone.utc))
        self.assertEqual((end.astimezone(timezone.utc)-start.astimezone(timezone.utc)).total_seconds(),23*3600)


if __name__ == '__main__':
    unittest.main()
