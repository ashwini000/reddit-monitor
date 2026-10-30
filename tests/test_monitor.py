import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import monitor as m


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((m.ROOT / 'config.json').read_text())
        self.c['team'] = [dict(name=x, email=x+'@example.invalid', brands=self.c['brands']) for x in 'ABC']
        self.s = dict(posts={}, tasks={}, health={}, digests={})
        self.now = datetime(2026, 10, 30, 4, 30, tzinfo=timezone.utc)

    def post(self, pid='abc'):
        return dict(id=pid, subreddit='Adulting', url=f'https://www.reddit.com/r/Adulting/comments/{pid}/',
                    title='Vibrator aur lube kaha se kharidu?', created_at=m.stamp(self.now-timedelta(hours=1)))

    def test_hinglish_context_and_exclusions(self):
        self.assertTrue(m.match('Partner ke saath mood nahi banta', self.c))
        self.assertFalse(m.match('Office jaane ka mann nahi karta', self.c))
        self.assertFalse(m.match('17F first vibrator', self.c))
        self.assertFalse(m.match('Sexual assault and intimacy', self.c))
        self.assertFalse(m.match('Looking for lubrication for car engine', self.c))

    def test_dedup_and_balanced_capacity(self):
        for _ in range(2):
            m.ingest([self.post(str(i)) for i in range(12)], self.s, self.c, self.now)
            m.assign(self.s, self.c, self.now)
        self.assertEqual(len(self.s['tasks']), 9)
        for x in 'ABC':
            self.assertEqual(sum(t['owner'] == x+'@example.invalid' for t in self.s['tasks'].values()), 3)

    def test_followups_different_owners_and_release(self):
        m.ingest([self.post()], self.s, self.c, self.now)
        m.assign(self.s, self.c, self.now)
        self.assertEqual(len(self.s['tasks']), 1)
        m.assign(self.s, self.c, self.now+timedelta(days=2))
        m.assign(self.s, self.c, self.now+timedelta(days=10))
        self.assertEqual(len(self.s['tasks']), 3)
        self.assertEqual(len({t['owner'] for t in self.s['tasks'].values()}), 3)

    def test_parser_and_canonical_link(self):
        parser = m.ListingParser()
        parser.feed('<shreddit-post permalink="/r/Adulting/comments/abc/title/" post-title="Lube &amp; toys" created-timestamp="2026-10-30T03:00:00Z"></shreddit-post>')
        self.assertEqual(parser.posts[0]['title'], 'Lube & toys')
        self.assertEqual(parser.posts[0]['id'], 'abc')
        with self.assertRaises(ValueError):
            m.canonical('https://evil.example/r/Adulting/comments/abc/')

    def test_age_and_no_team(self):
        p = self.post()
        p['created_at'] = m.stamp(self.now-timedelta(hours=25))
        m.ingest([p], self.s, self.c, self.now)
        self.assertFalse(self.s['posts'])
        m.ingest([self.post()], self.s, self.c, self.now)
        self.c['team'] = []
        m.assign(self.s, self.c, self.now)
        self.assertFalse(self.s['tasks'])

    def test_dry_run_does_not_mark_sent_and_done_not_reminded(self):
        m.ingest([self.post()], self.s, self.c, self.now)
        m.assign(self.s, self.c, self.now)
        with TemporaryDirectory() as d:
            m.notify(self.s, self.c, self.now, False, Path(d))
            self.assertIsNone(self.s['tasks']['abc-d0']['notified_at'])
            self.assertTrue(list(Path(d).glob('*.txt')))
        with patch.object(m, 'deliver', return_value=True) as deliver:
            m.notify(self.s, self.c, self.now, True, Path('.'))
            self.assertEqual(deliver.call_count, 3)
            m.notify(self.s, self.c, self.now, True, Path('.'))
            self.assertEqual(deliver.call_count, 3)
        self.s['tasks']['abc-d0']['status'] = 'done'
        with patch.object(m, 'deliver', return_value=True) as deliver:
            m.notify(self.s, self.c, self.now+timedelta(hours=2), True, Path('.'))
            deliver.assert_not_called()

    def test_delivery_failure_retried(self):
        m.ingest([self.post()], self.s, self.c, self.now)
        m.assign(self.s, self.c, self.now)
        with patch.object(m, 'deliver', side_effect=OSError('offline')):
            m.notify(self.s, self.c, self.now, True, Path('.'))
        self.assertIsNone(self.s['tasks']['abc-d0']['notified_at'])


if __name__ == '__main__':
    unittest.main()
