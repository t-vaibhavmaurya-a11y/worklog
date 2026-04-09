# Jira worklog → Slack

Posts your Jira worklog (by-day summary) to Slack via an **Incoming Webhook**. Optional **GitHub Actions** cron runs daily on GitHub’s servers.

## Repo layout

| Path | Purpose |
|------|--------|
| `scripts/jira_worklog.py` | Fetches issues with your worklogs, `--by-day` report |
| `scripts/send_worklog_to_slack.py` | Runs the report and POSTs to Slack |
| `scripts/launchd/worklog-slack.example.plist` | Optional: daily run on your Mac (not GitHub) |
| `.github/workflows/jira-worklog-slack.yml` | Scheduled + manual workflow |

## Local run

```bash
cd /path/to/jira-worklog-slack
pip install -r requirements.txt
export JIRA_SITE_URL="https://your-domain.atlassian.net"
export JIRA_USER_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-atlassian-api-token"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python3 scripts/send_worklog_to_slack.py --days 7 -z Asia/Kolkata
```

Or put the same variables in `~/.cursor/credentials.env` (they are read automatically if present).

## GitHub Actions

1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions** — add:
   - `JIRA_SITE_URL`
   - `JIRA_USER_EMAIL`
   - `JIRA_API_TOKEN`
   - `SLACK_WEBHOOK_URL`
3. **Actions → Jira worklog to Slack → Run workflow** to test.
4. Edit `.github/workflows/jira-worklog-slack.yml` — the `cron:` line is **UTC** only.

## Slack webhook

Slack app → **Incoming Webhooks** → add to workspace → copy URL into `SLACK_WEBHOOK_URL`.
