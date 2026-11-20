"""Deterministic change conflict detection engine.

Detects scheduling conflicts between approved/scheduled changes based on:

- same Asset (ChangeAssetImpact)
- same affected service (ChangeServiceImpact)
- same department
- same implementation lead
- same high-risk dependency (ChangeDependency dependency_type='conflicts_with')
- maintenance-window parallel limit (MaintenanceWindow.maximum_parallel_changes)
- blackout windows (MaintenanceWindow.blackout=True)
- overlapping high or critical risk changes
- dependent change scheduled before predecessor completion

Conflicts are identified by a deterministic fingerprint so repeated detection
updates the same conflict row and no duplicate open conflict is created.
"""
import hashlib
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from changes.models import (
    ChangeRequest,
    ChangeConflict,
    ChangeAssetImpact,
    ChangeServiceImpact,
    ChangeDependency,
    MaintenanceWindow,
    BlackoutPeriod,
    ChangeSchedulingException,
)


def _conflict_fingerprint(change, conflicting_change, conflict_type):
    """Deterministic fingerprint for a conflict pair."""
    ids = sorted([str(change.pk), str(conflicting_change.pk)])
    raw = f"{ids[0]}|{ids[1]}|{conflict_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _overlaps(a_start, a_end, b_start, b_end):
    """True if two time ranges overlap (inclusive)."""
    if not a_start or not a_end or not b_start or not b_end:
        return False
    return a_start <= b_end and b_start <= a_end


def _within_window(change, window_start, window_end):
    """True if a change's planned window overlaps [window_start, window_end]."""
    cs = change.planned_start
    ce = change.planned_end
    if not cs or not ce:
        return False
    return cs <= window_end and window_start <= ce


