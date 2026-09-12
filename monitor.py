"""Publish bounded Upptime evidence and deliver deduplicated incident.io alerts.

Only public service metadata is published. Credentials never enter the report.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sys
import urllib.request

TARGETS = {"website": "Website", "hub": "PicoVolt Hub", "hub-api": "Hub API",
           "docs": "Documentation", "engine": "Browser engine delivery"}
ROOT = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return result


def read_evidence(path, started):
    # Upptime emits flat scalar YAML here. Read only these fixed fields; never
    # evaluate arbitrary YAML tags or payloads from a remote endpoint.
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"status", "lastUpdated", "responseTime", "code"}:
            fields[key] = value.strip().strip("\"'")
    observed = parse_time(fields["lastUpdated"])
    if observed < parse_time(started) or (observed - datetime.now(timezone.utc)).total_seconds() > 60:
        raise ValueError("missing fresh probe evidence")
    state = {"up": "operational", "down": "unavailable", "degraded": "degraded"}[fields["status"]]
    return state, max(0, int(fields["responseTime"]))


def advance(previous, observed):
    result = dict(previous)
    result["successes"] = min(2, previous.get("successes", 0) + 1) if observed == "operational" else 0
    # Upptime already retries failures. Require two successive successful runs
    # to clear a confirmed outage in the shared feed and incident.io.
    result["state"] = observed
    if observed == "operational" and previous.get("state") in {"unavailable", "degraded"} and result["successes"] < 2:
        result["state"] = previous["state"]
    return result


def alert_payload(identity, state, observed_at):
    return {"title": f"{TARGETS[identity]} availability check",
            "description": f"External HTTPS check: {state}. Observed {observed_at}. Check the monitoring evidence before describing customer impact.",
            "deduplication_key": f"picovolt-production-{identity}",
            "status": "resolved" if state == "operational" else "firing",
            "source_url": "https://github.com/MiniJe/picovolt-monitor/actions/workflows/uptime.yml",
            "metadata": {"service": identity, "environment": "production", "monitor": "upptime", "state": state}}


def deliver(payload, url, token):
    if url != "https://api.incident.io/v2/alert_events/http/01M2AAPG176859S1PCPZ18SRVA":
        raise ValueError("Unexpected alert destination")
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=15) as response:
        if not 200 <= response.status < 300:
            raise ValueError("Alert delivery rejected")


def notify(identity, record, observed_at, send):
    state = record["state"]
    if state == "unknown":
        return
    desired = "resolved" if state == "operational" else "firing"
    if record.get("delivered") == desired:
        return
    # Persist this marker only after success, so failures retry on the next run.
    send(alert_payload(identity, state, observed_at))
    record["delivered"] = desired


def normalize_public_events(summary):
    events = summary["ongoing_incidents"]
    maintenance = summary["in_progress_maintenances"]
    if not isinstance(events, list) or not isinstance(maintenance, list):
        raise ValueError("invalid public status feed")
    result = []
    for event in events + maintenance:
        status = event["status"]
        if status not in {"investigating", "identified", "monitoring", "maintenance_in_progress"}:
            raise ValueError("unrecognized active incident status")
        result.append({"id": str(event["id"])[:100], "source": "incident.io",
                       "title": str(event["name"])[:240],
                       "state": "monitoring" if status == "maintenance_in_progress" else status,
                       "updated_at": event["last_update_at"]})
    return result


def public_events():
    request = urllib.request.Request("https://status.picovolt.dev/api/v1/summary",
                                    headers={"Accept": "application/json", "User-Agent": "PicoVolt-External-Monitor"})
    with urllib.request.urlopen(request, timeout=10) as response:
        content = response.read(262145)
        if response.status != 200 or len(content) > 262144:
            raise ValueError("invalid public status response")
    return normalize_public_events(json.loads(content))


def main():
    started = os.environ["MONITOR_STARTED_AT"]
    state_path = ROOT / "monitor-state.json"
    report_path = ROOT / "api/status.json"
    prior = json.loads(state_path.read_text(encoding="utf-8"))
    previous_report = json.loads(report_path.read_text(encoding="utf-8"))
    now = stamp()
    records, components, errors = {}, [], []
    token, url = os.environ.get("INCIDENT_HTTP_TOKEN", ""), os.environ.get("INCIDENT_HTTP_URL", "")
    for identity, name in TARGETS.items():
        try:
            observed, latency = read_evidence(ROOT / "history" / (identity + ".yml"), started)
        except (OSError, ValueError, KeyError):
            observed, latency = "unknown", None
            errors.append(f"{identity}: fresh evidence missing")
        old = prior.get(identity, {})
        record = advance(old, observed)
        if observed == "unknown":
            # Keep an active outage in transition memory without presenting stale
            # evidence as current or sending a false recovery.
            record = dict(old, successes=0)
        records[identity] = record
        public_state = "unknown" if observed == "unknown" else record["state"]
        components.append({"id": identity, "name": name, "state": public_state,
                           "latency_ms": latency, "detail": "External HTTPS observation; not a guarantee of full user journey availability."})
        if observed != "unknown" and token and url:
            try:
                notify(identity, record, now, lambda payload: deliver(payload, url, token))
            except Exception:
                # Never log request headers, secret URL parameters or raw errors.
                errors.append(f"{identity}: alert delivery failed; will retry")
    if not token or not url:
        errors.append("incident.io delivery not configured")
    try:
        incidents = public_events()
    except Exception:
        incidents = previous_report.get("incidents", [])
        components.append({"id": "incident-feed", "name": "Incident updates", "state": "unknown",
                           "detail": "The public incident feed could not be verified."})
        errors.append("public incident feed unavailable")
    history = previous_report.get("history", [])[-287:]
    history.append({"observed_at": now, "passed": sum(c["state"] == "operational" for c in components), "total": len(components)})
    report = {"schema_version": 1, "generated_at": now, "max_age_seconds": 600,
              "monitoring_mode": "external_scheduled", "components": components,
              "history": history, "incidents": incidents, "status_page_url": "https://status.picovolt.dev/"}
    for path, data in [(state_path, records), (report_path, report)]:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    for component in components:
        print(component["name"] + ": " + component["state"])
    for error in errors:
        print(error, file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
