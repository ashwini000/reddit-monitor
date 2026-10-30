# Reddit conversation monitor — first version

For ItsPleazure, Mohastra, and Kaamastra. Python 3.12; no paid AI service,
API credentials, or Python packages needed for this public-page implementation.

## Current status

Code and offline tests are ready. Nothing is deployed. No employees are configured
and no real emails have been sent. Public-page collection is experimental, not
guaranteed. All 20 supplied subreddit entries are configured, including both
AskIndianFeminist and AskIndianFeminists; their existence, accessibility and rules
have not been verified. Failed or empty sources appear in source health.

The first version checks post TITLES, not bodies or comments. It only reads the
server-rendered newest listing: no pagination, private content, NSFW gate bypass,
login automation or access-block circumvention. Busy subreddits may have more new
posts between checks than appear on one page. It cannot guarantee 24-hour coverage.
No user profiles or sensitive user characteristics are collected or inferred.

Public availability does not remove Reddit's permission requirements. This
implementation does not grant permission or make an approval-free use compliant
with Reddit's terms. A 403, 429, login wall or changed layout is a recorded failure,
not a reason to evade restrictions. There is no hidden scraper fallback.

## 1. Try the safe local demo

Extract this ZIP, open a terminal in its folder, and run:

```sh
python --version
python -m unittest discover -s tests -v
python monitor.py demo --daily
```

Use `python3` if that is your Python 3.12 command. The demo uses an invented post
and example.invalid employees. Open `outbox/` to see plain-text email previews.
Its state is isolated in `test-output/demo-state.json`; production history stays
unchanged. Demo never sends email, even if credentials are set.

## 2. Fill in the team

Edit `config.json`. Replace the empty `team` array with your actual roster:

```json
"team": [
  {
    "name": "Member A",
    "email": "replace-with-real-address@example.com",
    "brands": ["ItsPleazure", "Mohastra", "Kaamastra"],
    "daily_cap": 3,
    "active": true
  }
]
```

Add all employees as separate objects. Add the coordinator's address to
`manager_email`. Replace the contact wording in `user_agent` with a real work
contact. Set `default_brand` to the brand you want generic topics assigned to.
Only an exact brand-name match currently overrides that default; variants still
trigger discovery but need human brand review. A person must be eligible for the
selected brand. Three distinct eligible people are needed for three reviews.

The default limit is three NEW assignments per person per IST calendar day,
including follow-ups. Pending tasks can accumulate, so choose realistic caps.
Assignment balances outstanding work first, then the number assigned within the
rolling history. It never gives the same thread to the same person twice.
No forced product recommendation or automatic public posting is included.

## 3. Create a PRIVATE GitHub repository

Create a repository called `reddit-monitor` using your GitHub account. Keep it
private: the roster and assignment state contain employee email addresses.

Upload the CONTENTS of this folder to the repository root, including the hidden
`.github/workflows/monitor.yml` file. Do not upload the ZIP itself or put everything
inside an additional directory. Your repository root must contain `monitor.py`,
`config.json`, `tests/`, `data/`, and `.github/`.

For a Git upload from the extracted folder:

```sh
git init -b main
git add .
git commit -m "Add Reddit monitor"
git remote add origin https://github.com/YOUR-USERNAME/reddit-monitor.git
git push -u origin main
```

Use your actual username. GitHub handles authentication; do not embed tokens in
the URL. The Actions workflow must be on the repository's default branch.

In repository Settings → Actions → General, ensure Actions is enabled and the
workflow has permission to write repository contents. It commits only
`data/state.json`. Branch protection that prevents this bot from pushing will
break persistence; check that step after every initial test. If it fails, fix it
before enabling mail, otherwise assignments and reminders may repeat.

## 4. Run a public-page check without mail

Go to Actions → Reddit reviews → Run workflow. Choose `scan`; leave
`send_email` unchecked. Read Source health in the Check and notify logs.

- `ok`: readable post cards found; not a guarantee of complete coverage.
- `HTTP 403` / `HTTP 429`: access blocked or rate-limited. Do not evade it.
- No readable post cards: page layout, empty community or access wall.
- Network error/timeout: host networking or Reddit connectivity issue.

Check the Save assignment history step succeeded. If it found matching titles and
you configured employees, download the `email-previews` artifact to inspect drafts.
Zero relevant matches can be legitimate; failed sources are separately visible.
You can test SMTP with a test-only config containing YOUR address and a manually
submitted recent matching thread before adding the full team.

Manual input remains available when a source fails: add objects to
`data/manual_links.json`, using the actual title and UTC creation timestamp:

```json
[
  {
    "url": "https://www.reddit.com/r/Adulting/comments/REPLACE_ID/",
    "title": "REPLACE_WITH_ACTUAL_TITLE",
    "created_at": "2026-10-30T05:00:00+00:00"
  }
]
```

