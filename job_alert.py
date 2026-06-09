"""
Internship alert bot.

Searches free, official job APIs (Arbeitnow + Adzuna) for internship /
working-student roles in Germany and the rest of Europe that match your
skills, then emails you a digest of anything new since the last run.

Designed to run on a daily schedule via GitHub Actions, but you can also
run it locally:  python job_alert.py

Set DRY_RUN=1 to print the digest to the console instead of sending email.
"""

import os
import json
import html
import smtplib
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlencode

import requests

# ---------------------------------------------------------------------------
# CONFIG  --  edit these to match YOUR portfolio / target roles
# ---------------------------------------------------------------------------

# Skills/keywords to look for. Tune these to mirror your portfolio website.
# A job must mention at least ONE of these to be considered relevant.
KEYWORDS = [
    # security
    "cyber", "secur", "appsec", "infosec", "vulnerab",
    "penetration", "pentest", "soc", "blue team", "red team",
    "detection", "incident", "malware", "forensic",
    # software / dev
    "software", "develop", "engineer", "devops", "cloud",
    # your languages -- EDIT this line to match your portfolio
    "python", "java", "javascript", "typescript",
]

# A job must ALSO look like an internship / student role.
INTERNSHIP_TERMS = [
    "intern", "internship", "praktikum", "praktikant",
    "working student", "werkstudent", "thesis", "abschlussarbeit",
]

# Adzuna country codes to search (de = Germany, plus a few EU neighbours).
ADZUNA_COUNTRIES = ["de", "nl", "ie", "at", "ch"]

# Search phrases sent to Adzuna (it does full-text search).
ADZUNA_QUERIES = [
    "cybersecurity internship",
    "security working student",
    "software engineering internship",
    "informatik praktikum",
]

# How many Arbeitnow pages to scan (100 jobs per page, newest first).
ARBEITNOW_PAGES = 5

# Ignore postings older than this many days.
MAX_DAYS_OLD = 30

# File used to remember which jobs were already emailed.
SEEN_FILE = "seen_jobs.json"

# ---------------------------------------------------------------------------
# Secrets / environment (set as GitHub Actions secrets or in a local .env)
# ---------------------------------------------------------------------------
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.environ.get("EMAIL_TO", SMTP_USER)

DRY_RUN = os.environ.get("DRY_RUN", "") not in ("", "0", "false", "False")

HEADERS = {"User-Agent": "internship-alert-bot (personal job search)"}
TIMEOUT = 30


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_arbeitnow():
    """Pull recent jobs from the free Arbeitnow board API (no key needed)."""
    jobs = []
    url = "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(ARBEITNOW_PAGES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"[arbeitnow] fetch failed: {exc}")
            break

        for item in payload.get("data", []):
            created = item.get("created_at")
            posted = (
                dt.datetime.utcfromtimestamp(created).date().isoformat()
                if isinstance(created, (int, float))
                else ""
            )
            jobs.append(
                {
                    "title": item.get("title", "").strip(),
                    "company": item.get("company_name", "").strip(),
                    "location": item.get("location", "").strip(),
                    "url": item.get("url", "").strip(),
                    "text": " ".join(
                        [
                            item.get("title", ""),
                            item.get("description", ""),
                            " ".join(item.get("tags", []) or []),
                            " ".join(item.get("job_types", []) or []),
                        ]
                    ).lower(),
                    "posted": posted,
                    "source": "Arbeitnow",
                }
            )

        next_url = (payload.get("links") or {}).get("next")
        if not next_url:
            break
        url = next_url
    return jobs


