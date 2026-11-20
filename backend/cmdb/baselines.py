"""Baseline lifecycle: snapshot creation, approval workflow, comparison and
drift evaluation.

Snapshots are deterministic (sorted JSON, SHA-256 checksum) and bounded.
Drift findings use deterministic fingerprints so evaluations are idempotent.
Sensitive field values are masked inside findings.
"""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from common.models import Notification
from common.audit import log_action

from .models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
)

SNAPSHOT_CI_FIELDS = (
    "name", "status", "lifecycle_state", "criticality", "environment",
    "version", "manufacturer", "model", "hostname", "ip_address",
    "dns_name", "location", "monitoring_state", "data_classification",
    "validated_system_impact", "contains_personal_data", "ci_type_id",
    "department_id", "owner_id", "technical_owner_id", "support_group_id",
    "vendor_id", "service_catalogue_item_id",
)

# Field -> drift finding type mapping (explicit, never inferred).
FIELD_FINDING_TYPES = {
    "status": "status_changed",
    "owner_id": "owner_changed",
    "technical_owner_id": "owner_changed",
    "version": "software_version_changed",
    "lifecycle_state": "status_changed",
}

SENSITIVE_DIFF_FIELDS = {"ip_address", "serial_number"}

FIELD_SEVERITY = {
    "status_changed": "high",
    "owner_changed": "medium",
    "software_version_changed": "medium",
    "relationship_added": "medium",
    "relationship_removed": "medium",
    "relationship_changed": "medium",
    "missing_required_attribute": "high",
    "unexpected_attribute": "low",
    "field_changed": "medium",
}

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]

MAX_BASELINE_CIS = 200
MAX_SNAPSHOT_JSON_BYTES = 512_000


def mask_value(field, value):
    """Mask sensitive values inside drift findings."""
    if value in (None, ""):
        return ""
    if field in SENSITIVE_DIFF_FIELDS:
        return "[masked]"
    return str(value)


def _ci_snapshot_entry(ci):
    entry = {}
    for field in SNAPSHOT_CI_FIELDS:
        entry[field] = getattr(ci, field)
    entry["attributes"] = dict(ci.attributes or {})
    rels = []
    for rel in ConfigurationItemRelationship.objects.filter(
        source_ci=ci, status="active", is_deleted=False,
    ).select_related("target_ci"):
        rels.append({
            "target": rel.target_ci.ci_number,
            "type": rel.relationship_type,
            "status": rel.status,
        })
    rels.sort(key=lambda r: (r["type"], r["target"]))
    entry["relationships"] = rels
    return entry


def build_snapshot(cis):
    """Deterministic, bounded snapshot for a CI collection."""
    cis = list(cis)
    if len(cis) > MAX_BASELINE_CIS:
        raise ValueError(f"baseline scope exceeds {MAX_BASELINE_CIS} CIs")
    snapshot = {
        "format_version": 1,
        "generated_at": timezone.now().isoformat(),
        "cis": {ci.ci_number: _ci_snapshot_entry(ci) for ci in cis},
    }
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    if len(raw.encode("utf-8")) > MAX_SNAPSHOT_JSON_BYTES:
        raise ValueError("baseline snapshot exceeds size limit")
    checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return snapshot, checksum


def create_baseline(*, name, scope_type="single_ci", cis, actor=None,
                    service=None, description="", effective_from=None,
                    effective_to=None, status="draft"):
    """Create a draft/pending baseline with a deterministic snapshot."""
    cis = list(cis)
    if not cis:
        raise ValueError("baseline requires at least one configuration item")
    with transaction.atomic():
        baseline = ConfigurationBaseline.objects.create(
            name=name,
            scope_type=scope_type,
            service=service,
            description=description,
            effective_from=effective_from,
            effective_to=effective_to,
            status=status if status in ("draft", "pending_approval") else "draft",
            created_by=actor,
        )
        baseline.configuration_items.set(cis)
        snapshot, checksum = build_snapshot(cis)
        baseline.snapshot = snapshot
        baseline.checksum = checksum
        baseline.save(update_fields=["snapshot", "checksum", "updated_at"])
        for ci in cis:
            ConfigurationItemHistory.objects.create(
                configuration_item=ci,
                actor=actor,
                event_type="baseline_created",
                detail=f"Baseline {baseline.code} created",
                source="manual",
            )
    return baseline