def detect_conflicts(change, horizon_days=90):
    """Detect conflicts for a single change.

    Returns a list of dicts with keys: change, conflicting_change,
    conflict_type, severity, fingerprint.
    """
    now = timezone.now()
    horizon_end = now + timedelta(days=horizon_days)

    conflicts = []

    # Skip terminal changes - they don't generate new conflicts.
    terminal = {
        "closed", "rejected", "cancelled", "failed", "rolled_back",
    }
    if change.status in terminal:
        return conflicts

    cs = change.planned_start
    ce = change.planned_end

    # --- Blackout period conflict ---
    # A change scheduled during a blackout period is a conflict
    from datetime import timedelta
    horizon_end = timezone.now() + timedelta(days=90)
    blackout_periods = BlackoutPeriod.objects.filter(
        status="active", end_at__gte=timezone.now()
    )
    for bp in blackout_periods:
        # Check scope - if blackout has department/service scope, check matching
        scope_match = True
        if bp.scope_department and change.department_id != bp.scope_department_id:
            scope_match = False
        if bp.scope_service and change.service_id != bp.scope_service_id:
            scope_match = False
        if not scope_match:
            continue
        # Check overlap with change window
        if change.planned_start and change.planned_end:
            if _overlaps(change.planned_start, change.planned_end, bp.start_at, bp.end_at):
                # Check if there's already an approved exception
                has_exception = ChangeSchedulingException.objects.filter(
                    change=change,
                    blackout_period=bp,
                    status="approved",
                ).exists()
                if not has_exception:
                    conflicts.append({
                        "change": change,
                        "conflicting_change": None,
                        "conflict_type": "blackout_period",
                        "severity": "high",
                        "detail": f"Change scheduled during blackout period: {bp.name}",
                    })

    # --- Same Asset overlap ---
    asset_impacts = ChangeAssetImpact.objects.filter(change=change)
    asset_ids = list(asset_impacts.values_list("asset_id", flat=True))
    if asset_ids:
        other_impacts = ChangeAssetImpact.objects.filter(
            asset_id__in=asset_ids
        ).exclude(change=change)
        for imp in other_impacts.select_related("change"):
            other = imp.change
            if other.status in terminal:
                continue
            if not _within_window(other, cs, ce):
                continue
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "asset_overlap",
                "severity": _severity_for(change, other, "high"),
                "fingerprint": _conflict_fingerprint(change, other, "asset_overlap"),
            })

    # --- Same affected service overlap ---
    service_impacts = ChangeServiceImpact.objects.filter(change=change)
    service_ids = list(service_impacts.values_list("service_catalogue_item_id", flat=True))
    if service_ids:
        other_service_impacts = ChangeServiceImpact.objects.filter(
            service_catalogue_item_id__in=service_ids
        ).exclude(change=change)
        for imp in other_service_impacts.select_related("change"):
            other = imp.change
            if other.status in terminal:
                continue
            if not _within_window(other, cs, ce):
                continue
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "service_overlap",
                "severity": _severity_for(change, other, "high"),
                "fingerprint": _conflict_fingerprint(change, other, "service_overlap"),
            })

    # --- Same department overlap ---
    if change.department_id:
        other_changes = ChangeRequest.objects.filter(
            department_id=change.department_id
        ).exclude(pk=change.pk)
        for other in other_changes:
            if other.status in terminal:
                continue
            if not _within_window(other, cs, ce):
                continue
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "department_overlap",
                "severity": _severity_for(change, other, "medium"),
                "fingerprint": _conflict_fingerprint(change, other, "department_overlap"),
            })

    # --- Same implementation lead overlap ---
    if change.implementation_lead_id:
        other_changes = ChangeRequest.objects.filter(
            implementation_lead_id=change.implementation_lead_id
        ).exclude(pk=change.pk)
        for other in other_changes:
            if other.status in terminal:
                continue
            if not _within_window(other, cs, ce):
                continue
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "implementer_overlap",
                "severity": _severity_for(change, other, "medium"),
                "fingerprint": _conflict_fingerprint(change, other, "implementer_overlap"),
            })

    # --- Dependency order: successor scheduled before predecessor complete ---
    as_predecessor = ChangeDependency.objects.filter(predecessor=change)
    for dep in as_predecessor.select_related("successor"):
        other = dep.successor
        if other.status in terminal:
            continue
        if dep.dependency_type in ("blocks", "requires"):
            # Successor must start after predecessor completes.
            if ce and other.planned_start and other.planned_start < ce:
                conflicts.append({
                    "change": change,
                    "conflicting_change": other,
                    "conflict_type": "dependency_order",
                    "severity": "critical",
                    "fingerprint": _conflict_fingerprint(change, other, "dependency_order"),
                })

    # As successor: predecessor not complete before this starts.
    as_successor = ChangeDependency.objects.filter(successor=change)
    for dep in as_successor.select_related("predecessor"):
        other = dep.predecessor
        if other.status in terminal:
            continue
        if dep.dependency_type in ("blocks", "requires"):
            if ce and other.planned_end and other.planned_end > cs:
                conflicts.append({
                    "change": change,
                    "conflicting_change": other,
                    "conflict_type": "dependency_order",
                    "severity": "critical",
                    "fingerprint": _conflict_fingerprint(change, other, "dependency_order"),
                })

    # --- Manual conflicts already recorded ---
    manual_conflicts = ChangeConflict.objects.filter(
        change=change, conflict_type="manual"
    ).exclude(status="resolved")
    for mc in manual_conflicts.select_related("conflicting_change"):
        conflicts.append({
            "change": change,
            "conflicting_change": mc.conflicting_change,
            "conflict_type": "manual",
            "severity": mc.severity,
            "fingerprint": mc.fingerprint or _conflict_fingerprint(change, mc.conflicting_change, "manual"),
        })

    # --- Maintenance window parallel limit / blackout ---
    # Find windows overlapping this change's planned time.
    windows = MaintenanceWindow.objects.filter(
        status="active",
        start_at__lte=ce if ce else timezone.now(),
        end_at__gte=cs if cs else timezone.now(),
    )
    for window in windows:
        if window.blackout:
            conflicts.append({
                "change": change,
                "conflicting_change": None,
                "conflict_type": "blackout_window",
                "severity": "critical",
                "fingerprint": _conflict_fingerprint(
                    change, None, f"blackout_{window.code}"
                ),
            })
            continue
        # Count concurrent changes in this window.
        concurrent = ChangeRequest.objects.filter(
            status__in=["scheduled", "in_progress"],
            planned_start__lte=window.end_at,
            planned_end__gte=window.start_at,
        ).exclude(pk=change.pk)
        if concurrent.count() >= window.maximum_parallel_changes:
            conflicts.append({
                "change": change,
                "conflicting_change": None,
                "conflict_type": "window_capacity",
                "severity": "high",
                "fingerprint": _conflict_fingerprint(
                    change, None, f"capacity_{window.code}"
                ),
            })

    # --- High risk overlap: two high/critical changes overlapping in time ---
    if change.risk_level in ("high", "critical"):
        other_high = ChangeRequest.objects.filter(
            risk_level__in=["high", "critical"],
            status__in=["scheduled", "in_progress"],
        ).exclude(pk=change.pk)
        for other in other_high:
            if not _within_window(other, cs, ce):
                continue
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "high_risk_overlap",
                "severity": "high",
                "fingerprint": _conflict_fingerprint(change, other, "high_risk_overlap"),
            })

    # --- Schedule time overlap: direct time window conflicts ---
    # Identify changes with overlapping planned start/end times.
    # This is informational unless other factors make it critical.
    overlapping = ChangeRequest.objects.filter(
        status__in=["scheduled", "in_progress", "approved"],
        planned_start__isnull=False,
        planned_end__isnull=False,
    ).exclude(pk=change.pk)
    for other in overlapping:
        if not _overlaps(cs, ce, other.planned_start, other.planned_end):
            continue
        
        # Check if this is already covered by asset/service/department overlap
        # to avoid duplicate informational conflicts
        existing_types = {c["conflict_type"] for c in conflicts}
        if "asset_overlap" in existing_types or "service_overlap" in existing_types:
            # Already have a more specific conflict for this overlap
            continue
        
        # Determine if changes share any CIs or services via impact tables
        other_asset_ids = set(
            ChangeAssetImpact.objects.filter(change=other).values_list(
                "asset_id", flat=True
            )
        )
        this_asset_ids = set(asset_ids)
        shared_assets = this_asset_ids & other_asset_ids
        
        other_service_ids = set(
            ChangeServiceImpact.objects.filter(change=other).values_list(
                "service_catalogue_item_id", flat=True
            )
        )
        this_service_ids = set(service_ids)
        shared_services = this_service_ids & other_service_ids
        
        if shared_assets or shared_services:
            # Shared CI/service - more significant conflict
            conflict_type = "asset_overlap" if shared_assets else "service_overlap"
            severity = _severity_for(change, other, "high" if shared_assets else "medium")
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": conflict_type,
                "severity": severity,
                "fingerprint": _conflict_fingerprint(change, other, conflict_type),
            })
        elif change.department_id and other.department_id == change.department_id:
            # Same department - already covered by department_overlap above
            continue
        else:
            # No shared CIs/services - purely time-based overlap, informational
            conflicts.append({
                "change": change,
                "conflicting_change": other,
                "conflict_type": "schedule_overlap",
                "severity": "info",
                "fingerprint": _conflict_fingerprint(change, other, "schedule_overlap"),
            })

    return conflicts


