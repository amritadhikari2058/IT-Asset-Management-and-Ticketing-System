"""Domain Services for Software Licensing, Renewals, Allocations, and Compliance.

Implements all core business operations:
- Concurrency-safe agreement and allocation numbering.
- Agreement lifecycle transitions (activate, renew, suspend, resume, terminate, retire, recalculate).
- License allocations and bulk operations with race condition and over-allocation protection.
- Software installation recording, compliance verification, and removal.
- Threshold-aware renewal workflows with separation of duties (requester cannot self-approve).
- Deterministic compliance engine with idempotent finding fingerprinting.
- Integrations: Service Requests, Employee Offboarding reclamation, and Approval Center provider.
"""

from decimal import Decimal
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseHistory,
    LicenseRenewal,
    SoftwareInstallation,
    SoftwareProduct,
)
from licensing.permissions import is_system_admin, is_it_manager


# ==============================================================================
# NUMBERING & REFERENCES
# ==============================================================================



CONSUMING_ALLOCATION_STATUSES = [
    "assigned",
    "active",
    "reserved",
]

ACTIVE_ALLOCATED_STATUSES = [
    "assigned",
    "active",
]


def reconcile_agreement_entitlements(agreement: LicenseAgreement) -> Dict[str, Any]:
    """Reconcile one agreement's entitlement against its allocation records.

    Consuming statuses are ``assigned``, ``active``, and ``reserved``.
    ``suspended``, ``revoked``, and ``expired`` allocations do not consume
    entitlement and are reported separately for audit purposes.

    Unlimited / non-seat-based agreements return ``None`` for the purchased,
    available, and utilization values so callers cannot present a misleading
    percentage.
    """
    counts = agreement.allocations.aggregate(
        active_allocated=Count("pk", filter=Q(status__in=ACTIVE_ALLOCATED_STATUSES)),
        reserved=Count("pk", filter=Q(status="reserved")),
        suspended=Count("pk", filter=Q(status="suspended")),
        released=Count("pk", filter=Q(status__in=("revoked", "released"))),
        expired=Count("pk", filter=Q(status="expired")),
    )

    active_allocated = counts["active_allocated"] or 0
    reserved = counts["reserved"] or 0
    consuming = active_allocated + reserved
    suspended = counts["suspended"] or 0
    released = counts["released"] or 0
    expired = counts["expired"] or 0

    limit = get_agreement_entitlement_limit(agreement)
    is_unlimited = agreement.is_unlimited or limit is None
    calculable = bool(not is_unlimited and limit and limit > 0)

    if is_unlimited:
        available = None
        overallocated = 0
        utilization = None
        utilization_note = (
            "Unlimited or non-seat-based entitlement; utilization is not calculated."
        )
    else:
        available = max(0, limit - consuming)
        overallocated = max(0, consuming - limit)
        utilization = round((consuming / limit) * 100, 2) if calculable else None
        utilization_note = (
            ""
            if calculable
            else "Entitlement quantity is missing or zero; utilization cannot be calculated."
        )

    return {
        "agreement_id": agreement.pk,
        "agreement_number": agreement.agreement_number,
        "product_name": agreement.software_product.name,
        "vendor": agreement.vendor.name if agreement.vendor else None,
        "license_model": agreement.license_model,
        "status": agreement.status,
        "expiry_date": str(agreement.expiry_date) if agreement.expiry_date else None,
        "is_unlimited": is_unlimited,
        "purchased_entitlement_quantity": None if is_unlimited else limit,
        "active_allocated_quantity": active_allocated,
        "reserved_quantity": reserved,
        "consuming_quantity": consuming,
        "available_quantity": available,
        "overallocated_quantity": overallocated,
        "suspended_allocation_quantity": suspended,
        "released_allocation_quantity": released,
        "expired_allocation_quantity": expired,
        "utilization_percent": utilization,
        "utilization_calculable": calculable,
        "utilization_note": utilization_note,
        "open_findings": agreement.compliance_findings.filter(
            status__in=("open", "acknowledged")
        ).count(),
    }



def get_agreement_entitlement_limit(agreement: LicenseAgreement) -> Optional[int]:
    """Retrieve the entitlement limit for an agreement.

    Returns the quantity_purchased for non-concurrent models,
    or concurrent_limit for concurrent models. Returns None if the agreement
    is unlimited.
    """
    if agreement.is_unlimited:
        return None
    if agreement.license_model == "concurrent":
        return agreement.concurrent_limit
    return agreement.quantity_purchased


def reconcile_entitlements_summary(agrs) -> Dict[str, Any]:
    """Aggregate entitlement metrics across a queryset of LicenseAgreement.

    Uses the same per-agreement calculation as
    :func:`reconcile_agreement_entitlements` so the summary cannot drift from
    the detail rows. Unlimited / non-seat-based agreements are excluded from
    the calculable totals, matching the utilization report.
    """
    total_entitlement = 0
    total_usage = 0
    total_available = 0
    overallocated_agreements = 0
    overallocated_quantity = 0
    agreement_count = 0

    for agr in agrs:
        rec = reconcile_agreement_entitlements(agr)
        agreement_count += 1
        if not rec["utilization_calculable"]:
            continue
        total_entitlement += rec["purchased_entitlement_quantity"]
        total_usage += rec["consuming_quantity"]
        total_available += rec["available_quantity"]
        if rec["overallocated_quantity"]:
            overallocated_agreements += 1
            overallocated_quantity += rec["overallocated_quantity"]

    return {
        "agreement_count": agreement_count,
        "total_entitlement_quantity": total_entitlement,
        "current_usage": total_usage,
        "available_entitlement": total_available,
        "overallocated_agreements": overallocated_agreements,
        "overallocated_quantity": overallocated_quantity,
        "utilization_percent": (
            round((total_usage / total_entitlement) * 100, 2)
            if total_entitlement
            else None
        ),
        "utilization_calculable": total_entitlement > 0,
    }
def generate_agreement_number() -> str:
    """Generate a concurrency-safe, unique agreement number (LIC-YYYY-NNNNN).

    Uses database-backed sequence lookup with bounded retry loop for SQLite and PostgreSQL.
    Survives record deletions by querying all_objects.
    """
    year = timezone.now().year
    prefix = f"LIC-{year}-"
    max_retries = 10

    for attempt in range(max_retries):
        highest = (
            LicenseAgreement.all_objects.filter(agreement_number__startswith=prefix)
            .order_by("-agreement_number")
            .values_list("agreement_number", flat=True)
            .first()
        )
        if highest:
            try:
                seq = int(highest.split("-")[-1]) + 1 + attempt
            except (ValueError, IndexError):
                seq = LicenseAgreement.all_objects.count() + 1 + attempt
        else:
            seq = 1 + attempt

        candidate = f"{prefix}{seq:05d}"
        if not LicenseAgreement.all_objects.filter(agreement_number=candidate).exists():
            return candidate

    # Fallback to timestamp-based sequence if collisions occur repeatedly
    fallback_seq = int(timezone.now().timestamp() % 100000)
    return f"{prefix}{fallback_seq:05d}"


def generate_allocation_reference(agreement: LicenseAgreement) -> str:
    """Generate a unique reference code for an allocation seat."""
    seq = agreement.allocations.count() + 1
    return f"{agreement.agreement_number}-SEAT-{seq:04d}"


# ==============================================================================
# AUDIT & HISTORY HELPERS
# ==============================================================================

def record_license_history(
    event_type: str,
    actor=None,
    agreement: Optional[LicenseAgreement] = None,
    allocation: Optional[LicenseAllocation] = None,
    installation: Optional[SoftwareInstallation] = None,
    previous_status: str = "",
    new_status: str = "",
    detail: Optional[Dict[str, Any]] = None,
) -> LicenseHistory:
    """Create an immutable, non-sensitive history entry.

    Plaintext keys, secrets, and raw credentials are NEVER permitted in detail.
    """
    clean_detail = dict(detail or {})
    # Strip any accidental sensitive keys
    for dangerous_key in ("secret", "key", "password", "plaintext", "token", "credential"):
        clean_detail.pop(dangerous_key, None)

    return LicenseHistory.objects.create(
        agreement=agreement,
        allocation=allocation,
        installation=installation,
        actor=actor if getattr(actor, "pk", None) else None,
        event_type=event_type,
        previous_status=previous_status or "",
        new_status=new_status or "",
        detail=clean_detail,
    )


# ==============================================================================
# AGREEMENT LIFECYCLE SERVICES
# ==============================================================================

