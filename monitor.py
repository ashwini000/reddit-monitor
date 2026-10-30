"""Public-page monitoring and employee REVIEW assignments. Python 3.12+."""
import argparse
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc


def stamp(dt):
    return dt.astimezone(UTC).isoformat()


def parse_dt(value):
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(float(value), UTC)
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return dt.astimezone(UTC)


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def contains(text, phrase):
    return (' ' + norm(phrase) + ' ') in (' ' + norm(text) + ' ')


def match(title, config):
    if any(contains(title, x) for x in config['exclude_phrases']):
        return []
    # An extra conservative age check. This is not a reliable age classifier.
    if re.search(r'\b(?:1[0-7]\s*[mf]|[mf]\s*1[0-7])\b', title.lower()):
        return []
    groups = config['keywords']
    hits = [x for g in ('brand', 'products', 'intimacy') for x in groups[g] if contains(title, x)]
    if any(contains(title, x) for x in groups['context']):
        hits += [x for x in groups['contextual_hinglish'] if contains(title, x)]
    return sorted(set(hits))


def canonical(url):
    u = urlparse(urljoin('https://www.reddit.com', url))
    if u.hostname not in ('www.reddit.com', 'reddit.com') or u.scheme != 'https':
        raise ValueError('Expected a public reddit.com thread URL')
    m = re.match(r'^/r/([A-Za-z0-9_]+)/comments/([a-z0-9]+)(?:/|$)', u.path)
    if not m:
        raise ValueError('Expected /r/subreddit/comments/postid/ URL')
    return m.group(2), m.group(1), f'https://www.reddit.com/r/{m.group(1)}/comments/{m.group(2)}/'


class ListingParser(HTMLParser):
    """Reads server-rendered modern Reddit cards; JS-only pages fail visibly."""
    def __init__(self):
        super().__init__()
        self.posts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag != 'shreddit-post':
            return
        try:
            pid, sub, url = canonical(a['permalink'])
            title = a['post-title'].strip()
            created = parse_dt(a['created-timestamp'])
            if title:
                self.posts.append(dict(id=pid, subreddit=sub, url=url, title=title,
                                       created_at=stamp(created)))
        except (KeyError, ValueError, TypeError, OverflowError):
            pass


def fetch(subreddit, config):
    if not re.fullmatch(r'[A-Za-z0-9_]+', subreddit):
        raise ValueError('Invalid subreddit')
    req = Request(f'https://www.reddit.com/r/{subreddit}/new/',
                  headers={'User-Agent': config['user_agent'], 'Accept': 'text/html'})
    # One request. No login automation, proxy rotation, CAPTCHA handling, or retries.
    with urlopen(req, timeout=25) as res:
        if urlparse(res.url).path.startswith('/login'):
            raise ValueError('Login wall')
        body = res.read(4_000_001)
        if len(body) > 4_000_000:
            raise ValueError('Page exceeded size limit')
    parser = ListingParser()
    parser.feed(body.decode('utf-8', errors='replace'))
    if not parser.posts:
        raise ValueError('No readable post cards: blocked, empty, or layout changed')
    return [p for p in parser.posts if p['subreddit'].lower() == subreddit.lower()]


def save(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2) + '\n')
    tmp.replace(path)


def ingest(posts, state, config, now):
    for p in posts:
        hits = match(p['title'], config)
        age = (now - parse_dt(p['created_at'])).total_seconds() / 3600
        if p['id'] in state['posts'] or not hits or not 0 <= age <= config['max_post_age_hours']:
            continue
        state['posts'][p['id']] = dict(p, hits=hits, detected_at=stamp(now))


