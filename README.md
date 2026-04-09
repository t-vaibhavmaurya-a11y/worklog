# Jira worklog → Slack or Gmail

Posts your Jira worklog (by-day summary) to **Slack** (Incoming Webhook) or **email** (Gmail SMTP + App Password). Optional **GitHub Actions** cron runs daily on GitHub’s servers, or use **launchd** on your Mac.

## Repo layout

| Path | Purpose |
|------|--------|
| `scripts/jira_worklog.py` | Fetches issues with your worklogs, `--by-day` report |
| `scripts/send_worklog_to_slack.py` | Runs the report and POSTs to Slack |
| `scripts/send_worklog_to_gmail.py` | Runs the report and emails via Gmail SMTP |
| `credentials.example.env` | Example env vars (copy ideas to `~/.cursor/credentials.env`; do not commit secrets) |
| `scripts/launchd/worklog-slack.example.plist` | Optional: daily Slack on your Mac |
| `scripts/launchd/worklog-gmail.example.plist` | Optional: daily Gmail on your Mac |
| `.github/workflows/jira-worklog-slack.yml` | Scheduled + manual → Slack |
| `.github/workflows/jira-worklog-gmail.yml` | Scheduled + manual → Gmail |

## Local run (Slack)

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

## Local run (Gmail)

1. Google Account → **Security** → **2-Step Verification** → **App passwords** → create one for Mail.
2. Set:

```bash
export JIRA_SITE_URL="https://your-domain.atlassian.net"
export JIRA_USER_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-atlassian-api-token"
export GMAIL_SMTP_USER="you@gmail.com"
export GMAIL_SMTP_PASSWORD="xxxx xxxx xxxx xxxx"   # 16 chars; spaces optional
export WORKLOG_EMAIL_TO="you@gmail.com"            # optional; defaults to GMAIL_SMTP_USER
python3 scripts/send_worklog_to_gmail.py --days 1 -z Asia/Kolkata
```

Or add those keys to `~/.cursor/credentials.env`. See `credentials.example.env`.

## GitHub Actions (Slack)

1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions** — add: `JIRA_SITE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`, `SLACK_WEBHOOK_URL`.
3. **Actions → Jira worklog to Slack → Run workflow** to test.
4. Edit `.github/workflows/jira-worklog-slack.yml` — the `cron:` line is **UTC** only.

## GitHub Actions (Gmail)

1. **Settings → Secrets and variables → Actions** — add:
   - `JIRA_SITE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`
   - `GMAIL_SMTP_USER` (sender Gmail)
   - `GMAIL_SMTP_PASSWORD` (App Password; can include spaces)
   - `WORKLOG_EMAIL_TO` (optional; omit to email yourself)
   - `WORKLOG_EMAIL_SUBJECT` (optional)
2. **Actions → Jira worklog to Gmail → Run workflow** to test.
3. Edit `.github/workflows/jira-worklog-gmail.yml` — `cron:` is **UTC** only.

## Slack webhook

Slack app → **Incoming Webhooks** → add to workspace → copy URL into `SLACK_WEBHOOK_URL`.

## Security

If an App Password or token was shared in chat or committed by mistake, **revoke it** in Google / Atlassian and create a new one.
