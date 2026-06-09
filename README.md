# Internship alert bot

Automatically searches free, official job APIs for **internship / working-student
roles in Germany and Europe** that match your skills, and emails you a daily
digest of anything new. Runs itself on GitHub Actions — no server, no cost.

Sources used (both free and ToS-friendly — no scraping of LinkedIn/Indeed):
- **Arbeitnow** — free, no key, Europe-focused, surfaces English-language and
  visa-sponsorship roles.
- **Adzuna** — free developer key, covers Germany + EU with good filtering.

## How it works

1. Fetches recent postings from both APIs.
2. Keeps only jobs that mention one of your `KEYWORDS` **and** look like a
   student/intern role (`internship`, `Praktikum`, `Werkstudent`, ...).
3. Remembers what it already sent (`seen_jobs.json`) so you only get new hits.
4. Emails you a clean digest.

## Tune it to your portfolio

Open `job_alert.py` and edit the `CONFIG` block near the top:
- `KEYWORDS` — the skills/technologies from your portfolio website.
- `INTERNSHIP_TERMS` — student role terms (defaults cover German + English).
- `ADZUNA_COUNTRIES` / `ADZUNA_QUERIES` — which countries and searches to run.

## Run it locally first (recommended)

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your values
set -a; source .env; set +a
DRY_RUN=1 python job_alert.py   # prints the digest instead of emailing
```

When the output looks right, set `DRY_RUN=0` to actually send.

### Gmail note
`SMTP_PASS` must be a Google **App Password**, not your normal password:
Google Account → Security → 2-Step Verification → App passwords.
Other providers work too — just set `SMTP_HOST` / `SMTP_PORT` accordingly.

### Adzuna key (optional but recommended)
Register at https://developer.adzuna.com to get a free `app_id` and `app_key`.
Without them the bot still runs using Arbeitnow only.

## Deploy on GitHub Actions (free daily runs)

1. Push this folder to a new GitHub repo.
2. In the repo: **Settings → Secrets and variables → Actions → New repository
   secret**, and add: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `SMTP_HOST`,
   `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `EMAIL_TO`.
3. The workflow in `.github/workflows/job-alert.yml` runs daily at 07:00 UTC.
   Trigger it manually anytime from the **Actions** tab to test.

That's it — you'll start getting a daily email whenever new matching
internships appear.