def detect_schedule_conflicts(change, horizon_days=90):
    """Detect schedule conflicts focusing on time-based overlaps.

    Returns a list of dicts suitable for display in schedule views.
    This is a lighter-weight alternative to full conflict detection,
    focused on identifying what else is scheduled in the same time window.
    """
    now = timezone.now()
    horizon_end = now + timedelta(days=horizon_days)

    conflicts = []

    # Only for scheduled or in_progress changes with planned times
    if change.status not in ("scheduled", "in_progress"):
        return conflicts

    cs = change.planned_start
    ce = change.planned_end
    if not cs or not ce:
        return conflicts

    # Find all changes scheduled in the same time window
    overlapping = ChangeRequest.objects.filter(
        status__in=["scheduled", "in_progress"],
        planned_start__isnull=False,
        planned_end__isnull=False,
        planned_start__lte=ce,
        planned_end__gte=cs,
    ).exclude(pk=change.pk).select_related(
        "change_owner", "department", "implementation_lead"
    )

    for other in overlapping:
        # Determine overlap details
        overlap_start = max(cs, other.planned_start)
        overlap_end = min(ce, other.planned_end)
        overlap_minutes = (overlap_end - overlap_start).total_seconds() / 60

        # Check for shared CIs/services
        this_assets = set(
            ChangeAssetImpact.objects.filter(change=change).values_list(
                "asset_id", flat=True
            )
        )
        other_assets = set(
            ChangeAssetImpact.objects.filter(change=other).values_list(
                "asset_id", flat=True
            )
        )
        shared_assets = this_assets & other_assets

        this_services = set(
            ChangeServiceImpact.objects.filter(change=change).values_list(
                "service_catalogue_item_id", flat=True
            )
        )
        other_services = set(
            ChangeServiceImpact.objects.filter(change=other).values_list(
                "service_catalogue_item_id", flat=True
            )
        )
        shared_services = this_services & other_services

        # Determine conflict severity and type.
        # Different departments with no shared assets/services are not conflicts.
        # Same department or no department on either change = potential conflict.
        if shared_assets:
            conflict_type = "asset_overlap"
            severity = "high"
        elif shared_services:
            conflict_type = "service_overlap"
            severity = "medium"
        elif change.department_id and other.department_id and change.department_id != other.department_id:
            # Different departments, no shared assets/services - skip.
            continue
        elif change.department_id and other.department_id == change.department_id:
            conflict_type = "department_overlap"
            severity = "low"
        else:
            conflict_type = "schedule_overlap"
            severity = "info"

        conflicts.append({
            "change": change,
            "conflicting_change": other,
            "conflict_type": conflict_type,
            "severity": severity,
            "overlap_start": overlap_start,
            "overlap_end": overlap_end,
            "overlap_minutes": overlap_minutes,
            "shared_assets": list(shared_assets),
            "shared_services": list(shared_services),
        })

    return conflicts