@transaction.atomic
def activate_agreement(agreement: LicenseAgreement, actor) -> LicenseAgreement:
    """Activate a draft LicenseAgreement.

    Requires valid active product, future or current dates, and valid capacity.
    """
    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .select_related("software_product")
        .get(pk=agreement.pk)
    )

    if locked_agreement.status != "draft":
        raise ValidationError(f"Cannot activate agreement in '{locked_agreement.status}' status (must be draft).")

    product = locked_agreement.software_product
    if not product.can_allocate:
        raise ValidationError(
            f"Software product '{product.name}' is {product.approved_status} and cannot be activated."
        )

    if locked_agreement.start_date and locked_agreement.expiry_date and locked_agreement.expiry_date < locked_agreement.start_date:
        raise ValidationError({"expiry_date": "Expiry date cannot be earlier than start date."})

    previous_status = locked_agreement.status
    locked_agreement.status = "active"
    locked_agreement.recalculate_counters(save=False)
    locked_agreement.version += 1
    locked_agreement.save(update_fields=[
        "status", "quantity_allocated", "quantity_reserved",
        "quantity_available", "version", "updated_at"
    ])

    record_license_history(
        event_type="agreement_activated",
        actor=actor,
        agreement=locked_agreement,
        previous_status=previous_status,
        new_status="active",
        detail={"quantity_purchased": locked_agreement.quantity_purchased},
    )

    log_action(
        actor=actor,
        action="status_change",
        instance=locked_agreement,
        reason="Agreement activated into operational service.",
        details={"status": "active"},
    )

    return locked_agreement


@transaction.atomic
def suspend_agreement(agreement: LicenseAgreement, actor, reason: str) -> LicenseAgreement:
    """Suspend an active agreement. Blocks new allocations while retaining existing ones."""
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to suspend a license agreement.")

    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=agreement.pk)
    )

    if locked_agreement.status not in ("active", "expiring"):
        raise ValidationError(f"Cannot suspend agreement in '{locked_agreement.status}' status.")

    previous_status = locked_agreement.status
    locked_agreement.status = "suspended"
    locked_agreement.version += 1
    locked_agreement.save(update_fields=["status", "version", "updated_at"])

    record_license_history(
        event_type="agreement_suspended",
        actor=actor,
        agreement=locked_agreement,
        previous_status=previous_status,
        new_status="suspended",
        detail={"reason": reason.strip()},
    )

    log_action(
        actor=actor,
        action="status_change",
        instance=locked_agreement,
        reason=reason.strip(),
        details={"status": "suspended"},
    )

    return locked_agreement


@transaction.atomic
def resume_agreement(agreement: LicenseAgreement, actor) -> LicenseAgreement:
    """Resume a suspended license agreement."""
    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=agreement.pk)
    )

    if locked_agreement.status != "suspended":
        raise ValidationError(f"Cannot resume agreement in '{locked_agreement.status}' status.")

    previous_status = locked_agreement.status
    # Check if agreement expired during suspension
    today = timezone.now().date()
    new_status = "active"
    if locked_agreement.expiry_date and locked_agreement.expiry_date < today:
        new_status = "expired"

    locked_agreement.status = new_status
    locked_agreement.version += 1
    locked_agreement.save(update_fields=["status", "version", "updated_at"])

    record_license_history(
        event_type="agreement_activated" if new_status == "active" else "agreement_expired",
        actor=actor,
        agreement=locked_agreement,
        previous_status=previous_status,
        new_status=new_status,
        detail={"action": "resumed"},
    )

    log_action(
        actor=actor,
        action="status_change",
        instance=locked_agreement,
        reason="Suspension lifted.",
        details={"status": new_status},
    )

    return locked_agreement


@transaction.atomic
def terminate_agreement(
    agreement: LicenseAgreement,
    actor,
    reason: str,
    revoke_allocations: bool = False,
) -> LicenseAgreement:
    """Terminate a license agreement.

    Requires System Administrator role.
    If active allocations exist, requires revoke_allocations=True to revoke them.
    """
    if not is_system_admin(actor):
        raise ValidationError("Only System Administrators are authorized to terminate license agreements.")

    if not reason or not reason.strip():
        raise ValidationError("A reason is required to terminate a license agreement.")

    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=agreement.pk)
    )

    if locked_agreement.status in ("terminated", "retired"):
        raise ValidationError(f"Agreement is already {locked_agreement.status}.")

    if locked_agreement.status not in ("active", "expiring", "expired", "suspended"):
        raise ValidationError(f"Cannot terminate agreement in '{locked_agreement.status}' status.")

    active_allocs = locked_agreement.allocations.filter(status__in=["assigned", "active", "reserved"])
    active_count = active_allocs.count()

    if active_count > 0:
        if not revoke_allocations:
            raise ValidationError(
                f"Agreement has {active_count} active allocation(s). "
                f"Confirm revocation by providing revoke_allocations=True."
            )
        # Revoke all active allocations
        for alloc in active_allocs.select_for_update():
            alloc.status = "revoked"
            alloc.revoked_at = timezone.now()
            alloc.revoked_by = actor
            alloc.revocation_reason = f"Agreement {locked_agreement.agreement_number} terminated: {reason.strip()}"
            alloc.version += 1
            alloc.save(update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "version", "updated_at"])
            record_license_history(
                event_type="allocation_revoked",
                actor=actor,
                agreement=locked_agreement,
                allocation=alloc,
                previous_status="active",
                new_status="revoked",
                detail={"reason": "agreement_terminated"},
            )

    previous_status = locked_agreement.status
    locked_agreement.status = "terminated"
    locked_agreement.recalculate_counters(save=False)
    locked_agreement.version += 1
    locked_agreement.save(update_fields=[
        "status", "quantity_allocated", "quantity_reserved",
        "quantity_available", "version", "updated_at"
    ])

    record_license_history(
        event_type="agreement_terminated",
        actor=actor,
        agreement=locked_agreement,
        previous_status=previous_status,
        new_status="terminated",
        detail={"reason": reason.strip(), "revoked_allocations": active_count if revoke_allocations else 0},
    )

    log_action(
        actor=actor,
        action="status_change",
        instance=locked_agreement,
        reason=reason.strip(),
        details={"status": "terminated", "revoked_allocations": active_count if revoke_allocations else 0},
    )

    return locked_agreement


@transaction.atomic
def retire_agreement(agreement: LicenseAgreement, actor, reason: str = "") -> LicenseAgreement:
    """Retire an agreement. Retains historical records while preventing new allocations."""
    if not is_it_manager(actor):
        raise ValidationError("Only IT Managers or System Admins can retire an agreement.")

    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=agreement.pk)
    )

    if locked_agreement.status in ("terminated", "retired"):
        raise ValidationError(f"Cannot retire agreement in '{locked_agreement.status}' status.")

    if locked_agreement.status not in ("draft", "active", "expiring", "expired", "suspended"):
        raise ValidationError(f"Cannot retire agreement in '{locked_agreement.status}' status.")

    previous_status = locked_agreement.status
    locked_agreement.status = "retired"
    locked_agreement.version += 1
    locked_agreement.save(update_fields=["status", "version", "updated_at"])

    record_license_history(
        event_type="agreement_retired",
        actor=actor,
        agreement=locked_agreement,
        previous_status=previous_status,
        new_status="retired",
        detail={"reason": reason.strip() if reason else "Retired from service"},
    )

    log_action(
        actor=actor,
        action="retire",
        instance=locked_agreement,
        reason=reason.strip() if reason else "Retired from service",
        details={"status": "retired"},
    )

    return locked_agreement


@transaction.atomic
def recalculate_agreement_capacity(agreement: LicenseAgreement) -> LicenseAgreement:
    """Recalculate seat counters with row-level database lock."""
    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=agreement.pk)
    )
    locked_agreement.recalculate_counters(save=True)
    return locked_agreement


# ==============================================================================
# ALLOCATION SERVICES
# ==============================================================================

