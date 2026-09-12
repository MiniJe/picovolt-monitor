# PicoVolt external monitoring

Independent public HTTPS checks run by [Upptime](https://github.com/upptime/upptime)
on GitHub Actions. Customer-facing incident updates: **https://status.picovolt.dev/**.

Checks cover the website, Hub HTML, Hub API health, documentation and browser
engine delivery. No customer accounts, customer data or proprietary engine source
are stored here. The API check does not exercise account sign-in, and the binary
check verifies HTTP delivery, not execution or cryptographic integrity.

The schedule requests a run every five minutes. GitHub can delay or drop scheduled
runs; this is not an SLA or continuous coverage. Consumers must treat the report
as **unknown after ten minutes**, including if GitHub itself is unavailable.

- `history/`: Upptime timestamped evidence and response times.
- GitHub Issues: automatic Upptime outage and recovery records; short incidents
  are preserved. Watch this repository's Issues and Actions for GitHub notifications.
- `api/status.json`: public versioned snapshot for website banners, with a rolling
  day of samples. No historical uptime percentage is claimed.
- `monitor.py`: incident.io HTTP ingestion adapter. Failures are retried by
  Upptime; two successful runs clear a confirmed outage. Delivery failures retry
  without acknowledging locally. Missing evidence never sends a recovery.

Repository secret `INCIDENT_HTTP_TOKEN` and variable `INCIDENT_HTTP_URL` configure
the dedicated incident.io HTTP source. This uses supported alert ingestion, not
the paid general API. An alert route and public-page workflow must be configured
in incident.io separately; receiving an alert alone does not publish an incident.

## Maintenance

Run `python -m unittest discover -s tests -v`. Check the Actions tab after changes.
Actions use pinned commits and an ephemeral repository token; no personal access
token is supplied to the runner. The only persistent secret is scoped to the
PicoVolt alert source. Never paste it into code, issues or logs.

Standard GitHub-hosted runners are free for this public repository. No paid
monitoring plan is required. GitHub can disable inactive schedules after 60 days;
inspect the Actions page if observations become stale. No automatic deployment,
customer credential tests, destructive recovery or server restarts are performed.

New adapter and configuration code in this repository are MIT licensed.
This does not change the license of PicoVolt or its releases.