def refresh_snapshot(baseline):
    """Rebuild the snapshot for a draft baseline from its current CIs."""
    if baseline.status != "draft":
        raise ValueError("only draft baselines can be re-snapshotted")
    cis = list(baseline.configuration_items.all().order_by("ci_number"))
    if not cis:
        raise ValueError("baseline has no configuration items")
    snapshot, checksum = build_snapshot(cis)
    baseline.snapshot = snapshot
    baseline.checksum = checksum
    baseline.save(update_fields=["snapshot", "checksum", "updated_at"])
    return baseline


def submit_baseline(baseline, actor):
    """Move a draft baseline into pending_approval."""
    if baseline.status != "draft":
        raise ValueError("only draft baselines can be submitted")
    baseline.status = "pending_approval"
    baseline.save(update_fields=["status", "updated_at"])
    log_action(
        actor=actor, action="status_change", instance=baseline,
        reason="baseline submitted for approval",
        details={"from": "draft", "to": "pending_approval"},
    )
    return baseline


def approve_baseline(baseline, actor):
    """Approve a baseline (manager/admin, never the creator).

    Approving supersedes any other approved baseline with the same name and
    assigns the next version number.
    """
    with transaction.atomic():
        locked = (
            ConfigurationBaseline.objects
            .select_for_update(of=("self",))
            .select_related("created_by")
            .get(pk=baseline.pk)
        )
        if locked.status not in ("draft", "pending_approval"):
            raise ValueError(f"cannot approve baseline in status {locked.status!r}")
        if locked.created_by_id and locked.created_by_id == actor.id:
            raise PermissionError("Cannot approve own baseline.")

        prior_version = (
            ConfigurationBaseline.all_objects
            .filter(name=locked.name, status="superseded")
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        ) or 0

        superseded = list(
            ConfigurationBaseline.objects.filter(
                name=locked.name, status="approved",
            ).exclude(pk=locked.pk)
        )
        for other in superseded:
            other.status = "superseded"
            other.save(update_fields=["status", "updated_at"])

        locked.status = "approved"
        locked.approved_by = actor
        locked.approved_at = timezone.now()
        locked.version = max(prior_version, locked.version - 1) + 1
        locked.save(update_fields=[
            "status", "approved_by", "approved_at", "version", "updated_at",
        ])
        log_action(
            actor=actor, action="status_change", instance=locked,
            reason="baseline approved",
            details={
                "from": "pending_approval" if superseded else "draft",
                "to": "approved",
                "superseded_ids": [b.id for b in superseded],
            },
        )
        for ci in locked.configuration_items.all():
            ConfigurationItemHistory.objects.create(
                configuration_item=ci,
                actor=actor,
                event_type="baseline_approved",
                detail=f"Baseline {locked.code} v{locked.version} approved",
                source="manual",
            )
    baseline.refresh_from_db()
    return baseline


def supersede_baseline(baseline, actor):
    """Manually supersede an approved baseline."""
    if baseline.status != "approved":
        raise ValueError("only approved baselines can be superseded")
    baseline.status = "superseded"
    baseline.save(update_fields=["status", "updated_at"])
    log_action(
        actor=actor, action="status_change", instance=baseline,
        reason="baseline superseded", details={"to": "superseded"},
    )
    return baseline


def _finding_type_for_field(field):
    if field in FIELD_FINDING_TYPES:
        return FIELD_FINDING_TYPES[field]
    return "field_changed"