@transaction.atomic
def allocate_license(
    agreement: LicenseAgreement,
    allocation_type: str,
    assigned_user=None,
    assigned_asset=None,
    department=None,
    actor=None,
    notes: str = "",
    expected_release_date=None,
    service_request=None,
    auto_activate: bool = True,
    allow_duplicate: bool = False,
) -> LicenseAllocation:
    """Allocate a license seat to a user, asset, or department.

    Enforces capacity limits under a select_for_update lock.
    Guards against over-allocation and duplicate assignments.
    """
    locked_agreement = (
        LicenseAgreement.objects.select_for_update()
        .select_related("software_product")
        .get(pk=agreement.pk)
    )

    if locked_agreement.status not in ("active", "expiring"):
        raise ValidationError(
            f"Cannot allocate from agreement in '{locked_agreement.status}' status (must be active or expiring)."
        )

    if locked_agreement.expiry_date and locked_agreement.expiry_date < timezone.now().date():
        raise ValidationError(
            f"Cannot allocate from expired agreement {locked_agreement.agreement_number} "
            f"(expired {locked_agreement.expiry_date})."
        )

    product = locked_agreement.software_product
    if not product.can_allocate:
        raise ValidationError(
            f"Software product '{product.name}' is prohibited or retired; cannot issue allocations."
        )

    # Validate target parameters according to allocation_type
    if allocation_type == "user":
        if not assigned_user:
            raise ValidationError({"assigned_user": "An assigned employee is required for a user allocation."})
        if not assigned_user.is_active or getattr(assigned_user, "is_deleted", False):
            raise ValidationError({"assigned_user": "Cannot allocate license to an inactive or deleted employee."})
        if not allow_duplicate:
            existing_user_alloc = (
                LicenseAllocation.objects.filter(
                    agreement__software_product=product,
                    assigned_user=assigned_user,
                    status__in=CONSUMING_ALLOCATION_STATUSES,
                ).exists()
            )
            if existing_user_alloc:
                raise ValidationError(
                    {"assigned_user": f"Employee {assigned_user.email} already holds an active allocation for '{product.name}'."}
                )

    elif allocation_type == "device":
        if not assigned_asset:
            raise ValidationError({"assigned_asset": "An assigned asset is required for a device allocation."})
        if assigned_asset.status in ("retired", "lost", "disposed") or getattr(assigned_asset, "is_deleted", False):
            raise ValidationError({"assigned_asset": f"Asset '{assigned_asset.asset_tag}' is {assigned_asset.status}."})
        if not allow_duplicate:
            existing_asset_alloc = (
                LicenseAllocation.objects.filter(
                    agreement__software_product=product,
                    assigned_asset=assigned_asset,
                    status__in=CONSUMING_ALLOCATION_STATUSES,
                ).exists()
            )
            if existing_asset_alloc:
                raise ValidationError(
                    {"assigned_asset": f"Asset {assigned_asset.asset_tag} already has an active allocation for '{product.name}'."}
                )

    elif allocation_type == "department":
        if not department:
            raise ValidationError({"department": "A department is required for a department allocation."})
        if getattr(department, "is_deleted", False) or not department.is_active:
            raise ValidationError({"department": "Cannot allocate license to an inactive department."})

    elif allocation_type == "site":
        if not locked_agreement.is_unlimited:
            raise ValidationError("Site allocations are only valid for site, enterprise, or volume agreements.")

    elif allocation_type == "concurrent_reservation":
        if locked_agreement.license_model != "concurrent" and not locked_agreement.is_unlimited:
            raise ValidationError("Concurrent reservation requires a concurrent or unlimited agreement model.")

    else:
        raise ValidationError({"allocation_type": f"Unsupported allocation type '{allocation_type}'."})

    # Capacity check under row lock
    if not locked_agreement.is_unlimited:
        capacity_limit = get_agreement_entitlement_limit(locked_agreement)
        active_and_reserved = locked_agreement.allocations.filter(
            status__in=CONSUMING_ALLOCATION_STATUSES
        ).count()

        if capacity_limit is not None and active_and_reserved >= capacity_limit:
            raise ValidationError(
                f"Agreement {locked_agreement.agreement_number} has reached maximum capacity "
                f"({active_and_reserved}/{capacity_limit} allocated/reserved). Over-allocation blocked."
            )

    now = timezone.now()
    initial_status = "active" if auto_activate else "assigned"

    ref = generate_allocation_reference(locked_agreement)

    allocation = LicenseAllocation.objects.create(
        agreement=locked_agreement,
        allocation_type=allocation_type,
        assigned_user=assigned_user,
        assigned_asset=assigned_asset,
        department=department,
        allocation_reference=ref,
        status=initial_status,
        assigned_at=now,
        assigned_by=actor if getattr(actor, "pk", None) else None,
        activated_at=now if auto_activate else None,
        activation_confirmed_by=actor if (auto_activate and getattr(actor, "pk", None)) else None,
        last_verified_at=now if auto_activate else None,
        last_verified_by=actor if (auto_activate and getattr(actor, "pk", None)) else None,
        expected_release_date=expected_release_date,
        notes=notes or "",
        service_request=service_request,
    )

    # Recalculate agreement counters
    locked_agreement.recalculate_counters(save=True)

    evaluate_license_compliance(agreement=locked_agreement, actor=actor)

    record_license_history(
        event_type="allocation_activated" if auto_activate else "allocation_assigned",
        actor=actor,
        agreement=locked_agreement,
        allocation=allocation,
        previous_status="",
        new_status=initial_status,
        detail={
            "type": allocation_type,
            "reference": ref,
            "target": str(assigned_user or assigned_asset or department or "site"),
        },
    )

    log_action(
        actor=actor,
        action="assignment",
        instance=allocation,
        reason=notes or f"Allocated {locked_agreement.software_product.name}",
        details={
            "agreement": locked_agreement.agreement_number,
            "type": allocation_type,
            "status": initial_status,
        },
    )

    # Notification to employee if user allocation
    if assigned_user and getattr(assigned_user, "pk", None):
        notify_user(
            assigned_user, "license_assigned",
            f"License Assigned: {product.name}",
            (
                f"A license for '{product.name}' has been assigned to you under agreement "
                f"{locked_agreement.agreement_number} (Ref: {ref})."
            ),
            entity_type="licensing.LicenseAllocation",
            object_id=str(allocation.pk),
            post_commit=False,
        )

    return allocation


@transaction.atomic
def revoke_allocation(
    allocation: LicenseAllocation,
    actor,
    reason: str,
) -> LicenseAllocation:
    """Revoke an active or reserved allocation seat.

    Reason is mandatory. Recalculates agreement counters under row lock.
    """
    if not reason or not reason.strip():
        raise ValidationError("A revocation reason is required.")

    # Lock order is agreement -> allocation everywhere allocation state changes.
    # This matches allocate_license and terminate_agreement and avoids a
    # deadlock cycle with agreement termination.
    agreement = LicenseAgreement.objects.select_for_update().get(
        pk=allocation.agreement_id
    )

    locked_alloc = (
        LicenseAllocation.objects.select_for_update()
        .get(pk=allocation.pk)
    )

    if locked_alloc.status == "revoked":
        raise ValidationError("Allocation is already revoked.")

    previous_status = locked_alloc.status
    now = timezone.now()

    locked_alloc.status = "revoked"
    locked_alloc.revoked_at = now
    locked_alloc.revoked_by = actor if getattr(actor, "pk", None) else None
    locked_alloc.revocation_reason = reason.strip()
    locked_alloc.version += 1
    locked_alloc.save(update_fields=[
        "status", "revoked_at", "revoked_by", "revocation_reason", "version", "updated_at"
    ])

    # Recalculate agreement counters under the already-held agreement lock
    agreement.recalculate_counters(save=True)
    evaluate_license_compliance(agreement=agreement, actor=actor)

    record_license_history(
        event_type="allocation_revoked",
        actor=actor,
        agreement=agreement,
        allocation=locked_alloc,
        previous_status=previous_status,
        new_status="revoked",
        detail={"reason": reason.strip()},
    )

    log_action(
        actor=actor,
        action="assignment",
        instance=locked_alloc,
        reason=reason.strip(),
        details={"status": "revoked"},
    )

    # In-app notification to affected user
    if locked_alloc.assigned_user:
        notify_user(
            locked_alloc.assigned_user, "license_revoked",
            f"License Revoked: {agreement.software_product.name}",
            f"Your license for '{agreement.software_product.name}' has been revoked. Reason: {reason.strip()}",
            entity_type="licensing.LicenseAllocation",
            object_id=str(locked_alloc.pk),
            post_commit=False,
        )

    return locked_alloc


@transaction.atomic
def release_allocation(
    allocation: LicenseAllocation,
    actor,
    reason: str = "",
) -> LicenseAllocation:
    """Release (revoke) an allocation seat and restore agreement capacity."""
    resolved_reason = (reason or "").strip() or "Released"
    return revoke_allocation(allocation, actor, reason=resolved_reason)


def get_offboarding_allocation_preview(user) -> List[Dict[str, Any]]:
    """Return active allocations that would be reclaimed during offboarding."""
    allocations = get_active_allocations_for_user(user)
    return [
        {
            "id": alloc.pk,
            "agreement_number": alloc.agreement.agreement_number,
            "product_name": alloc.agreement.software_product.name,
            "allocation_reference": alloc.allocation_reference,
            "allocation_type": alloc.allocation_type,
            "status": alloc.status,
            "assigned_at": alloc.assigned_at.isoformat() if alloc.assigned_at else None,
        }
        for alloc in allocations
    ]