def fetch_adzuna():
    """Pull jobs from Adzuna for each configured country (needs a free key)."""
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        print("[adzuna] no API key set, skipping (Arbeitnow only)")
        return []

    jobs = []
    for country in ADZUNA_COUNTRIES:
        for query in ADZUNA_QUERIES:
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "what": query,
                "results_per_page": 50,
                "max_days_old": MAX_DAYS_OLD,
                "content-type": "application/json",
            }
            base = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?"
            try:
                resp = requests.get(base + urlencode(params),
                                    headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                print(f"[adzuna] {country}/'{query}' failed: {exc}")
                continue

            for item in payload.get("results", []):
                jobs.append(
                    {
                        "title": item.get("title", "").strip(),
                        "company": (item.get("company") or {}).get(
                            "display_name", ""
                        ).strip(),
                        "location": (item.get("location") or {}).get(
                            "display_name", ""
                        ).strip(),
                        "url": item.get("redirect_url", "").strip(),
                        "text": " ".join(
                            [item.get("title", ""), item.get("description", "")]
                        ).lower(),
                        "posted": (item.get("created", "") or "")[:10],
                        "source": f"Adzuna ({country.upper()})",
                    }
                )
    return jobs


# ---------------------------------------------------------------------------
# Filtering & dedup
# ---------------------------------------------------------------------------
def is_relevant(job):
    text = job["text"]
    has_skill = any(kw in text for kw in KEYWORDS)
    has_intern = any(term in text for term in INTERNSHIP_TERMS)
    return has_skill and has_intern


def job_key(job):
    return job["url"] or f"{job['title']}|{job['company']}".lower()


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def save_seen(seen):
    cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    with open(SEEN_FILE, "w", encoding="utf-8") as fh:
        json.dump(pruned, fh, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def build_html(new_jobs):
    today = dt.date.today().isoformat()
    rows = []
    for job in new_jobs:
        title = html.escape(job["title"] or "Untitled role")
        company = html.escape(job["company"] or "Unknown company")
        location = html.escape(job["location"] or "")
        source = html.escape(job["source"])
        posted = html.escape(job["posted"])
        url = html.escape(job["url"], quote=True)
        rows.append(
            f"""
            <div style="padding:14px 0;border-bottom:1px solid #e5e5e5;">
              <a href="{url}" style="font-size:16px;font-weight:600;
                 color:#1a4fa0;text-decoration:none;">{title}</a>
              <div style="font-size:14px;color:#333;margin-top:2px;">
                {company}{' &middot; ' + location if location else ''}
              </div>
              <div style="font-size:12px;color:#888;margin-top:2px;">
                {source}{' &middot; posted ' + posted if posted else ''}
              </div>
            </div>"""
        )

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;
                margin:0 auto;color:#111;">
      <h2 style="font-weight:600;">{len(new_jobs)} new internship match(es)
         &mdash; {today}</h2>
      <p style="font-size:13px;color:#666;">
        Germany &amp; Europe &middot; filtered to your skills and student roles.
      </p>
      {''.join(rows)}
      <p style="font-size:12px;color:#999;margin-top:20px;">
        Sent by your internship-alert bot. Edit KEYWORDS in job_alert.py to
        retune what it looks for.
      </p>
    </div>"""


def send_email(subject, html_body):
    if DRY_RUN or not (SMTP_USER and SMTP_PASS):
        print("----- DRY RUN: email not sent -----")
        print("Subject:", subject)
        print(html_body)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    print(f"Email sent to {EMAIL_TO}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_jobs = fetch_arbeitnow() + fetch_adzuna()
    print(f"Fetched {len(all_jobs)} jobs total.")

    relevant = [j for j in all_jobs if is_relevant(j)]
    print(f"{len(relevant)} match skills + internship filters.")

    # Dedupe within this run.
    unique = {}
    for job in relevant:
        unique.setdefault(job_key(job), job)

    seen = load_seen()
    today = dt.date.today().isoformat()
    new_jobs = [j for key, j in unique.items() if key not in seen]
    print(f"{len(new_jobs)} are new since last run.")

    if not new_jobs:
        print("Nothing new today. No email sent.")
        return

    new_jobs.sort(key=lambda j: j["posted"], reverse=True)
    subject = f"{len(new_jobs)} new internship match(es) in Germany/Europe"
    send_email(subject, build_html(new_jobs))

    for key in unique:
        seen[key] = today
    save_seen(seen)


if __name__ == "__main__":
    main()