def _bump_severity(base_severity, ci):
    severity = base_severity
    if ci.criticality == "critical":
        idx = SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else 0
        severity = SEVERITY_ORDER[min(idx + 1, len(SEVERITY_ORDER) - 1)]
    elif ci.criticality == "high" and severity in ("info", "low"):
        severity = "medium"
    return severity


def compare_ci_to_baseline(ci, baseline):
    """Return masked diffs between a CI and a baseline snapshot entry."""
    entry = (baseline.snapshot or {}).get("cis", {}).get(ci.ci_number)
    if entry is None:
        return [{
            "finding_type": "field_changed",
            "field": "__presence__",
            "expected": "present in baseline",
            "actual": "missing from baseline",
            "severity": "medium",
        }]
    diffs = []
    for field in SNAPSHOT_CI_FIELDS:
        if field not in entry:
            continue
        expected = entry[field]
        actual = getattr(ci, field)
        if expected != actual:
            diffs.append({
                "finding_type": _finding_type_for_field(field),
                "field": field,
                "expected": mask_value(field, expected),
                "actual": mask_value(field, actual),
                "severity": FIELD_SEVERITY.get(_finding_type_for_field(field), "medium"),
            })

    snap_attrs = entry.get("attributes", {}) or {}
    live_attrs = dict(ci.attributes or {})
    ci_type = ci.ci_type
    required = set((ci_type.required_attributes or []) if ci_type else [])
    schema_keys = set((ci_type.schema or {}).keys()) if ci_type else set()

    for key in sorted(set(snap_attrs) | set(live_attrs)):
        in_snap = key in snap_attrs
        in_live = key in live_attrs
        if in_snap and not in_live:
            diffs.append({
                "finding_type": "missing_required_attribute"
                if key in required else "field_changed",
                "field": f"attributes.{key}",
                "expected": mask_value(key, snap_attrs[key]),
                "actual": "",
                "severity": "high" if key in required else "low",
            })
        elif in_live and not in_snap:
            diffs.append({
                "finding_type": "unexpected_attribute"
                if schema_keys and key not in schema_keys else "field_changed",
                "field": f"attributes.{key}",
                "expected": "",
                "actual": mask_value(key, live_attrs[key]),
                "severity": "low",
            })
        elif snap_attrs[key] != live_attrs[key]:
            diffs.append({
                "finding_type": "field_changed",
                "field": f"attributes.{key}",
                "expected": mask_value(key, snap_attrs[key]),
                "actual": mask_value(key, live_attrs[key]),
                "severity": "low",
            })

    snap_rels = {
        (r["type"], r["target"]) for r in entry.get("relationships", []) or []
    }
    live_rels = set()
    prefetched_rels = getattr(ci, "active_outgoing_relationships", None)
    if prefetched_rels is not None:
        rel_iter = prefetched_rels
    else:
        rel_iter = ConfigurationItemRelationship.objects.filter(
            source_ci=ci, status="active", is_deleted=False,
        ).select_related("target_ci")
    for rel in rel_iter:
        live_rels.add((rel.relationship_type, rel.target_ci.ci_number))
    for rel_type, target in sorted(snap_rels - live_rels):
        diffs.append({
            "finding_type": "relationship_removed",
            "field": "relationships",
            "expected": f"{rel_type} -> {target}",
            "actual": "",
            "severity": "medium",
        })
    for rel_type, target in sorted(live_rels - snap_rels):
        diffs.append({
            "finding_type": "relationship_added",
            "field": "relationships",
            "expected": "",
            "actual": f"{rel_type} -> {target}",
            "severity": "medium",
        })

    for diff in diffs:
        diff["severity"] = _bump_severity(diff["severity"], ci)
    return diffs