def bulk_allocate_licenses(
    agreement: LicenseAgreement,
    allocations_data: List[Dict[str, Any]],
    actor,
) -> Dict[str, Any]:
    """Perform bulk seat allocations with per-row isolation and reporting.

    Does not silently fail. Returns a comprehensive result breakdown.
    """
    results = []
    succeeded = 0
    failed = 0

    for idx, item in enumerate(allocations_data):
        target_repr = str(item.get("assigned_user_id") or item.get("assigned_asset_id") or item.get("department_id") or idx)
        try:
            with transaction.atomic():
                user = None
                asset = None
                dept = None
                alloc_type = item.get("allocation_type", "user")

                if item.get("assigned_user_id"):
                    from accounts.models import User
                    user = User.objects.get(pk=item["assigned_user_id"])
                if item.get("assigned_asset_id"):
                    from assets.models import Asset
                    asset = Asset.objects.get(pk=item["assigned_asset_id"])
                if item.get("department_id"):
                    from accounts.models import Department
                    dept = Department.objects.get(pk=item["department_id"])

                alloc = allocate_license(
                    agreement=agreement,
                    allocation_type=alloc_type,
                    assigned_user=user,
                    assigned_asset=asset,
                    department=dept,
                    actor=actor,
                    notes=item.get("notes", ""),
                    allow_duplicate=item.get("allow_duplicate", False),
                )
                succeeded += 1
                results.append({
                    "row": idx + 1,
                    "target": target_repr,
                    "success": True,
                    "allocation_id": alloc.pk,
                    "reference": alloc.allocation_reference,
                })
        except Exception as exc:
            failed += 1
            results.append({
                "row": idx + 1,
                "target": target_repr,
                "success": False,
                "error": str(exc),
            })

    return {
        "total": len(allocations_data),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def bulk_revoke_allocations(
    allocation_ids: List[int],
    actor,
    reason: str,
) -> Dict[str, Any]:
    """Bulk revoke allocations with per-row isolation and reporting."""
    if not reason or not reason.strip():
        raise ValidationError("A revocation reason is required for bulk revocation.")

    results = []
    succeeded = 0
    failed = 0

    for alloc_id in allocation_ids:
        try:
            alloc = LicenseAllocation.objects.get(pk=alloc_id)
            revoke_allocation(alloc, actor, reason=reason)
            succeeded += 1
            results.append({"id": alloc_id, "success": True})
        except Exception as exc:
            failed += 1
            results.append({"id": alloc_id, "success": False, "error": str(exc)})

    return {
        "total": len(allocation_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def verify_allocation(allocation: LicenseAllocation, actor, notes: str = "") -> LicenseAllocation:
    """Record verification that an allocation remains active and in-use."""
    now = timezone.now()
    allocation.last_verified_at = now
    allocation.last_verified_by = actor if getattr(actor, "pk", None) else None
    if notes:
        allocation.notes = f"{allocation.notes}\n[Verification {now:%Y-%m-%d}]: {notes}".strip()
    allocation.save(update_fields=["last_verified_at", "last_verified_by", "notes", "updated_at"])

    record_license_history(
        event_type="allocation_verified",
        actor=actor,
        agreement=allocation.agreement,
        allocation=allocation,
        detail={"notes": notes},
    )
    return allocation


# ==============================================================================
# SOFTWARE INSTALLATION SERVICES
# ==============================================================================

@transaction.atomic
def record_installation(
    software_product: SoftwareProduct,
    asset,
    allocation: Optional[LicenseAllocation] = None,
    installed_version: str = "",
    install_date=None,
    installed_by=None,
    source: str = "manual",
    notes: str = "",
) -> SoftwareInstallation:
    """Record or update a software installation on a hardware asset."""
    # Enforce active asset
    if asset.status in ("retired", "lost", "disposed") or getattr(asset, "is_deleted", False):
        raise ValidationError(f"Cannot record software on {asset.status} asset {asset.asset_tag}.")

    # Evaluate compliance state
    compliance_status = "compliant"
    if software_product.approved_status == "prohibited":
        compliance_status = "prohibited_software"
    elif allocation is not None:
        if allocation.status == "expired":
            compliance_status = "expired_license"
        elif allocation.agreement.status == "expired":
            compliance_status = "expired_license"
        else:
            compliance_status = "compliant"
    elif software_product.license_required:
        compliance_status = "unlicensed"

    inst, created = SoftwareInstallation.objects.get_or_create(
        software_product=software_product,
        asset=asset,
        defaults={
            "allocation": allocation,
            "installed_version": installed_version,
            "install_date": install_date or timezone.now().date(),
            "installed_by": installed_by if getattr(installed_by, "pk", None) else None,
            "source": source,
            "compliance_status": compliance_status,
            "notes": notes,
        },
    )

    if not created:
        inst.allocation = allocation
        inst.installed_version = installed_version or inst.installed_version
        inst.last_seen_at = timezone.now()
        inst.status = "installed"
        inst.compliance_status = compliance_status
        if notes:
            inst.notes = notes
        inst.save()

    record_license_history(
        event_type="installation_recorded",
        actor=installed_by,
        installation=inst,
        agreement=allocation.agreement if allocation else None,
        allocation=allocation,
        detail={"product": software_product.name, "asset": asset.asset_tag, "compliance": compliance_status},
    )

    log_action(
        actor=installed_by,
        action="create" if created else "update",
        instance=inst,
        reason=f"Recorded software {software_product.name} on {asset.asset_tag}",
        details={"compliance_status": compliance_status},
    )

    return inst


@transaction.atomic
def remove_installation(installation: SoftwareInstallation, actor, notes: str = "") -> SoftwareInstallation:
    """Mark an installation as removed, retaining historical traceability."""
    installation.status = "removed"
    if notes:
        installation.notes = f"{installation.notes}\n[Removed {timezone.now():%Y-%m-%d}]: {notes}".strip()
    installation.save(update_fields=["status", "notes", "updated_at"])

    record_license_history(
        event_type="installation_removed",
        actor=actor,
        installation=installation,
        agreement=installation.allocation.agreement if installation.allocation else None,
        allocation=installation.allocation,
        detail={"notes": notes},
    )

    log_action(
        actor=actor,
        action="update",
        instance=installation,
        reason="Installation marked removed",
        details={"status": "removed"},
    )

    return installation


# ==============================================================================
# RENEWAL & THRESHOLD SERVICES
# ==============================================================================

def get_renewal_admin_threshold() -> Decimal:
    """Retrieve the configurable approval threshold requiring System Admin sign-off."""
    raw = getattr(settings, "LICENSE_RENEWAL_SYSTEM_ADMIN_THRESHOLD", "50000.00")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("50000.00")


@transaction.atomic
def submit_renewal_request(
    agreement: LicenseAgreement,
    proposed_start_date,
    proposed_expiry_date,
    proposed_quantity: int,
    proposed_unit_cost: Decimal,
    proposed_total_cost: Decimal,
    currency: str,
    requested_by,
    reason: str = "",
    procurement_purchase_request=None,
    procurement_purchase_order=None,
) -> LicenseRenewal:
    """Submit a license agreement renewal proposal for review."""
    if agreement.status in ("draft", "terminated", "retired"):
        raise ValidationError(f"Cannot submit renewal for agreement in '{agreement.status}' status.")

    # Only one active pending review allowed per agreement
    existing_pending = LicenseRenewal.objects.filter(
        agreement=agreement,
        status="pending_review",
    ).exists()
    if existing_pending:
        raise ValidationError("An active pending renewal proposal already exists for this agreement.")

    if proposed_expiry_date <= proposed_start_date:
        raise ValidationError("Proposed expiry date must be strictly after proposed start date.")

    renewal = LicenseRenewal.objects.create(
        agreement=agreement,
        previous_start_date=agreement.start_date,
        previous_expiry_date=agreement.expiry_date,
        proposed_start_date=proposed_start_date,
        proposed_expiry_date=proposed_expiry_date,
        proposed_quantity=proposed_quantity,
        proposed_unit_cost=proposed_unit_cost,
        proposed_total_cost=proposed_total_cost,
        currency=currency or agreement.currency,
        status="pending_review",
        reason=reason or "",
        requested_by=requested_by if getattr(requested_by, "pk", None) else None,
        requested_at=timezone.now(),
        procurement_purchase_request=procurement_purchase_request,
        procurement_purchase_order=procurement_purchase_order,
    )

    record_license_history(
        event_type="renewal_review_started",
        actor=requested_by,
        agreement=agreement,
        detail={"renewal_id": renewal.pk, "total_cost": str(proposed_total_cost)},
    )

    log_action(
        actor=requested_by,
        action="create",
        instance=renewal,
        reason="Renewal proposal submitted for review",
        details={"status": "pending_review", "total": str(proposed_total_cost)},
    )

    return renewal


@transaction.atomic
def review_renewal_request(
    renewal: LicenseRenewal,
    actor,
    decision: str,
    review_reason: str = "",
) -> LicenseRenewal:
    """Approve or reject a renewal proposal.

    Enforces separation of duties (requester cannot approve own renewal)
    and threshold delegation (System Admin required for high-cost or foreign currency renewals).
    """
    if decision not in ("approved", "rejected"):
        raise ValidationError("Decision must be either 'approved' or 'rejected'.")

    locked_renewal = (
        LicenseRenewal.objects.select_for_update()
        .select_related("agreement")
        .get(pk=renewal.pk)
    )

    if locked_renewal.status != "pending_review":
        raise ValidationError(f"Cannot review renewal in '{locked_renewal.status}' status.")

    # Separation of duties
    if locked_renewal.requested_by_id and locked_renewal.requested_by_id == getattr(actor, "pk", None):
        raise ValidationError("Separation of duties violation: Requester cannot approve or reject their own renewal.")

    # Threshold & currency check
    threshold = get_renewal_admin_threshold()
    configured_currency = getattr(settings, "LICENSE_THRESHOLD_CURRENCY", "USD")

    requires_sysadmin = (
        locked_renewal.currency != configured_currency
        or locked_renewal.proposed_total_cost >= threshold
    )

    if requires_sysadmin and not is_system_admin(actor):
        raise ValidationError(
            f"Renewal requires System Administrator approval (Amount: {locked_renewal.currency} "
            f"{locked_renewal.proposed_total_cost} >= Threshold {configured_currency} {threshold})."
        )
    elif not requires_sysadmin and not is_it_manager(actor):
        raise ValidationError("Only IT Managers or System Admins can review renewals.")

    now = timezone.now()
    locked_renewal.status = decision
    locked_renewal.reviewed_by = actor
    locked_renewal.reviewed_at = now
    locked_renewal.review_reason = review_reason or ""
    locked_renewal.version += 1
    locked_renewal.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "review_reason", "version", "updated_at"
    ])

    event_type = "renewal_approved" if decision == "approved" else "renewal_rejected"
    record_license_history(
        event_type=event_type,
        actor=actor,
        agreement=locked_renewal.agreement,
        detail={"decision": decision, "reason": review_reason},
    )

    log_action(
        actor=actor,
        action="update",
        instance=locked_renewal,
        reason=review_reason or f"Renewal {decision}",
        details={"status": decision},
    )

    if locked_renewal.requested_by:
        notify_user(
            locked_renewal.requested_by, "license_renewal_decision",
            f"Renewal {decision.capitalize()}: {locked_renewal.agreement.agreement_number}",
            f"Your renewal proposal for {locked_renewal.agreement.agreement_number} was {decision}.",
            entity_type="licensing.LicenseRenewal",
            object_id=str(locked_renewal.pk),
            post_commit=False,
        )

    return locked_renewal


@transaction.atomic
def apply_approved_renewal(
    renewal: LicenseRenewal,
    actor,
) -> LicenseAgreement:
    """Apply an approved renewal to the target agreement transactionally."""
    locked_renewal = (
        LicenseRenewal.objects.select_for_update()
        .get(pk=renewal.pk)
    )

    if locked_renewal.status != "approved":
        raise ValidationError(f"Cannot apply renewal in '{locked_renewal.status}' status (must be approved).")

    agreement = (
        LicenseAgreement.objects.select_for_update()
        .get(pk=locked_renewal.agreement_id)
    )

    if agreement.status in ("terminated", "retired"):
        raise ValidationError(f"Cannot apply renewal to a {agreement.status} agreement.")

    if agreement.status in ("terminated", "retired"):
        raise ValidationError(f"Cannot apply renewal to a {agreement.status} agreement.")

    if locked_renewal.proposed_expiry_date <= locked_renewal.proposed_start_date:
        raise ValidationError("Proposed expiry date must be strictly after proposed start date.")

    # Apply proposed dates and terms
    agreement.start_date = locked_renewal.proposed_start_date
    agreement.expiry_date = locked_renewal.proposed_expiry_date
    agreement.quantity_purchased = locked_renewal.proposed_quantity
    agreement.unit_cost = locked_renewal.proposed_unit_cost
    agreement.total_cost = locked_renewal.proposed_total_cost
    agreement.currency = locked_renewal.currency

    # Update agreement status: if expired/expiring -> active
    today = timezone.now().date()
    if agreement.expiry_date and agreement.expiry_date >= today:
        agreement.status = "active"

    agreement.recalculate_counters(save=False)
    agreement.version += 1
    agreement.save()

    locked_renewal.status = "completed"
    locked_renewal.version += 1
    locked_renewal.save(update_fields=["status", "version", "updated_at"])

    record_license_history(
        event_type="renewal_applied",
        actor=actor,
        agreement=agreement,
        detail={
            "new_expiry": str(agreement.expiry_date),
            "quantity": agreement.quantity_purchased,
            "total_cost": str(agreement.total_cost),
        },
    )

    log_action(
        actor=actor,
        action="update",
        instance=agreement,
        reason="Approved renewal terms applied.",
        details={"status": agreement.status, "expiry": str(agreement.expiry_date)},
    )

    return agreement


# ==============================================================================
# COMPLIANCE ENGINE
# ==============================================================================

def compute_finding_fingerprint(
    finding_type: str,
    product_id: Optional[int] = None,
    agreement_id: Optional[int] = None,
    allocation_id: Optional[int] = None,
    installation_id: Optional[int] = None,
    asset_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> str:
    """Generate a deterministic SHA-256 fingerprint representing an issue identity."""
    raw = f"{finding_type}:{product_id or ''}:{agreement_id or ''}:{allocation_id or ''}:{installation_id or ''}:{asset_id or ''}:{user_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


AUTO_RESOLVED_NOTE = "Automatically resolved: condition no longer present."


def _append_auto_resolution_note(existing: str) -> str:
    """Preserve human-authored resolution text and add the engine's result."""
    existing = (existing or "").strip()
    if not existing:
        return AUTO_RESOLVED_NOTE
    if AUTO_RESOLVED_NOTE in existing:
        return existing
    return f"{existing}\n{AUTO_RESOLVED_NOTE}"


def _upsert_finding(fingerprint: str, defaults: Dict[str, Any]) -> LicenseComplianceFinding:
    """Create or refresh a finding without discarding human decisions.

    Acknowledged findings stay acknowledged until the condition is resolved,
    and false positives are never reopened automatically. Resolved findings
    are reopened when the condition is detected again.
    """
    finding = (
        LicenseComplianceFinding.objects.filter(fingerprint=fingerprint)
        .order_by("pk")
        .first()
    )
    if finding is None:
        return LicenseComplianceFinding.objects.create(
            fingerprint=fingerprint, **defaults
        )

    if finding.status in ("acknowledged", "false_positive"):
        return finding

    for field, value in defaults.items():
        setattr(finding, field, value)
    finding.status = "open"
    finding.resolved_at = None
    finding.resolved_by = None
    # Drop only the engine's generated line; keep any human-authored text.
    finding.resolution_note = "\n".join(
        line for line in (finding.resolution_note or "").splitlines()
        if line.strip() != AUTO_RESOLVED_NOTE
    ).strip()
    finding.save()
    return finding


def evaluate_license_compliance(
    software_product: Optional[SoftwareProduct] = None,
    agreement: Optional[LicenseAgreement] = None,
    asset=None,
    user=None,
    actor=None,
) -> List[LicenseComplianceFinding]:
    """Execute deterministic compliance evaluation rules.

    Idempotently creates or updates open findings.
    Automatically resolves findings when conditions are corrected.
    """
    findings: List[LicenseComplianceFinding] = []
    today = timezone.now().date()
    unused_threshold_days = getattr(settings, "LICENSE_UNUSED_DAYS", 90)
    unused_cutoff = timezone.now() - timezone.timedelta(days=unused_threshold_days)

    # --------------------------------------------------------------------------
    # 1. Over-allocated Agreements
    # --------------------------------------------------------------------------
    agr_qs = LicenseAgreement.objects.filter(is_deleted=False)
    if agreement:
        agr_qs = agr_qs.filter(pk=agreement.pk)
    if software_product:
        agr_qs = agr_qs.filter(software_product=software_product)

    for agr in agr_qs:
        if not agr.is_unlimited:
            limit = get_agreement_entitlement_limit(agr)
            consuming_seats = agr.allocations.filter(
                status__in=CONSUMING_ALLOCATION_STATUSES
            ).count()
            if limit is not None and consuming_seats > limit:
                fp = compute_finding_fingerprint("over_allocated", agreement_id=agr.pk, product_id=agr.software_product_id)
                fnd = _upsert_finding(fp, {
                    "finding_type": "over_allocated",
                    "severity": "critical",
                    "agreement": agr,
                    "software_product": agr.software_product,
                    "status": "open",
                    "title": f"Over-allocation on agreement {agr.agreement_number}",
                    "description": f"Consuming allocations ({consuming_seats}) exceed entitlement limit ({limit}).",
                })
                findings.append(fnd)

    # --------------------------------------------------------------------------
    # 2. Expired and Expiring Agreements
    # --------------------------------------------------------------------------
    for agr in agr_qs.filter(expiry_date__isnull=False):
        if agr.expiry_date < today and agr.status not in ("terminated", "retired"):
            fp = compute_finding_fingerprint("expired_agreement", agreement_id=agr.pk, product_id=agr.software_product_id)
            fnd = _upsert_finding(fp, {
                "finding_type": "expired_agreement",
                "severity": "high",
                "agreement": agr,
                "software_product": agr.software_product,
                "status": "open",
                "title": f"License agreement {agr.agreement_number} has expired",
                "description": f"Agreement expired on {agr.expiry_date}. Associated seats may be non-compliant.",
            })
            findings.append(fnd)
        elif agr.renewal_date and today >= agr.renewal_date and agr.expiry_date >= today:
            fp = compute_finding_fingerprint("expiring_agreement", agreement_id=agr.pk, product_id=agr.software_product_id)
            fnd = _upsert_finding(fp, {
                "finding_type": "expiring_agreement",
                "severity": "medium",
                "agreement": agr,
                "software_product": agr.software_product,
                "status": "open",
                "title": f"License agreement {agr.agreement_number} is approaching renewal/expiry",
                "description": f"Agreement reaches renewal date {agr.renewal_date} (expires {agr.expiry_date}).",
            })
            findings.append(fnd)

    # --------------------------------------------------------------------------
    # 2b. Missing or Incomplete Agreement Information
    # --------------------------------------------------------------------------
    for agr in agr_qs:
        missing = []
        if not agr.start_date:
            missing.append("start date")
        if not agr.expiry_date:
            missing.append("expiry date")
        if not agr.is_unlimited and (not agr.quantity_purchased or agr.quantity_purchased <= 0):
            missing.append("purchased quantity")
        if missing:
            fp = compute_finding_fingerprint("missing_documentation", agreement_id=agr.pk, product_id=agr.software_product_id)
            fnd = _upsert_finding(fp, {
                "finding_type": "missing_documentation",
                "severity": "medium",
                "agreement": agr,
                "software_product": agr.software_product,
                "status": "open",
                "title": f"Missing license information for {agr.agreement_number}",
                "description": f"Agreement is missing required information: {', '.join(missing)}.",
            })
            findings.append(fnd)

        if not agr.is_unlimited:
            entitlement_limit = get_agreement_entitlement_limit(agr)
            if not entitlement_limit or entitlement_limit <= 0:
                fp = compute_finding_fingerprint("missing_entitlement_quantity", agreement_id=agr.pk, product_id=agr.software_product_id)
                fnd = _upsert_finding(fp, {
                    "finding_type": "missing_entitlement_quantity",
                    "severity": "high",
                    "agreement": agr,
                    "software_product": agr.software_product,
                    "status": "open",
                    "title": f"Missing entitlement quantity for {agr.agreement_number}",
                    "description": (
                        "Agreement has no positive seat entitlement; capacity checks "
                        "cannot be evaluated and utilization is not calculable."
                    ),
                })
                findings.append(fnd)

    # --------------------------------------------------------------------------
    # 3. Allocations to Inactive Employees or Retired Assets
    # --------------------------------------------------------------------------
    alloc_qs = LicenseAllocation.objects.filter(status__in=CONSUMING_ALLOCATION_STATUSES).select_related("assigned_user", "assigned_asset", "agreement__software_product")
    if agreement:
        alloc_qs = alloc_qs.filter(agreement=agreement)
    if user:
        alloc_qs = alloc_qs.filter(assigned_user=user)
    if asset:
        alloc_qs = alloc_qs.filter(assigned_asset=asset)

    for alloc in alloc_qs:
        alloc_agreement = alloc.agreement

        # Allocation still consuming capacity on a terminated agreement
        if alloc_agreement.status == "terminated":
            fp = compute_finding_fingerprint(
                "terminated_agreement_allocation",
                allocation_id=alloc.pk,
                agreement_id=alloc_agreement.pk,
            )
            fnd = _upsert_finding(fp, {
                "finding_type": "terminated_agreement_allocation",
                "severity": "high",
                "allocation": alloc,
                "agreement": alloc_agreement,
                "software_product": alloc_agreement.software_product,
                "status": "open",
                "title": f"Allocation on terminated agreement {alloc_agreement.agreement_number}",
                "description": (
                    f"Allocation '{alloc.allocation_reference}' is still {alloc.status} "
                    f"on terminated agreement {alloc_agreement.agreement_number}."
                ),
            })
            findings.append(fnd)

        # Allocation still consuming capacity on an expired agreement
        elif (
            alloc_agreement.expiry_date
            and alloc_agreement.expiry_date < today
            and alloc_agreement.status not in ("terminated", "retired")
        ):
            fp = compute_finding_fingerprint(
                "expired_agreement_allocation",
                allocation_id=alloc.pk,
                agreement_id=alloc_agreement.pk,
            )
            fnd = _upsert_finding(fp, {
                "finding_type": "expired_agreement_allocation",
                "severity": "high",
                "allocation": alloc,
                "agreement": alloc_agreement,
                "software_product": alloc_agreement.software_product,
                "status": "open",
                "title": f"Allocation on expired agreement {alloc_agreement.agreement_number}",
                "description": (
                    f"Allocation '{alloc.allocation_reference}' is still {alloc.status} "
                    f"on agreement {alloc_agreement.agreement_number}, which expired "
                    f"on {alloc_agreement.expiry_date}."
                ),
            })
            findings.append(fnd)

        # Inactive employee check
        if alloc.allocation_type == "user" and alloc.assigned_user:
            u = alloc.assigned_user
            if not u.is_active or getattr(u, "is_deleted", False):
                fp = compute_finding_fingerprint("allocation_to_inactive_user", allocation_id=alloc.pk, user_id=u.pk)
                fnd = _upsert_finding(fp, {
                    "finding_type": "allocation_to_inactive_user",
                    "severity": "high",
                    "allocation": alloc,
                    "agreement": alloc.agreement,
                    "software_product": alloc.agreement.software_product,
                    "user": u,
                    "status": "open",
                    "title": f"License allocated to inactive employee {u.email}",
                    "description": f"Employee {u.email} holds active allocation '{alloc.allocation_reference}' but is deactivated.",
                })
                findings.append(fnd)

        # Retired asset check
        if alloc.allocation_type == "device" and alloc.assigned_asset:
            a = alloc.assigned_asset
            if a.status in ("retired", "lost", "disposed") or getattr(a, "is_deleted", False):
                fp = compute_finding_fingerprint("allocation_to_retired_asset", allocation_id=alloc.pk, asset_id=a.pk)
                fnd = _upsert_finding(fp, {
                    "finding_type": "allocation_to_retired_asset",
                    "severity": "medium",
                    "allocation": alloc,
                    "agreement": alloc.agreement,
                    "software_product": alloc.agreement.software_product,
                    "asset": a,
                    "status": "open",
                    "title": f"License allocated to inactive/retired asset {a.asset_tag}",
                    "description": f"Asset {a.asset_tag} holds active allocation '{alloc.allocation_reference}' but is {a.status}.",
                })
                findings.append(fnd)

        # Potentially unused allocation (verification gap > 90 days)
        if alloc.allocation_type in ("user", "device"):
            check_date = alloc.last_verified_at or alloc.assigned_at
            if check_date and check_date < unused_cutoff:
                fp = compute_finding_fingerprint("unused_license", allocation_id=alloc.pk)
                fnd = _upsert_finding(fp, {
                    "finding_type": "unused_license",
                    "severity": "low",
                    "allocation": alloc,
                    "agreement": alloc.agreement,
                    "software_product": alloc.agreement.software_product,
                    "user": alloc.assigned_user,
                    "asset": alloc.assigned_asset,
                    "status": "open",
                    "title": f"Allocation {alloc.allocation_reference} verification gap (> {unused_threshold_days} days)",
                    "description": f"Allocation has not been verified in {unused_threshold_days} days.",
                })
                findings.append(fnd)

    # --------------------------------------------------------------------------
    # 4. Unlicensed or Prohibited Software Installations
    # --------------------------------------------------------------------------
    inst_qs = SoftwareInstallation.objects.filter(status="installed").select_related("software_product", "asset", "allocation")
    if software_product:
        inst_qs = inst_qs.filter(software_product=software_product)
    if asset:
        inst_qs = inst_qs.filter(asset=asset)

    for inst in inst_qs:
        prod = inst.software_product
        if prod.approved_status == "prohibited":
            fp = compute_finding_fingerprint("prohibited_software", installation_id=inst.pk, product_id=prod.pk, asset_id=inst.asset_id)
            fnd = _upsert_finding(fp, {
                "finding_type": "prohibited_software",
                "severity": "critical",
                "installation": inst,
                "software_product": prod,
                "asset": inst.asset,
                "status": "open",
                "title": f"Prohibited software detected: {prod.name} on {inst.asset.asset_tag}",
                "description": f"Product '{prod.name}' is flagged as prohibited but installed on asset {inst.asset.asset_tag}.",
            })
            findings.append(fnd)
        elif prod.license_required and not inst.allocation_id:
            fp = compute_finding_fingerprint("unlicensed_installation", installation_id=inst.pk, product_id=prod.pk, asset_id=inst.asset_id)
            fnd = _upsert_finding(fp, {
                "finding_type": "unlicensed_installation",
                "severity": "high",
                "installation": inst,
                "software_product": prod,
                "asset": inst.asset,
                "status": "open",
                "title": f"Unlicensed installation: {prod.name} on {inst.asset.asset_tag}",
                "description": f"Software '{prod.name}' requires a license but has no active license allocation assigned.",
            })
            findings.append(fnd)

    # --------------------------------------------------------------------------
    # 5. Resolve findings whose underlying condition no longer exists
    # --------------------------------------------------------------------------
    auto_resolvable_types = (
        "over_allocated",
        "expired_agreement",
        "expiring_agreement",
        "missing_documentation",
        "missing_entitlement_quantity",
        "allocation_to_inactive_user",
        "allocation_to_retired_asset",
        "unused_license",
        "unlicensed_installation",
        "prohibited_software",
        "terminated_agreement_allocation",
        "expired_agreement_allocation",
    )
    stale_qs = LicenseComplianceFinding.objects.filter(
        status__in=("open", "acknowledged"),
        finding_type__in=auto_resolvable_types,
    )
    if agreement:
        stale_qs = stale_qs.filter(agreement=agreement)
    if software_product:
        stale_qs = stale_qs.filter(software_product=software_product)
    if asset:
        stale_qs = stale_qs.filter(asset=asset)
    if user:
        stale_qs = stale_qs.filter(user=user)

    for stale in stale_qs:
        if not finding_condition_persists(stale):
            stale.status = "resolved"
            stale.resolved_at = timezone.now()
            stale.resolved_by = actor if getattr(actor, "pk", None) else None
            stale.resolution_note = _append_auto_resolution_note(stale.resolution_note)
            stale.save(update_fields=[
                "status", "resolved_at", "resolved_by", "resolution_note", "updated_at",
            ])

    return findings


def finding_condition_persists(finding: LicenseComplianceFinding) -> bool:
    """Determine whether the underlying condition for a finding still exists."""
    if finding.finding_type == "expired_agreement" and finding.agreement_id:
        agr = finding.agreement
        today = timezone.now().date()
        return bool(agr and agr.expiry_date and agr.expiry_date < today and agr.status not in ("terminated", "retired"))
    if finding.finding_type == "expiring_agreement" and finding.agreement_id:
        agr = finding.agreement
        today = timezone.now().date()
        return bool(agr and agr.renewal_date and today >= agr.renewal_date and agr.expiry_date >= today)
    if finding.finding_type == "over_allocated" and finding.agreement_id:
        agr = finding.agreement
        if not agr or agr.is_unlimited:
            return False
        limit = get_agreement_entitlement_limit(agr)
        consuming = agr.allocations.filter(
            status__in=CONSUMING_ALLOCATION_STATUSES
        ).count()
        return bool(limit is not None and consuming > limit)
    if finding.finding_type == "allocation_to_inactive_user" and finding.allocation_id:
        alloc = finding.allocation
        user = alloc.assigned_user if alloc else None
        return bool(alloc and alloc.status in CONSUMING_ALLOCATION_STATUSES and user and (not user.is_active or getattr(user, "is_deleted", False)))
    if finding.finding_type == "allocation_to_retired_asset" and finding.allocation_id:
        alloc = finding.allocation
        asset = alloc.assigned_asset if alloc else None
        return bool(alloc and alloc.status in CONSUMING_ALLOCATION_STATUSES and asset and (asset.status in ("retired", "lost", "disposed") or getattr(asset, "is_deleted", False)))
    if finding.finding_type == "missing_documentation" and finding.agreement_id:
        agr = finding.agreement
        if not agr:
            return False
        if not agr.start_date or not agr.expiry_date:
            return True
        if not agr.is_unlimited and (not agr.quantity_purchased or agr.quantity_purchased <= 0):
            return True
        return False
    if finding.finding_type == "unused_license" and finding.allocation_id:
        alloc = finding.allocation
        if not alloc or alloc.status not in CONSUMING_ALLOCATION_STATUSES:
            return False
        unused_threshold_days = getattr(settings, "LICENSE_UNUSED_DAYS", 90)
        cutoff = timezone.now() - timezone.timedelta(days=unused_threshold_days)
        check_date = alloc.last_verified_at or alloc.assigned_at
        return bool(check_date and check_date < cutoff)
    if finding.finding_type == "unlicensed_installation" and finding.installation_id:
        inst = finding.installation
        return bool(inst and inst.status == "installed" and inst.software_product.license_required and not inst.allocation_id)
    if finding.finding_type == "prohibited_software" and finding.installation_id:
        inst = finding.installation
        return bool(inst and inst.status == "installed" and inst.software_product.approved_status == "prohibited")
    if finding.finding_type == "missing_entitlement_quantity" and finding.agreement_id:
        agr = finding.agreement
        if not agr or agr.is_unlimited:
            return False
        limit = get_agreement_entitlement_limit(agr)
        return not limit or limit <= 0
    if finding.finding_type == "terminated_agreement_allocation" and finding.allocation_id:
        alloc = finding.allocation
        return bool(
            alloc
            and alloc.status in CONSUMING_ALLOCATION_STATUSES
            and alloc.agreement.status == "terminated"
        )
    if finding.finding_type == "expired_agreement_allocation" and finding.allocation_id:
        alloc = finding.allocation
        agr = alloc.agreement if alloc else None
        today = timezone.now().date()
        return bool(
            alloc
            and alloc.status in CONSUMING_ALLOCATION_STATUSES
            and agr
            and agr.expiry_date
            and agr.expiry_date < today
            and agr.status not in ("terminated", "retired")
        )
    return False


@transaction.atomic
def remediate_compliance_finding(
    finding: LicenseComplianceFinding,
    actor,
    remediation_note: str,
    reevaluate: bool = False,
) -> LicenseComplianceFinding:
    """Record a remediation action without forcing resolution."""
    if not is_it_manager(actor):
        raise ValidationError("Only IT Managers or System Admins can record remediation actions.")
    if not remediation_note or not remediation_note.strip():
        raise ValidationError("A remediation note is required.")

    locked = LicenseComplianceFinding.objects.select_for_update().get(pk=finding.pk)
    now = timezone.now()
    note = f"[{now:%Y-%m-%d %H:%M} {getattr(actor, 'email', actor)}] {remediation_note.strip()}"
    # Remediation history lives in its own field: resolution_note is reserved for
    # resolution metadata and is appended to by automatic re-evaluation.
    locked.remediation_note = f"{locked.remediation_note}\n{note}".strip() if locked.remediation_note else note
    if locked.status == "open":
        locked.status = "acknowledged"
    locked.save(update_fields=["status", "remediation_note", "updated_at"])

    record_license_history(
        event_type="compliance_changed",
        actor=actor,
        agreement=locked.agreement,
        allocation=locked.allocation,
        installation=locked.installation,
        detail={"finding_id": locked.pk, "action": "remediation_recorded", "note": remediation_note.strip()},
    )

    if reevaluate:
        evaluate_license_compliance(
            software_product=locked.software_product,
            agreement=locked.agreement,
            asset=locked.asset,
            user=locked.user,
            actor=actor,
        )
        locked.refresh_from_db()

    return locked


@transaction.atomic
def resolve_compliance_finding(
    finding: LicenseComplianceFinding,
    actor,
    resolution_note: str,
    is_false_positive: bool = False,
) -> LicenseComplianceFinding:
    """Acknowledge or resolve a compliance finding. Reason mandatory."""
    if not is_it_manager(actor):
        raise ValidationError("Only IT Managers or System Admins can resolve compliance findings.")

    if not resolution_note or not resolution_note.strip():
        raise ValidationError("A resolution note is required.")

    if not is_false_positive and finding_condition_persists(finding):
        raise ValidationError("Cannot resolve finding while the underlying condition still exists.")

    finding.status = "false_positive" if is_false_positive else "resolved"
    finding.resolved_at = timezone.now()
    finding.resolved_by = actor
    finding.resolution_note = resolution_note.strip()
    finding.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_note", "updated_at"])

    log_action(
        actor=actor,
        action="update",
        instance=finding,
        reason=resolution_note.strip(),
        details={"status": finding.status},
    )

    return finding


# ==============================================================================
# INTEGRATION SERVICES
# ==============================================================================

def allocate_from_service_request(
    service_request,
    agreement: LicenseAgreement,
    actor,
) -> LicenseAllocation:
    """Fulfill an approved Service Request by creating a linked license allocation.

    Idempotent: Re-entrant calls return the existing allocation.
    """
    # Check existing allocation for this service request
    existing = LicenseAllocation.objects.filter(
        service_request=service_request,
        agreement=agreement,
        status__in=["assigned", "active"],
    ).first()
    if existing:
        return existing

    requester = getattr(service_request, "requester", None)
    if not requester or not requester.is_active or getattr(requester, "is_deleted", False):
        raise ValidationError("Service Request requester must be an active employee.")

    allocation = allocate_license(
        agreement=agreement,
        allocation_type="user",
        assigned_user=requester,
        actor=actor,
        notes=f"Allocated via Service Request {service_request.request_number}",
        service_request=service_request,
    )

    return allocation


def get_active_allocations_for_user(user) -> List[LicenseAllocation]:
    """Retrieve all active or reserved allocations associated with an employee.

    Includes named user seats and device seats tied to assets assigned to the user.
    """
    if not user or not getattr(user, "pk", None):
        return []

    return list(
        LicenseAllocation.objects.filter(
            Q(assigned_user=user) | Q(assigned_asset__assigned_to=user),
            status__in=["assigned", "active", "reserved"],
        ).select_related("agreement__software_product", "assigned_asset")
    )


@transaction.atomic
def revoke_allocations_for_offboarding(
    user,
    actor,
    reason: str,
    lifecycle_case=None,
) -> Dict[str, Any]:
    """Reclaim all software licenses during employee offboarding.

    Gracefully links to optional lifecycle_case without hard dependencies.
    """
    if not reason or not reason.strip():
        reason = f"Employee offboarding for {user.email}"

    allocations = get_active_allocations_for_user(user)
    revoked_count = 0
    results = []

    for alloc in allocations:
        try:
            revoke_allocation(alloc, actor=actor, reason=reason)
            revoked_count += 1
            results.append({
                "allocation_id": alloc.pk,
                "product": alloc.agreement.software_product.name,
                "reference": alloc.allocation_reference,
                "success": True,
            })
        except Exception as exc:
            results.append({
                "allocation_id": alloc.pk,
                "product": alloc.agreement.software_product.name,
                "reference": alloc.allocation_reference,
                "success": False,
                "error": str(exc),
            })

    log_action(
        actor=actor,
        action="assignment",
        instance=user,
        reason=reason,
        details={"revoked_license_count": revoked_count, "results": results},
    )

    return {
        "user_id": user.pk,
        "revoked_count": revoked_count,
        "total_active": len(allocations),
        "results": results,
    }


# ==============================================================================
# APPROVAL CENTER PROVIDER HOOK
# ==============================================================================



@transaction.atomic
def activate_allocation(
    allocation: LicenseAllocation,
    actor,
    reason: str = "",
) -> LicenseAllocation:
    """Activate an assigned, reserved, or suspended license allocation.

    Reactivation from ``suspended`` increases entitlement consumption, so the
    agreement row is locked and capacity is checked before the status change.
    Activation from ``assigned``/``reserved`` does not increase consumption
    because those statuses already consume entitlement.
    """
    reason = (reason or "").strip() or "Activation reinstated"

    # Lock order is agreement -> allocation everywhere allocation state changes.
    agreement = LicenseAgreement.objects.select_for_update().get(
        pk=allocation.agreement_id
    )

    locked_alloc = (
        LicenseAllocation.objects.select_for_update()
        .get(pk=allocation.pk)
    )

    if locked_alloc.status == "active":
        raise ValidationError("Allocation is already active.")

    if locked_alloc.status == "revoked":
        raise ValidationError("Cannot activate a revoked allocation.")

    if locked_alloc.status not in ("assigned", "reserved", "suspended"):
        raise ValidationError(
            f"Cannot activate allocation in '{locked_alloc.status}' status."
        )

    if agreement.status not in ("active", "expiring"):
        raise ValidationError(
            f"Cannot activate allocation on agreement in '{agreement.status}' status "
            f"(must be active or expiring)."
        )

    if agreement.expiry_date and agreement.expiry_date < timezone.now().date():
        raise ValidationError(
            f"Cannot activate allocation on expired agreement {agreement.agreement_number} "
            f"(expired {agreement.expiry_date})."
        )

    previous_status = locked_alloc.status
    increases_consumption = previous_status not in CONSUMING_ALLOCATION_STATUSES

    if increases_consumption and not agreement.is_unlimited:
        capacity_limit = get_agreement_entitlement_limit(agreement)
        consuming_count = agreement.allocations.filter(
            status__in=CONSUMING_ALLOCATION_STATUSES
        ).count()
        if capacity_limit is not None and consuming_count + 1 > capacity_limit:
            raise ValidationError(
                f"Agreement {agreement.agreement_number} has reached maximum capacity "
                f"({consuming_count + 1}/{capacity_limit} allocations would be consuming). "
                f"Cannot reactivate: entitlement would be exceeded."
            )

    now = timezone.now()
    locked_alloc.status = "active"
    locked_alloc.activated_at = now
    locked_alloc.activation_confirmed_by = actor if getattr(actor, "pk", None) else None
    locked_alloc.last_verified_at = now
    locked_alloc.last_verified_by = actor if getattr(actor, "pk", None) else None
    locked_alloc.version += 1
    locked_alloc.save(update_fields=[
        "status", "activated_at", "activation_confirmed_by",
        "last_verified_at", "last_verified_by", "version", "updated_at",
    ])

    agreement.recalculate_counters(save=True)
    evaluate_license_compliance(agreement=agreement, actor=actor)

    record_license_history(
        event_type="allocation_activated",
        actor=actor,
        agreement=agreement,
        allocation=locked_alloc,
        previous_status=previous_status,
        new_status="active",
        detail={"reason": reason},
    )

    log_action(
        actor=actor,
        action="assignment",
        instance=locked_alloc,
        reason=reason,
        details={"status": "active", "previous_status": previous_status},
    )

    return locked_alloc


@transaction.atomic
def suspend_allocation(allocation: LicenseAllocation, actor, reason: str = "") -> LicenseAllocation:
    """Suspend a consuming allocation and restore its capacity."""
    reason = (reason or "").strip() or "Allocation suspended"

    # Lock order is agreement -> allocation everywhere allocation state changes.
    agreement = LicenseAgreement.objects.select_for_update().get(
        pk=allocation.agreement_id
    )

    locked_alloc = (
        LicenseAllocation.objects.select_for_update()
        .get(pk=allocation.pk)
    )

    if locked_alloc.status == "suspended":
        raise ValidationError("Allocation is already suspended.")

    if locked_alloc.status == "revoked":
        raise ValidationError("Cannot suspend a revoked allocation.")

    if locked_alloc.status not in CONSUMING_ALLOCATION_STATUSES:
        raise ValidationError(
            f"Cannot suspend allocation in '{locked_alloc.status}' status."
        )

    previous_status = locked_alloc.status

    locked_alloc.status = "suspended"
    locked_alloc.version += 1
    locked_alloc.save(update_fields=["status", "version", "updated_at"])

    agreement.recalculate_counters(save=True)
    evaluate_license_compliance(agreement=agreement, actor=actor)

    record_license_history(
        event_type="allocation_suspended",
        actor=actor,
        agreement=agreement,
        allocation=locked_alloc,
        previous_status=previous_status,
        new_status="suspended",
        detail={"reason": reason},
    )

    log_action(
        actor=actor,
        action="assignment",
        instance=locked_alloc,
        reason=reason,
        details={"status": "suspended", "previous_status": previous_status},
    )

    return locked_alloc


class LicenseRenewalApprovalProvider:
    """Approval Center integration provider for pending license renewals."""

    key = "license_renewal"
    label = "License Renewal"
    base_path = "/api/licensing/renewals/"

    def get_queryset(self, user):
        if not user or not user.is_authenticated or not is_it_manager(user):
            return LicenseRenewal.objects.none()
        return LicenseRenewal.objects.filter(status="pending_review").select_related("agreement__software_product", "requested_by")

    def can_view(self, user):
        return is_it_manager(user)

    def can_approve(self, user, item: LicenseRenewal) -> bool:
        if not user or not user.is_authenticated:
            return False
        # Separation of duties: requester cannot approve
        if item.requested_by_id == user.pk:
            return False
        threshold = get_renewal_admin_threshold()
        configured_currency = getattr(settings, "LICENSE_THRESHOLD_CURRENCY", "USD")
        if item.currency != configured_currency or item.proposed_total_cost >= threshold:
            return is_system_admin(user)
        return is_it_manager(user)

    def can_reject(self, user, item: LicenseRenewal) -> bool:
        if not user or not user.is_authenticated:
            return False
        if item.requested_by_id == user.pk:
            return False
        return is_it_manager(user)

    def serialize(self, item: LicenseRenewal, user) -> Dict[str, Any]:
        return {
            "id": item.pk,
            "provider": self.key,
            "label": f"Renewal: {item.agreement.agreement_number} ({item.agreement.software_product.name})",
            "requested_by": item.requested_by.email if item.requested_by else None,
            "requested_at": item.requested_at.isoformat() if item.requested_at else None,
            "proposed_total_cost": str(item.proposed_total_cost),
            "currency": item.currency,
            "can_approve": self.can_approve(user, item),
            "can_reject": self.can_reject(user, item),
        }
