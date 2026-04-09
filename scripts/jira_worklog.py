#!/usr/bin/env python3
"""
Export issues where the current user logged work in the last N days (same idea as Jira JQL:
  worklogAuthor = currentUser() AND worklogDate >= -7d
).

Credentials: ~/.cursor/credentials.env (JIRA_SITE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN).
Optional: REQUEST_VERIFY_SSL=false

Usage:
  python3 scripts/jira_worklog.py --days 7
  python3 scripts/jira_worklog.py --7d
  python3 scripts/jira_worklog.py 7d
  python3 scripts/jira_worklog.py 7 -o worklogs.csv
  python3 scripts/jira_worklog.py --days 14 --details
  python3 scripts/jira_worklog.py --days 14 --by-day
  python3 scripts/jira_worklog.py --by-day -o summary.txt --timezone Asia/Kolkata

Shell alias (optional):
  alias worklog='python3 /path/to/fse-mgmt/scripts/jira_worklog.py'
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _load_credentials() -> None:
    creds_file = Path.home() / ".cursor" / "credentials.env"
    if creds_file.exists():
        with open(creds_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def _auth_headers() -> dict[str, str]:
    site_url = os.environ.get("JIRA_SITE_URL")
    email = os.environ.get("JIRA_USER_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not all([site_url, email, token]):
        raise SystemExit(
            "Missing JIRA_SITE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN. "
            "Set them in ~/.cursor/credentials.env"
        )
    credentials = f"{email}:{token}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _verify_ssl() -> bool:
    return os.environ.get("REQUEST_VERIFY_SSL", "true").lower() not in ("false", "0", "no")


def _maybe_disable_insecure_warnings() -> None:
    if _verify_ssl():
        return
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass


def _resolve_tz(tz_name: str | None) -> tzinfo:
    if tz_name:
        try:
            return ZoneInfo(tz_name.strip())
        except Exception as e:
            raise SystemExit(
                f"Invalid --timezone {tz_name!r}. Use an IANA name, e.g. Asia/Kolkata. ({e})"
            ) from e
    local = datetime.now().astimezone().tzinfo
    if local is not None:
        return local
    return timezone.utc


def _fmt_duration_seconds(sec: int) -> str:
    if sec <= 0:
        return "0m"
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if not parts:
        parts.append(f"{s}s" if s else "0m")
    return " ".join(parts)


def _truncate(s: str, max_len: int = 72) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def collect_user_worklog_entries(
    site_url: str,
    api_prefix: str,
    headers: dict[str, str],
    issues: list[dict[str, Any]],
    account_id: str,
    cutoff_utc: datetime,
) -> list[dict[str, Any]]:
    """Raw worklog rows for current user with started >= cutoff (UTC)."""
    rows: list[dict[str, Any]] = []
    for issue in issues:
        key = issue.get("key") or ""
        fields = issue.get("fields") or {}
        summary = fields.get("summary") or ""
        worklogs = fetch_all_worklogs(site_url, api_prefix, headers, key)
        for wl in worklogs:
            author = wl.get("author") or {}
            aid = author.get("accountId") or author.get("name")
            if aid != account_id:
                continue
            started_raw = wl.get("started") or ""
            started_dt = _parse_worklog_started(started_raw)
            if not started_dt:
                continue
            if started_dt.astimezone(timezone.utc) < cutoff_utc:
                continue
            sec = int(wl.get("timeSpentSeconds") or 0)
            rows.append(
                {
                    "started_dt": started_dt,
                    "issue_key": key,
                    "summary": summary,
                    "seconds": sec,
                }
            )
    rows.sort(key=lambda r: r["started_dt"], reverse=True)
    return rows


def build_by_day_report(
    entries: list[dict[str, Any]],
    tz: tzinfo,
    days_lookback: int,
) -> str:
    """
    Group entries by local calendar day (newest day first).
    Within each day, aggregate seconds per issue; issues sorted by time desc.
    """
    # local_date -> issue_key -> {seconds, summary}
    per_day: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
    for e in entries:
        started: datetime = e["started_dt"]
        local_d = started.astimezone(tz).date()
        key = e["issue_key"]
        bucket = per_day[local_d].setdefault(
            key, {"seconds": 0, "summary": e["summary"]}
        )
        bucket["seconds"] += int(e["seconds"])

    sorted_days = sorted(per_day.keys(), reverse=True)
    lines: list[str] = []
    width = 78
    sep = "═" * width
    thin = "─" * width

    total_sec = sum(e["seconds"] for e in entries)
    lines.append(sep)
    lines.append(
        f"  Worklog summary — last {days_lookback} days  │  "
        f"total {_fmt_duration_seconds(total_sec)}  │  {len(sorted_days)} day(s)"
    )
    lines.append(sep)
    lines.append("")

    for d in sorted_days:
        issues_map = per_day[d]
        day_total = sum(v["seconds"] for v in issues_map.values())
        weekday = d.strftime("%A")
        lines.append(thin)
        lines.append(
            f"  {weekday}, {d.strftime('%d %b %Y')}  →  {_fmt_duration_seconds(day_total)}"
        )
        lines.append(thin)
        ranked = sorted(
            issues_map.items(), key=lambda kv: kv[1]["seconds"], reverse=True
        )
        for issue_key, info in ranked:
            t = _fmt_duration_seconds(int(info["seconds"]))
            summ = _truncate(str(info["summary"]), 68)
            lines.append(f"    {t:>8}   {issue_key:12}  {summ}")
        lines.append("")

    lines.append(sep)
    return "\n".join(lines)


def _jira_get(
    site_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as e:
        raise SystemExit("Install requests: pip install requests") from e

    url = f"{site_url.rstrip('/')}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=60, verify=_verify_ssl())
    if resp.status_code >= 400:
        raise SystemExit(
            f"Jira API error {resp.status_code} for {path}: {(resp.text or '')[:800]}"
        )
    return resp.json()


def _jira_post_json(
    site_url: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as e:
        raise SystemExit("Install requests: pip install requests") from e

    h = {**headers, "Content-Type": "application/json"}
    url = f"{site_url.rstrip('/')}{path}"
    resp = requests.post(url, headers=h, json=body, timeout=60, verify=_verify_ssl())
    if resp.status_code >= 400:
        raise SystemExit(
            f"Jira API error {resp.status_code} for {path}: {(resp.text or '')[:800]}"
        )
    return resp.json()


def _pick_api_prefix(site_url: str, headers: dict[str, str]) -> str:
    """Use REST v3 when possible; fall back to v2 (some Jira Server instances)."""
    try:
        import requests
    except ImportError as e:
        raise SystemExit("Install requests: pip install requests") from e

    errors: list[str] = []
    for prefix in ("/rest/api/3", "/rest/api/2"):
        url = f"{site_url.rstrip('/')}{prefix}/myself"
        r = requests.get(url, headers=headers, timeout=30, verify=_verify_ssl())
        if r.status_code == 200:
            return prefix
        snippet = (r.text or "")[:300].replace("\n", " ")
        errors.append(f"{prefix}/myself -> HTTP {r.status_code}: {snippet}")
    raise SystemExit(
        "Could not reach Jira /myself on API v3 or v2. Check URL, token, and permissions.\n"
        + "\n".join(errors)
    )


def _format_jira_datetime(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        # Jira often returns "2026-04-06T19:56:00.000+0530" or Z suffix
        s = iso.replace("Z", "+00:00")
        if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d/%b/%y %I:%M %p")
    except (ValueError, TypeError):
        return iso


def _user_display(user: dict[str, Any] | None) -> tuple[str, str]:
    if not user:
        return "", ""
    return user.get("displayName") or "", user.get("accountId") or user.get("name") or ""


def _seconds_str(sec: int | None) -> str:
    if sec is None:
        return ""
    return str(int(sec))


def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        return "".join(_adf_to_text(c) for c in node.get("content", []) or [])
    if isinstance(node, list):
        return "".join(_adf_to_text(c) for c in node)
    return ""


def search_issues(
    site_url: str,
    api_prefix: str,
    headers: dict[str, str],
    jql: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    max_results = 100

    # Jira Cloud removed GET/POST /rest/api/3/search (410); use /search/jql (token pagination).
    if api_prefix.endswith("/rest/api/3"):
        next_token: str | None = None
        while True:
            body: dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": fields,
            }
            if next_token:
                body["nextPageToken"] = next_token
            data = _jira_post_json(site_url, f"{api_prefix}/search/jql", headers, body)
            batch = data.get("issues") or []
            issues.extend(batch)
            if data.get("isLast") or not batch:
                break
            next_token = data.get("nextPageToken")
            if not next_token:
                break
        return issues

    # Jira Server / legacy v2: classic search with startAt.
    start_at = 0
    while True:
        params: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ",".join(fields),
        }
        data = _jira_get(site_url, f"{api_prefix}/search", headers, params=params)
        batch = data.get("issues") or []
        issues.extend(batch)
        total = data.get("total", len(issues))
        start_at += len(batch)
        if start_at >= total or not batch:
            break
    return issues


def fetch_all_worklogs(
    site_url: str,
    api_prefix: str,
    headers: dict[str, str],
    issue_key: str,
) -> list[dict[str, Any]]:
    all_logs: list[dict[str, Any]] = []
    start_at = 0
    max_results = 100
    while True:
        params = {"startAt": start_at, "maxResults": max_results}
        data = _jira_get(
            site_url, f"{api_prefix}/issue/{issue_key}/worklog", headers, params=params
        )
        worklogs = data.get("worklogs") or []
        all_logs.extend(worklogs)
        total = data.get("total", len(all_logs))
        start_at += len(worklogs)
        if start_at >= total or not worklogs:
            break
    return all_logs


def _parse_worklog_started(started: str) -> datetime | None:
    if not started:
        return None
    s = started.replace("Z", "+00:00")
    if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def issue_to_csv_row(issue: dict[str, Any]) -> list[str]:
    fields = issue.get("fields") or {}
    it = fields.get("issuetype") or {}
    assignee_name, assignee_id = _user_display(fields.get("assignee"))
    reporter_name, reporter_id = _user_display(fields.get("reporter"))
    pr = fields.get("priority") or {}
    st = fields.get("status") or {}
    res = fields.get("resolution") or {}
    return [
        it.get("name") or "",
        issue.get("key") or "",
        str(issue.get("id") or ""),
        (fields.get("summary") or "").replace("\n", " ").replace("\r", ""),
        assignee_name,
        assignee_id,
        reporter_name,
        reporter_id,
        pr.get("name") or "",
        st.get("name") or "",
        res.get("name") or "",
        _format_jira_datetime(fields.get("created")),
        _format_jira_datetime(fields.get("updated")),
        _format_jira_datetime(fields.get("duedate")),
        _seconds_str(fields.get("timeoriginalestimate")),
        _seconds_str(fields.get("aggregatetimespent")),
        _seconds_str(fields.get("aggregateoriginalestimate")),
    ]


CSV_HEADER = [
    "Issue Type",
    "Issue key",
    "Issue id",
    "Summary",
    "Assignee",
    "Assignee Id",
    "Reporter",
    "Reporter Id",
    "Priority",
    "Status",
    "Resolution",
    "Created",
    "Updated",
    "Due date",
    "Original estimate",
    "Σ Time Spent",
    "Σ Original Estimate",
]


def preprocess_argv(argv: list[str]) -> list[str]:
    """Turn --7d / --14d into --days 7 / --days 14."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        m = re.fullmatch(r"--(\d+)d", a, flags=re.IGNORECASE)
        if m:
            out.extend(["--days", m.group(1)])
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def parse_days_from_positional(s: str | None) -> int | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+)d?", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def main() -> int:
    _load_credentials()
    raw = preprocess_argv(sys.argv[1:])
    parser = argparse.ArgumentParser(
        description="Export Jira issues with your worklogs in the last N days."
    )
    parser.add_argument(
        "days_positional",
        nargs="?",
        default=None,
        help="Days lookback as 7 or 7d (optional if --days is set).",
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=None,
        metavar="N",
        help="Number of days for worklogDate >= -Nd (default: 7).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write issue-level CSV to this file (UTF-8). Default: print to stdout.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Also print each worklog entry (you, in range) to stderr or --details-csv.",
    )
    parser.add_argument(
        "--details-csv",
        metavar="PATH",
        help="Write per-worklog rows to this CSV file (requires --details).",
    )
    out_mode = parser.add_mutually_exclusive_group()
    out_mode.add_argument(
        "--json",
        action="store_true",
        help="Print issues as JSON instead of CSV.",
    )
    out_mode.add_argument(
        "--by-day",
        action="store_true",
        help="Print a day-wise summary (newest days first); uses your local timezone unless --timezone is set.",
    )
    parser.add_argument(
        "--timezone",
        "-z",
        metavar="IANA",
        help="Timezone for grouping days, e.g. Asia/Kolkata. Default: system local timezone.",
    )
    args = parser.parse_args(raw)

    days = args.days
    if days is None:
        days = parse_days_from_positional(args.days_positional)
    if days is None:
        days = 7
    if days < 1:
        parser.error("days must be >= 1")

    _maybe_disable_insecure_warnings()

    site_url = os.environ.get("JIRA_SITE_URL", "").rstrip("/")
    headers = _auth_headers()
    api_prefix = _pick_api_prefix(site_url, headers)

    myself = _jira_get(site_url, f"{api_prefix}/myself", headers)
    account_id = myself.get("accountId") or myself.get("name")
    if not account_id:
        raise SystemExit("Could not read accountId from Jira /myself response.")

    jql = f'worklogAuthor = currentUser() AND worklogDate >= -{days}d'
    field_list = [
        "summary",
        "issuetype",
        "assignee",
        "reporter",
        "priority",
        "status",
        "resolution",
        "created",
        "updated",
        "duedate",
        "timeoriginalestimate",
        "aggregatetimespent",
        "aggregateoriginalestimate",
    ]

    issues = search_issues(site_url, api_prefix, headers, jql, field_list)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if args.by_day:
        tz = _resolve_tz(args.timezone)
        entries = collect_user_worklog_entries(
            site_url, api_prefix, headers, issues, account_id, cutoff
        )
        report = build_by_day_report(entries, tz, days)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
        else:
            sys.stdout.write(report)
            if not report.endswith("\n"):
                sys.stdout.write("\n")
        if args.details:
            _emit_details_csv(
                site_url,
                api_prefix,
                headers,
                issues,
                account_id,
                cutoff,
                args.details_csv,
            )
        return 0

    if args.json:
        out = sys.stdout if not args.output else open(args.output, "w", encoding="utf-8")
        try:
            json.dump(issues, out, indent=2)
            out.write("\n")
        finally:
            if args.output:
                out.close()
        return 0

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for issue in issues:
        writer.writerow(issue_to_csv_row(issue))
    csv_text = buf.getvalue()

    if args.output:
        Path(args.output).write_text(csv_text, encoding="utf-8")
    else:
        sys.stdout.write(csv_text)

    if args.details:
        _emit_details_csv(
            site_url,
            api_prefix,
            headers,
            issues,
            account_id,
            cutoff,
            args.details_csv,
        )

    return 0


