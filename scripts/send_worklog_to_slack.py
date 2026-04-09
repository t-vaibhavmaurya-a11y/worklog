#!/usr/bin/env python3
"""
Build the same by-day Jira worklog report as jira_worklog.py and post it to Slack.

Why not only Slack MCP?
  MCP runs when you chat in Cursor. For a fixed time every day, use either:
  - GitHub Actions: .github/workflows/jira-worklog-slack.yml (cron in UTC + repo Secrets), or
  - macOS launchd: scripts/launchd/worklog-slack.example.plist

  In CI, set JIRA_* and SLACK_WEBHOOK_URL as encrypted repository secrets (no credentials.env file).

Credentials (~/.cursor/credentials.env):
  JIRA_*          — same as jira_worklog.py
  SLACK_WEBHOOK_URL — Incoming Webhook URL (simplest; pick a private channel or DM hook)

Optional:
  REQUEST_VERIFY_SSL=false

Usage:
  python3 scripts/send_worklog_to_slack.py
  python3 scripts/send_worklog_to_slack.py --days 7 -z Asia/Kolkata
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


def _slack_webhook_post(text: str, webhook_url: str) -> None:
    try:
        import urllib3

        if os.environ.get("REQUEST_VERIFY_SSL", "true").lower() in ("false", "0", "no"):
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    import requests

    # Slack incoming webhook limit ~40k; keep headroom
    max_len = 35000
    truncated = text
    if len(truncated) > max_len:
        truncated = truncated[: max_len - 50] + "\n\n…(truncated)"

    payload = {"text": truncated}
    r = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=60,
        verify=os.environ.get("REQUEST_VERIFY_SSL", "true").lower()
        not in ("false", "0", "no"),
    )
    if r.status_code >= 400:
        raise SystemExit(
            f"Slack webhook error {r.status_code}: {(r.text or '')[:500]}"
        )


def main() -> int:
    _load_credentials()
    parser = argparse.ArgumentParser(
        description="Post Jira by-day worklog report to Slack (Incoming Webhook)."
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=1,
        metavar="N",
        help="Worklog lookback days (default: 1 = yesterday+today window per jira_worklog).",
    )
    parser.add_argument(
        "--timezone",
        "-z",
        metavar="IANA",
        help="Timezone for --by-day grouping, e.g. Asia/Kolkata.",
    )
    args = parser.parse_args()

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        raise SystemExit(
            "Set SLACK_WEBHOOK_URL: export it, add to ~/.cursor/credentials.env, "
            "or use a GitHub Actions secret (repo Settings → Secrets → Actions)."
        )

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
        report = "_No worklog entries in this period._"

    # Avoid ``` fences: worklog lines may contain backticks and break Slack formatting.
    header = "*Daily Jira worklog*\n"
    _slack_webhook_post(header + report, webhook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
