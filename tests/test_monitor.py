from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import monitor


class EvidenceTests(unittest.TestCase):
    def test_stale_missing_or_bad_evidence_never_green(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.yml"
            for value in ["invalid", "2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"]:
                path.write_text(f"status: up\nlastUpdated: {value}\nresponseTime: 42\n")
                with self.assertRaises(ValueError):
                    monitor.read_evidence(path, monitor.stamp())

    def test_retry_delivery_until_acknowledged(self):
        record = {"state": "unavailable"}
        def fail(_):
            raise RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            monitor.notify("hub", record, monitor.stamp(), fail)
        self.assertNotIn("delivered", record)
        sent = []
        monitor.notify("hub", record, monitor.stamp(), sent.append)
        monitor.notify("hub", record, monitor.stamp(), sent.append)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["status"], "firing")

    def test_recovery_requires_two_checks_and_matching_key(self):
        initial = {"state": "unavailable", "delivered": "firing"}
        one = monitor.advance(initial, "operational")
        self.assertEqual(one["state"], "unavailable")
        two = monitor.advance(one, "operational")
        self.assertEqual(two["state"], "operational")
        self.assertEqual(monitor.advance(one, "unavailable")["successes"], 0)
        sent = []
        monitor.notify("hub", two, monitor.stamp(), sent.append)
        self.assertEqual(sent[0]["status"], "resolved")
        self.assertEqual(sent[0]["deduplication_key"], monitor.alert_payload("hub", "unavailable", monitor.stamp())["deduplication_key"])

    def test_unknown_never_sends_recovery(self):
        sent = []
        monitor.notify("hub", {"state": "unknown", "delivered": "firing"}, monitor.stamp(), sent.append)
        self.assertEqual(sent, [])

    def test_public_events_and_maintenance_remain_visible(self):
        event = {"id": "public-1", "name": "An operator-confirmed incident", "status": "identified", "last_update_at": monitor.stamp()}
        maintenance = dict(event, id="maintenance-1", status="maintenance_in_progress")
        normalized = monitor.normalize_public_events({"ongoing_incidents": [event], "in_progress_maintenances": [maintenance]})
        self.assertEqual([entry["state"] for entry in normalized], ["identified", "monitoring"])
        with self.assertRaises((KeyError, ValueError)):
            monitor.normalize_public_events({})


if __name__ == "__main__":
    unittest.main()
