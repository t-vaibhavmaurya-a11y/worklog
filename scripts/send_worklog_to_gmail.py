#!/usr/bin/env python3
"""
Build the same by-day Jira worklog report as jira_worklog.py and email it via Gmail SMTP.

Credentials (~/.cursor/credentials.env or env):
  JIRA_SITE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN  — same as jira_worklog.py
  GMAIL_SMTP_USER     — full Gmail address (sender)
  GMAIL_SMTP_PASSWORD — Google App Password (16 chars; spaces ignored)
  WORKLOG_EMAIL_TO    — recipient (often same as GMAIL_SMTP_USER)

Optional:
  WORKLOG_EMAIL_SUBJECT — default: "Daily Jira worklog"
  REQUEST_VERIFY_SSL

Usage:
  python3 scripts/send_worklog_to_gmail.py
  python3 scripts/send_worklog_to_gmail.py --days 7 -z Asia/Kolkata
"""

from __future__ import annotations

import argparse
import os
import re
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path


def _load_credentials() -> None:
    creds_file = Path.home() / ".cursor" / "credentials.env"
    if creds_file.exists():
        with open(creds_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def _normalize_app_password(raw: str) -> str:
    s = raw.strip().replace(" ", "")
    if not re.fullmatch(r"[a-zA-Z0-9]{16}", s):
        raise SystemExit(
            "GMAIL_SMTP_PASSWORD must be a 16-character Google App Password "
            "(letters only; spaces are OK in the env value)."
        )
    return s


def _send_gmail_smtp(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    password: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=120) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(from_addr, password)
        smtp.send_message(msg)


def main() -> int:
    _load_credentials()
    parser = argparse.ArgumentParser(
        description="Email Jira by-day worklog report via Gmail SMTP (App Password)."
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=1,
        metavar="N",
        help="Worklog lookback days (default: 1).",
    )
    parser.add_argument(
        "--timezone",
        "-z",
        metavar="IANA",
        help="Timezone for --by-day grouping, e.g. Asia/Kolkata.",
    )
    args = parser.parse_args()

    gmail_user = os.environ.get("GMAIL_SMTP_USER", "").strip()
    raw_pw = os.environ.get("GMAIL_SMTP_PASSWORD", "").strip()
    to_addr = os.environ.get("WORKLOG_EMAIL_TO", "").strip() or gmail_user
    subject = (
        os.environ.get("WORKLOG_EMAIL_SUBJECT", "").strip() or "Daily Jira worklog"
    )

    if not gmail_user:
        raise SystemExit(
            "Set GMAIL_SMTP_USER (sender Gmail address): export, "
            "~/.cursor/credentials.env, or GitHub Actions secret."
        )
    if not raw_pw:
        raise SystemExit(
            "Set GMAIL_SMTP_PASSWORD (Google App Password): export, "
            "~/.cursor/credentials.env, or GitHub Actions secret."
        )
    password = _normalize_app_password(raw_pw)

    script_dir = Path(__file__).resolve().parent
    jira_script = script_dir / "jira_worklog.py"
    if not jira_script.is_file():
        raise SystemExit(f"Missing {jira_script}")

    cmd = [
        sys.executable,
        str(jira_script),
        "--by-day",
        "--days",
        str(args.days),
    ]
    if args.timezone:
        cmd.extend(["--timezone", args.timezone])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(
            f"jira_worklog.py failed ({proc.returncode}): {err[:1200]}"
        )

    report = proc.stdout.strip()
    if not report:
        report = "(No worklog entries in this period.)"

    max_len = 900_000
    if len(report) > max_len:
        report = report[: max_len - 80] + "\n\n…(truncated)"

    body = "Daily Jira worklog\n\n" + report

    _send_gmail_smtp(
        from_addr=gmail_user,
        to_addr=to_addr,
        subject=subject,
        body=body,
        password=password,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
