"""Event normalizers for monitoring module."""

from django.utils import timezone


class GenericNormalizer:
    """Generic normalization adapter for monitoring events."""

    REQUIRED_FIELDS = ["event_type", "event_state", "severity", "title"]

    def normalize(self, raw_payload):
        """Normalize a raw monitoring event payload into canonical form."""
        normalized = {
            "source_event_id": raw_payload.get("source_event_id", ""),
            "event_type": raw_payload.get("event_type", ""),
            "event_state": raw_payload.get("event_state", "firing"),
            "severity": raw_payload.get("severity", "info"),
            "title": raw_payload.get("title", ""),
            "summary": raw_payload.get("summary", ""),
            "occurred_at": raw_payload.get("occurred_at", timezone.now()),
            "target_type": raw_payload.get("target_type", "unknown"),
            "target_identifier": raw_payload.get("target_identifier", ""),
            "hostname": raw_payload.get("hostname", ""),
            "ip_address": raw_payload.get("ip_address", ""),
            "service_name": raw_payload.get("service_name", ""),
            "metric_name": raw_payload.get("metric_name", ""),
            "metric_value": raw_payload.get("metric_value", ""),
            "threshold": raw_payload.get("threshold", ""),
            "environment": raw_payload.get("environment", ""),
            "metadata": raw_payload.get("metadata", {}),
        }
        return normalized

    def validate(self, normalized):
        """Validate normalized event data."""
        errors = []
        for field in self.REQUIRED_FIELDS:
            if not normalized.get(field):
                errors.append(f"Missing required field: {field}")

        valid_states = ["firing", "recovered", "informational", "unknown"]
        if normalized.get("event_state") not in valid_states:
            errors.append(f"Invalid event_state: {normalized.get('event_state')}")

        valid_severities = ["info", "warning", "minor", "major", "critical"]
        if normalized.get("severity") not in valid_severities:
            errors.append(f"Invalid severity: {normalized.get('severity')}")

        return errors


class PrometheusNormalizer:
    """Prometheus Alertmanager payload normalizer."""

    def normalize(self, raw_payload):
        """Normalize Prometheus Alertmanager webhook payload."""
        alerts = raw_payload.get("alerts", [])
        if not alerts:
            return []

        results = []
        for alert in alerts:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})

            results.append({
                "source_event_id": alert.get("fingerprint", ""),
                "event_type": labels.get("alertname", "unknown"),
                "event_state": alert.get("status", "firing"),
                "severity": labels.get("severity", "warning"),
                "title": annotations.get("summary", labels.get("alertname", "")),
                "summary": annotations.get("description", ""),
                "occurred_at": alert.get("startsAt", timezone.now()),
                "target_type": labels.get("target_type", "host"),
                "target_identifier": labels.get("instance", ""),
                "hostname": labels.get("instance", ""),
                "metric_name": labels.get("alertname", ""),
                "metadata": {"alertname": labels.get("alertname", "")},
            })
        return results


class ZabbixNormalizer:
    """Zabbix webhook-like payload normalizer."""

    def normalize(self, raw_payload):
        """Normalize Zabbix webhook payload."""
        return [{
            "source_event_id": str(raw_payload.get("eventid", "")),
            "event_type": raw_payload.get("eventname", "unknown"),
            "event_state": "firing" if raw_payload.get("status") == "PROBLEM" else "recovered",
            "severity": self._map_zabbix_severity(raw_payload.get("severity", "")),
            "title": raw_payload.get("eventname", ""),
            "summary": raw_payload.get("message", ""),
            "occurred_at": raw_payload.get("clock", timezone.now()),
            "target_type": "host",
            "target_identifier": raw_payload.get("host", ""),
            "hostname": raw_payload.get("host", ""),
            "metadata": {},
        }]

    def _map_zabbix_severity(self, severity):
        mapping = {
            "0": "info",
            "1": "warning",
            "2": "minor",
            "3": "major",
            "4": "critical",
            "5": "critical",
        }
        return mapping.get(str(severity), "warning")