def _severity_for(change, other, default):
    """Determine severity from both changes' risk levels."""
    levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    c1 = levels.get(change.risk_level or "low", 1)
    c2 = levels.get(other.risk_level or "low", 1)
    score = max(c1, c2)
    if score >= 3:
        return "high"
    if score == 2:
        return "medium"
    return default


def upsert_conflicts(change, conflicts):
    """Persist detected conflicts, deduplicating by fingerprint.

    Existing open conflicts with the same fingerprint are updated in place;
    new ones are created. Resolved/accepted conflicts are left alone unless
    re-detected.
    """
    created = []
    updated = []
    existing_fingerprints = set(
        ChangeConflict.objects.filter(change=change).values_list(
            "fingerprint", flat=True
        )
    )

    for conflict in conflicts:
        fingerprint = conflict.get("fingerprint")
        if not fingerprint:
            continue
        matching = ChangeConflict.objects.filter(
            change=change, fingerprint=fingerprint
        ).first()
        if matching:
            matching.conflicting_change = conflict.get(
                "conflicting_change"
            ) or matching.conflicting_change
            matching.conflict_type = conflict.get(
                "conflict_type", matching.conflict_type
            )
            matching.severity = conflict.get(
                "severity", matching.severity
            )
            matching.status = "open"
            matching.save()
            updated.append(matching)
        else:
            ChangeConflict.objects.create(
                change=change,
                conflicting_change=conflict.get("conflicting_change"),
                conflict_type=conflict.get("conflict_type"),
                severity=conflict.get("severity", "medium"),
                fingerprint=fingerprint,
            )
            created.append(fingerprint)

    return created, updated


def resolve_conflicts_for_change(change, user, resolution="resolved"):
    """Mark all open conflicts for a change as resolved (deterministic)."""
    updated = ChangeConflict.objects.filter(
        change=change, status="open"
    ).update(
        status=resolution,
        resolution="Resolved by schedule change",
        resolved_by=user,
    )
    return updated