def assign(state, config, now):
    zone = ZoneInfo(config['timezone'])
    today = now.astimezone(zone).date()
    for pid, post in state['posts'].items():
        origin = parse_dt(post['created_at'])
        if now > origin + timedelta(days=15):
            continue
        for day in [0] + config['followup_days']:
            key = f'{pid}-d{day}'
            release = origin + timedelta(days=day)
            if key in state['tasks'] or now < release:
                continue
            # Unassigned new discoveries expire after the initial 24-hour window.
            if day == 0 and now > origin + timedelta(hours=24):
                continue
            previous = {t['owner'] for t in state['tasks'].values() if t['post_id'] == pid}
            brand = config['default_brand']
            title = norm(post['title'])
            for b in config['brands']:
                if contains(title, b):
                    brand = b
                    break
            eligible = []
            for person in config['team']:
                if not person.get('active', True) or brand not in person['brands']:
                    continue
                owned = [t for t in state['tasks'].values() if t['owner'] == person['email']]
                daily = sum(parse_dt(t['assigned_at']).astimezone(zone).date() == today for t in owned)
                cap = person.get('daily_cap', config['max_new_assignments_per_person_per_day'])
                if daily >= cap or person['email'] in previous:
                    continue
                pending = sum(t['status'] == 'pending' for t in owned)
                eligible.append((pending, len(owned), person['email']))
            if not eligible:
                continue
            owner = min(eligible)[2]
            deadline = min(release + timedelta(hours=24), origin + timedelta(days=15))
            state['tasks'][key] = dict(id=key, post_id=pid, owner=owner, brand=brand,
                day=day, status='pending', assigned_at=stamp(now), due_at=stamp(deadline),
                notified_at=None, comment_url=None)


def digest_for(person, tasks, state, now):
    lines = [f"Hi {person['name']},", '', 'Your Reddit conversation REVIEW tasks:', '']
    for t in tasks:
        p = state['posts'][t['post_id']]
        lines += [f"[{t['id']}] {t['brand']} — Day {t['day']} review",
                  p['title'], p['url'], 'Matched: ' + ', '.join(p['hits']),
                  'Due (IST): ' + parse_dt(t['due_at']).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y %H:%M'),
                  'OVERDUE' if now > parse_dt(t['due_at']) else '', '']
    if not tasks:
        lines += ['No pending assignments. Check your allocated communities if scheduled.', '']
    lines += ['Check community rules and the current thread before replying. Disclose brand affiliation.',
              'Add a useful contribution; a brand mention is not required. Skip unsuitable threads.',
              'Do not profile users, coordinate votes, or present employees as independent customers.',
              'Reply to the coordinator with the task ID and comment link, or a reason to skip.',
              'The coordinator records completion using the GitHub workflow or CLI.']
    return '\n'.join(lines)


def deliver(recipient, subject, body, live, outbox):
    if not live:
        outbox.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((recipient + subject + body).encode()).hexdigest()[:12]
        (outbox / f'{key}.txt').write_text(f'To: {recipient}\nSubject: {subject}\n\n{body}')
        return False
    msg = EmailMessage()
    msg['From'] = os.environ['SMTP_FROM']
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.set_content(body)
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        smtp.send_message(msg)
    return True