Use a real thread ID, current actual timestamp and a title matching the configured
topics. This example is not a live thread. Input still undergoes keyword/age
filtering. Do not submit private or removed content.

## 5. Configure email credentials privately

Your existing email provider must support authenticated SMTP with STARTTLS.
Ask its admin for SMTP settings and an app password if required. This version
supports password/app-password SMTP, not OAuth-only mail or implicit TLS port 465.
The sender provider's sending limits still apply; no new paid sender is required
by the code. Confirm your existing account permits automated team emails.

In Settings → Secrets and variables → Actions → Secrets, create:

| Secret | Value |
| --- | --- |
| SMTP_HOST | Your provider's SMTP hostname |
| SMTP_PORT | Normally 587 for STARTTLS; follow provider instructions |
| SMTP_USER | Login address/username |
| SMTP_PASSWORD | Provider-authorised app password or SMTP credential |
| SMTP_FROM | Authorised sender email address |

Never send passwords in chat or add them to `config.json`.

Run a manual `scan` with `send_email` checked once your preview is correct.
Checking `daily` forces the full daily list (including a no-pending-work message)
outside the usual morning window. Successful dry runs do not mark mail as sent.

## 6. Enable scheduled team mail

Under the same Settings page, Variables → New repository variable:

```
ENABLE_EMAIL = true
```

The workflow contains the UTC equivalents of:

| IST | What happens |
| --- | --- |
| 10:00 AM | Scan + full pending-work digest to every active employee |
| 12:00 PM | Scan + email newly assigned work |
| 4:00 PM | Scan + email newly assigned work |
| 10:00 PM | Scan + email newly assigned work |

The morning event explicitly requests a daily digest even if GitHub starts it
late. Scheduled runs are best effort, not exact-time guarantees. The coordinator
receives source health and overdue work on each scan if configured. Remove or set
`ENABLE_EMAIL=false` to stop scheduled mail. Disable the workflow to stop scans.

## 7. Record completion or skip

Emails ask employees to reply to the coordinator with task ID and their comment
permalink, or a reason to skip. Incoming mail is NOT read automatically.

Coordinator: Actions → Reddit reviews → Run workflow:

- Choose `complete`, paste task ID and the comment permalink from that thread.
- Or choose `skip`, paste task ID and a reason.
- Choose `list` to inspect task statuses in the workflow logs.

The same commands work locally:

```sh
python monitor.py list
python monitor.py complete --task abc123-d0 --comment-url https://www.reddit.com/r/Adulting/comments/abc123/title/comment123/
python monitor.py skip --task abc123-d2 --reason "No useful follow-up needed"
```

Completion validates the permalink's structure and thread ID; it does not verify
the comment's existence, author, or brand affiliation. A manager must check those.
Do not edit production state locally and on GitHub simultaneously.

## Review sequence and scope

Day 0, Day 2 and Day 10 are measured from the Reddit POST creation timestamp.
Each is a REVIEW opportunity, not a requirement for three promotional mentions.
An initial response has a target deadline of post time +24 hours; subsequent
review deadlines are +24 hours after their release dates, capped at Day 15.
Capacity shortages can make assignments overdue. Pending tasks expire at Day 15.
The coordinator sees overdue work; automatic reassignment is not implemented.

Employees read current community rules and the actual conversation before posting.
Do not respond where the community disallows brand participation. Follow-ups need
new useful context. Disclose affiliation; do not disguise employees as customers.
No vote coordination, user profiling or automatic comments are included.

Keyword exclusions are basic safeguards, not reliable age/medical/abuse detection.
Human review is required. The script does not automatically detect deleted or
locked threads, moderator rules or changed content during follow-ups. Employees
must check. Remove stored deleted content promptly when discovered. Records older
than 30 days are removed from current state, but Git history and retained workflow
artifacts may preserve old copies: this is a prototype, not a deletion-compliance
system. Limit repository access and remove sensitive/deleted records from history
where required before relying on it long term.

Email is at-least-once: a crash after the mail server accepts a message but before
history is saved can repeat it. A delivery error remains eligible for retry.
GitHub state saves are serialized between these workflow runs; avoid editing
`data/state.json` during a run. Monitor failed state commits.

## Troubleshooting and costs

There is no AI bill. Free hosted-runner minutes, artifact storage and your email
provider's limits still apply. Keep GitHub spending restricted to your intended
budget. With all sources timing out, runs use more minutes than successful scans.
Review usage after the first week, rather than assuming it stays free forever.

Live availability must be tested FROM YOUR GitHub runner. A local network failure
does not establish whether Reddit will allow that runner. If collection is
blocked there too, the collector is blocked; task management can still use links
submitted manually. This version does not promise a bypass.

Official setup references (checked 30 October 2026):

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://support.reddithelp.com/hc/en-us/articles/360043512931-Don-t-break-the-site

See VALIDATION.md for the checks actually run for this package.