def compare_service_to_baseline(service, baseline):
    """Compare every CI of a service (via service links) to the baseline."""
    from .models import ServiceConfigurationItemLink

    results = []
    linked_ids = set(
        ServiceConfigurationItemLink.objects.filter(
            service=service, is_deleted=False,
        ).values_list("configuration_item_id", flat=True)
    )
    cis = ConfigurationItem.objects.filter(
        id__in=linked_ids,
    ).select_related("ci_type")
    for ci in cis.order_by("ci_number"):
        for diff in compare_ci_to_baseline(ci, baseline):
            diff = dict(diff)
            diff["ci_id"] = ci.id
            diff["ci_number"] = ci.ci_number
            results.append(diff)
    return results


def _fingerprint(ci, baseline, finding_type, field):
    raw = f"{ci.ci_number}|{baseline.code}|{finding_type}|{field}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _notify_owner(ci, finding):
    recipients = []
    for user in (ci.owner, ci.technical_owner):
        if user and user.is_active and user not in recipients:
            recipients.append(user)
    now = timezone.now()
    cutoff = now - timezone.timedelta(days=7)
    for recipient in recipients:
        already = Notification.objects.filter(
            recipient=recipient,
            entity_type="cmdb.ConfigurationDriftFinding",
            object_id=str(finding.pk),
            created_at__gte=cutoff,
        ).exists()
        if not already:
            Notification.objects.create(
                recipient=recipient,
                title=f"CMDB drift ({finding.severity}): {ci.ci_number}",
                body=(
                    f"Drift finding '{finding.finding_type}' on {ci.ci_number} "
                    f"({ci.name}) field '{finding.field_name or 'n/a'}'."
                ),
                entity_type="cmdb.ConfigurationDriftFinding",
                object_id=str(finding.pk),
            )


def evaluate_configuration_drift(ci=None, baseline=None, actor=None,
                                resolve_stale=True, notify=True):
    """Evaluate a CI against its approved baseline; idempotent per fingerprint.

    Findings that are no longer detected are resolved automatically when
    `resolve_stale` is set (used by the drift task/management command).
    """
    if ci is None and baseline is None:
        raise ValueError("ci or baseline required")

    if baseline is None:
        baseline = (
            ConfigurationBaseline.objects.filter(
                configuration_items=ci, status="approved", is_deleted=False,
            )
            .order_by("-approved_at")
            .first()
        )
    if baseline is None:
        return []

    targets = []
    if ci is not None:
        targets = [ci]
    else:
        targets = list(
            baseline.configuration_items.filter(
                is_deleted=False,
            ).select_related("ci_type")
        )

    produced_fingerprints = set()
    findings = []
    for target in targets:
        if baseline.snapshot is None or "cis" not in (baseline.snapshot or {}):
            continue
        if target.ci_number not in (baseline.snapshot or {}).get("cis", {}):
            # CI not part of this baseline's snapshot: nothing to compare
            continue
        diffs = compare_ci_to_baseline(target, baseline)
        for diff in diffs:
            fingerprint = _fingerprint(
                target, baseline, diff["finding_type"], diff["field"],
            )
            produced_fingerprints.add(fingerprint)
            with transaction.atomic():
                existing = (
                    ConfigurationDriftFinding.objects
                    .select_for_update()
                    .filter(fingerprint=fingerprint, is_deleted=False)
                    .first()
                )
                if existing is None:
                    finding = ConfigurationDriftFinding.objects.create(
                        configuration_item=target,
                        baseline=baseline,
                        finding_type=diff["finding_type"],
                        severity=diff["severity"],
                        status="open",
                        field_name=diff["field"],
                        expected_value=diff["expected"],
                        actual_value=diff["actual"],
                        fingerprint=fingerprint,
                        source="drift_evaluation",
                    )
                    if notify and finding.severity in ("high", "critical"):
                        _notify_owner(target, finding)
                    findings.append(finding)
                else:
                    changed = (
                        existing.actual_value != diff["actual"]
                        or existing.expected_value != diff["expected"]
                    )
                    if existing.status == "resolved" and changed:
                        existing.status = "open"
                        existing.resolved_at = None
                        existing.resolved_by = None
                        existing.resolution_note = ""
                        existing.expected_value = diff["expected"]
                        existing.actual_value = diff["actual"]
                        existing.detected_at = timezone.now()
                        existing.save(update_fields=[
                            "status", "resolved_at", "resolved_by",
                            "resolution_note", "expected_value",
                            "actual_value", "detected_at", "updated_at",
                        ])
                        if notify and existing.severity in ("high", "critical"):
                            _notify_owner(target, existing)
                    findings.append(existing)

    if resolve_stale:
        # anything open for this scope but not produced this round is stale
        scope_qs = ConfigurationDriftFinding.objects.filter(
            baseline=baseline, is_deleted=False,
            status__in=("open", "acknowledged"),
        )
        if ci is not None:
            scope_qs = scope_qs.filter(configuration_item=ci)
        stale = [
            f for f in scope_qs
            if f.fingerprint not in produced_fingerprints
        ]
        now = timezone.now()
        for finding in stale:
            finding.status = "resolved"
            finding.resolved_at = now
            finding.resolved_by = actor
            finding.resolution_note = "Auto-resolved: no longer detected"
            finding.save(update_fields=[
                "status", "resolved_at", "resolved_by", "resolution_note",
                "updated_at",
            ])

    return findings