def notify(state, config, now, live, outbox, force_daily=False):
    local = now.astimezone(ZoneInfo(config['timezone']))
    daily = force_daily or local.hour == 10
    today = str(local.date())
    for person in config['team']:
        if not person.get('active', True):
            continue
        email = person['email']
        daily_key = f'{today}:{email}'
        full = daily and daily_key not in state['digests']
        tasks = [t for t in state['tasks'].values() if t['owner'] == email and t['status'] == 'pending'
                 and (full or not t['notified_at'])]
        if not full and not tasks:
            continue
        try:
            if deliver(email, 'Reddit: daily review list' if full else 'Reddit: new review assignments',
                       digest_for(person, tasks, state, now), live, outbox):
                for t in tasks:
                    t['notified_at'] = stamp(now)
                if full:
                    state['digests'][daily_key] = stamp(now)
        except Exception as e:
            # Never print SMTP error text: providers may include recipient/credential information.
            print(f'Email delivery failed ({type(e).__name__}); tasks remain eligible for retry.')
    if config.get('manager_email'):
        health = '\n'.join(f'{s}: {v["status"]}' for s, v in state['health'].items())
        overdue = [t['id'] for t in state['tasks'].values()
                   if t['status'] == 'pending' and now > parse_dt(t['due_at'])]
        body = f'Source health:\n{health}\n\nOverdue: {", ".join(overdue) or "none"}\n'
        if not config['team']:
            body += '\nNo employees configured. No assignments can be distributed.\n'
        try:
            deliver(config['manager_email'], 'Reddit monitor: source health and overdue work', body, live, outbox)
        except Exception as e:
            print(f'Manager email failed ({type(e).__name__}).')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['scan', 'demo', 'complete', 'skip', 'list'])
    ap.add_argument('--config', type=Path, default=ROOT / 'config.json')
    ap.add_argument('--state', type=Path, default=ROOT / 'data/state.json')
    ap.add_argument('--task')
    ap.add_argument('--comment-url')
    ap.add_argument('--reason')
    ap.add_argument('--send-email', action='store_true')
    ap.add_argument('--daily', action='store_true', help='Daily digest even if scheduled run was delayed')
    args = ap.parse_args()
    now = datetime.now(UTC)
    config = json.loads(args.config.read_text())
    state = json.loads(args.state.read_text()) if args.state.exists() else dict(posts={}, tasks={}, health={}, digests={})
    emails = [p['email'] for p in config['team']]
    if len(emails) != len(set(emails)):
        ap.error('Duplicate team email addresses')
    if args.command in ('complete', 'skip'):
        if args.task not in state['tasks']:
            ap.error('Unknown task ID')
        t = state['tasks'][args.task]
        if args.command == 'complete':
            if not args.comment_url:
                ap.error('--comment-url is required')
            pid, _, _ = canonical(args.comment_url)
            path = urlparse(args.comment_url).path.strip('/').split('/')
            if pid != t['post_id'] or len(path) < 6:
                ap.error('Use a comment permalink from the assigned thread')
            t['comment_url'] = args.comment_url
        elif not args.reason:
            ap.error('--reason is required')
        t.update(status='done' if args.command == 'complete' else 'skipped',
                 resolved_at=stamp(now), reason=args.reason)
    elif args.command == 'list':
        for t in state['tasks'].values():
            print(t['id'], t['owner'], t['status'], t['due_at'])
        return
    else:
        if args.command == 'demo':
            if args.send_email:
                ap.error('Demo cannot send emails')
            # Demo has isolated state and fake employees, never production assignments.
            args.state = ROOT / 'test-output/demo-state.json'
            state = dict(posts={}, tasks={}, health={}, digests={})
            config['team'] = [dict(name=f'Member {x}', email=f'member{x}@example.invalid',
                                  brands=config['brands'], daily_cap=5) for x in 'ABC']
            ingest([dict(id='demo1', subreddit='Adulting', title='First vibrator and lube suggestions?',
                         url='https://www.reddit.com/r/Adulting/comments/demo1/',
                         created_at=stamp(now - timedelta(hours=1)))], state, config, now)
        else:
            for sub in config['subreddits']:
                try:
                    posts = fetch(sub, config)
                    ingest(posts, state, config, now)
                    state['health'][sub] = dict(status='ok', at=stamp(now), count=len(posts))
                except (HTTPError, URLError, ValueError, TimeoutError, OSError) as e:
                    status = f'HTTP {e.code}' if isinstance(e, HTTPError) else str(e)[:160]
                    state['health'][sub] = dict(status=status, at=stamp(now))
                time.sleep(config['request_gap_seconds'])
            # Manual entries bypass neither title filtering nor the 24-hour age window.
            for p in json.loads((ROOT / 'data/manual_links.json').read_text()):
                pid, sub, url = canonical(p['url'])
                ingest([dict(p, id=pid, subreddit=sub, url=url)], state, config, now)
        for t in state['tasks'].values():
            origin = parse_dt(state['posts'][t['post_id']]['created_at'])
            if t['status'] == 'pending' and now > origin + timedelta(days=15):
                t.update(status='expired', resolved_at=stamp(now))
        # Keep a rolling 30-day window; avoid an indefinite archive of thread text.
        stale = {pid for pid, p in state['posts'].items()
                 if now - parse_dt(p['created_at']) > timedelta(days=30)}
        state['posts'] = {pid: p for pid, p in state['posts'].items() if pid not in stale}
        state['tasks'] = {k: t for k, t in state['tasks'].items() if t['post_id'] not in stale}
        state['digests'] = {k: v for k, v in state['digests'].items()
                            if now - parse_dt(v) < timedelta(days=30)}
        assign(state, config, now)
        # Save assignments BEFORE delivery. Remote crash after SMTP acceptance can still
        # repeat an email on retry; this is at-least-once delivery, not exactly-once.
        save(state, args.state)
        notify(state, config, now, args.send_email, ROOT / 'outbox', args.daily)
        print('Source health:', json.dumps(state['health']))
        print(f"Tracked posts: {len(state['posts'])}; tasks: {len(state['tasks'])}")
    save(state, args.state)


if __name__ == '__main__':
    main()