def _emit_details_csv(
    site_url: str,
    api_prefix: str,
    headers: dict[str, str],
    issues: list[dict[str, Any]],
    account_id: str,
    cutoff: datetime,
    details_csv_path: str | None,
) -> None:
    detail_rows: list[list[str]] = []
    detail_header = [
        "Issue key",
        "Worklog id",
        "Started",
        "Time spent (seconds)",
        "Time spent (human)",
        "Comment",
    ]
    for issue in issues:
        key = issue.get("key") or ""
        worklogs = fetch_all_worklogs(site_url, api_prefix, headers, key)
        for wl in worklogs:
            author = wl.get("author") or {}
            aid = author.get("accountId") or author.get("name")
            if aid != account_id:
                continue
            started_raw = wl.get("started") or ""
            started_dt = _parse_worklog_started(started_raw)
            if started_dt and started_dt.astimezone(timezone.utc) < cutoff:
                continue
            sec = int(wl.get("timeSpentSeconds") or 0)
            comment = wl.get("comment")
            if isinstance(comment, dict):
                comment = _adf_to_text(comment).strip()
            else:
                comment = (comment or "").strip() if comment else ""
            h = f"{sec // 3600}h {(sec % 3600) // 60}m" if sec else "0h 0m"
            detail_rows.append(
                [
                    key,
                    str(wl.get("id") or ""),
                    started_raw,
                    str(sec),
                    h,
                    comment.replace("\n", " ").replace("\r", ""),
                ]
            )

    detail_buf = io.StringIO()
    dw = csv.writer(detail_buf)
    dw.writerow(detail_header)
    for row in detail_rows:
        dw.writerow(row)
    detail_text = detail_buf.getvalue()

    if details_csv_path:
        Path(details_csv_path).write_text(detail_text, encoding="utf-8")
    else:
        print(detail_text, file=sys.stderr, end="")


if __name__ == "__main__":
    sys.exit(main())