def acknowledge_finding(finding, actor):
    if finding.status != "open":
        raise ValueError("only open findings can be acknowledged")
    finding.status = "acknowledged"
    finding.acknowledged_by = actor
    finding.acknowledged_at = timezone.now()
    finding.save(update_fields=[
        "status", "acknowledged_by", "acknowledged_at", "updated_at",
    ])
    ConfigurationItemHistory.objects.create(
        configuration_item=finding.configuration_item,
        actor=actor,
        event_type="drift_acknowledged",
        detail=f"{finding.finding_type} / {finding.field_name}",
        source="manual",
    )
    return finding


def resolve_finding(finding, actor, note):
    if not note or not str(note).strip():
        raise ValueError("resolution_note is required")
    finding.status = "resolved"
    finding.resolved_by = actor
    finding.resolved_at = timezone.now()
    finding.resolution_note = str(note).strip()
    finding.save(update_fields=[
        "status", "resolved_by", "resolved_at", "resolution_note",
        "updated_at",
    ])
    ConfigurationItemHistory.objects.create(
        configuration_item=finding.configuration_item,
        actor=actor,
        event_type="drift_resolved",
        detail=finding.resolution_note[:500],
        source="manual",
    )
    return finding


def accept_finding(finding, actor):
    finding.status = "accepted"
    finding.resolved_by = actor
    finding.resolved_at = timezone.now()
    finding.resolution_note = finding.resolution_note or "Accepted as expected"
    finding.save(update_fields=[
        "status", "resolved_by", "resolved_at", "resolution_note",
        "updated_at",
    ])
    log_action(
        actor=actor, action="status_change", instance=finding,
        reason="drift finding accepted",
        details={"severity": finding.severity, "to": "accepted"},
    )
    ConfigurationItemHistory.objects.create(
        configuration_item=finding.configuration_item,
        actor=actor,
        event_type="drift_accepted",
        detail=f"{finding.finding_type} / {finding.field_name}",
        source="manual",
    )
    return finding


def mark_false_positive(finding, actor, note):
    if not note or not str(note).strip():
        raise ValueError("a note is required to mark a false positive")
    finding.status = "false_positive"
    finding.resolved_by = actor
    finding.resolved_at = timezone.now()
    finding.resolution_note = str(note).strip()
    finding.save(update_fields=[
        "status", "resolved_by", "resolved_at", "resolution_note",
        "updated_at",
    ])
    ConfigurationItemHistory.objects.create(
        configuration_item=finding.configuration_item,
        actor=actor,
        event_type="drift_false_positive",
        detail=finding.resolution_note[:500],
        source="manual",
    )
    return finding
