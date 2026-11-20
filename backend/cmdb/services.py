"""CMDB domain services: integrations (asset/software sync), verification,
retirement and relationship lifecycle.

All decision points run inside transactions and are concurrency-safe:
optimistic record_version checks raise StaleVersionError; unique-constraint
races are retried or converted to idempotent updates.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from common.audit import log_action

from .impact import analyze_ci_impact
from .models import (
    HIERARCHY_PARENT_DIRECTION,
    ConfigurationItem,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemType,
    validate_relationship,
)

# Retiring a CI deactivates its active relationships (explicit policy).
RETIRE_DEACTIVATES_RELATIONSHIPS = True

ASSET_STATUS_TO_CI_STATUS = {
    "assigned": "active",
    "available": "planned",
    "in_repair": "maintenance",
    "retired": "retired",
    "lost": "unknown",
    "disposed": "disposed",
}

ASSET_CATEGORY_RULES = (
    ("server", "Server", "SERVER", "hardware"),
    ("laptop", "Laptop", "LAPTOP", "hardware"),
    ("desktop", "Workstation", "WORKSTATION", "hardware"),
    ("workstation", "Workstation", "WORKSTATION", "hardware"),
    ("network", "Network Device", "NETWORK_DEVICE", "network"),
    ("switch", "Network Device", "NETWORK_DEVICE", "network"),
    ("router", "Network Device", "NETWORK_DEVICE", "network"),
    ("firewall", "Network Device", "NETWORK_DEVICE", "network"),
    ("printer", "Printer", "PRINTER", "hardware"),
    ("scanner", "Printer", "PRINTER", "hardware"),
    ("storage", "Storage Device", "STORAGE_DEVICE", "hardware"),
    ("san", "Storage Device", "STORAGE_DEVICE", "hardware"),
    ("nas", "Storage Device", "STORAGE_DEVICE", "hardware"),
    ("database", "Database", "DATABASE", "database"),
    ("application", "Business Application", "BUSINESS_APPLICATION", "application"),
    ("license", "Software Product", "SOFTWARE_PRODUCT", "software"),
    ("software", "Software Product", "SOFTWARE_PRODUCT", "software"),
)


class StaleVersionError(Exception):
    """record_version in the request does not match the stored record."""


class ImpactRequiredError(Exception):
    """Retirement blocked until the caller acknowledges impact."""

    def __init__(self, impact):
        super().__init__("impact acknowledgement required")
        self.impact = impact


class AssetAssignedError(Exception):
    """Linked asset is assigned to a user; retirement blocked."""


def record_history(ci, actor, event_type, *, detail="", source="manual",
                   previous_status="", new_status="", changed_fields=None,
                   relationship=None):
    return ConfigurationItemHistory.objects.create(
        configuration_item=ci,
        relationship=relationship,
        actor=actor,
        event_type=event_type,
        previous_status=previous_status or "",
        new_status=new_status or "",
        changed_fields=changed_fields or {},
        detail=detail,
        source=source,
    )


def _check_version(ci, expected_record_version):
    if expected_record_version is None:
        return
    if int(expected_record_version) != ci.record_version:
        raise StaleVersionError(
            f"expected record_version {expected_record_version}, "
            f"found {ci.record_version}"
        )


# ---------------------------------------------------------------------------
# Asset / software integration
# ---------------------------------------------------------------------------

def _type_for_asset(asset):
    category = getattr(asset, "category", None)
    name = (getattr(category, "name", "") or "").lower()
    for needle, type_name, code, category_name in ASSET_CATEGORY_RULES:
        if needle in name:
            return type_name, code, category_name
    return "Workstation", "WORKSTATION", "hardware"


def _resolve_type(type_name, code, category):
    ctype = (
        ConfigurationItemType.objects.filter(code=code).first()
        or ConfigurationItemType.objects.filter(name=type_name).first()
    )
    if ctype is None:
        ctype = ConfigurationItemType.objects.create(
            name=type_name, code=code, category=category,
            is_system=False,
        )
    return ctype


def sync_asset_to_ci(asset, actor=None, create_missing=True,
                     update_existing=True):
    """Idempotent asset -> CI synchronization.

    Manual CIs are preserved untouched (their fields are operator-owned);
    asset-sourced CIs are refreshed from the asset record.

    Returns (ci_or_None, created_bool).
    """
    if asset is None or getattr(asset, "is_deleted", False):
        return None, False

    if asset is None or getattr(asset, "is_deleted", False):
        return None, False

    ci = ConfigurationItem.objects.filter(asset=asset, is_deleted=False).first()

    if ci is None:
        if not create_missing:
            return None, False
        type_name, code, category_name = _type_for_asset(asset)
        ctype = _resolve_type(type_name, code, category_name)
        status = ASSET_STATUS_TO_CI_STATUS.get(
            getattr(asset, "status", ""), "planned",
        )
        try:
            with transaction.atomic():
                ci = ConfigurationItem.objects.create(
                    name=getattr(asset, "name", "") or asset.asset_tag,
                    ci_type=ctype,
                    asset=asset,
                    department=getattr(asset, "department", None),
                    vendor=getattr(asset, "vendor", None),
                    serial_number=getattr(asset, "serial_number", "") or "",
                    location=getattr(asset, "location", "") or "",
                    status=status,
                    source="asset_sync",
                    source_identifier=asset.asset_tag,
                    last_discovered_at=timezone.now(),
                    created_by=actor,
                )
        except IntegrityError:
            # Race: another writer linked this asset first -> update path.
            ci = ConfigurationItem.objects.filter(
                asset=asset, is_deleted=False,
            ).first()
            if ci is None:
                raise
        else:
            record_history(
                ci, actor, "created", source="asset_sync",
                detail=f"Created from asset {asset.asset_tag}",
            )
            return ci, True

    if not update_existing:
        return ci, False
    if ci.source != "asset_sync":
        # Manual CI: operator-owned fields are preserved.
        return ci, False

    mapped_status = ASSET_STATUS_TO_CI_STATUS.get(
        getattr(asset, "status", ""), None,
    )
    candidates = {
        "name": getattr(asset, "name", "") or ci.name,
        "department": getattr(asset, "department", None),
        "vendor": getattr(asset, "vendor", None),
        "serial_number": getattr(asset, "serial_number", "") or "",
        "location": getattr(asset, "location", "") or "",
        "status": mapped_status,
    }
    changed = {}
    for field, value in candidates.items():
        if value is None and field in ("department", "vendor"):
            continue  # never null out ownership links from sync
        if value is not None and getattr(ci, field, None) != value:
            if field == "status" and value in ("retired", "disposed"):
                # never silently retire CIs from asset status alone
                continue
            changed[field] = value

    if changed:
        previous_status = ci.status
        for field, value in changed.items():
            setattr(ci, field, value)
        ci.record_version = (ci.record_version or 1) + 1
        update_fields = list(changed) + ["record_version", "updated_at"]
        ci.save(update_fields=update_fields)
        record_history(
            ci, actor, "synchronized", source="asset_sync",
            previous_status=previous_status, new_status=ci.status,
            changed_fields={k: str(v) for k, v in changed.items()},
            detail=f"Synced from asset {asset.asset_tag}",
        )
    else:
        ci.last_discovered_at = timezone.now()
        ci.save(update_fields=["last_discovered_at", "updated_at"])
    return ci, False


def _status_for_product(product):
    approved = getattr(product, "approved_status", "") or ""
    if approved == "retired":
        return "retired"
    if approved == "prohibited" or not getattr(product, "is_active", True):
        return "inactive"
    return "active"


def sync_software_product_to_ci(product, actor=None, create_missing=True,
                                update_existing=True):
    """Idempotent SoftwareProduct -> CI synchronization."""
    if product is None or getattr(product, "is_deleted", False):
        return None, False

    ci = ConfigurationItem.objects.filter(
        software_product=product, is_deleted=False,
    ).first()

    if ci is None:
        if not create_missing:
            return None, False
        ctype = _resolve_type(
            "Software Product", "SOFTWARE_PRODUCT", "software",
        )
        try:
            with transaction.atomic():
                ci = ConfigurationItem.objects.create(
                    name=product.name,
                    ci_type=ctype,
                    software_product=product,
                    version=getattr(product, "version", "") or "",
                    status=_status_for_product(product),
                    source="licensing_sync",
                    source_identifier=getattr(product, "code", "") or "",
                    last_discovered_at=timezone.now(),
                    created_by=actor,
                )
        except IntegrityError:
            ci = ConfigurationItem.objects.filter(
                software_product=product, is_deleted=False,
            ).first()
            if ci is None:
                raise
        else:
            record_history(
                ci, actor, "created", source="licensing_sync",
                detail=f"Created from software product {product.name}",
            )
            return ci, True

    if not update_existing:
        return ci, False
    if ci.source != "licensing_sync":
        return ci, False

    mapped_status = _status_for_product(product)
    candidates = {
        "name": product.name,
        "version": getattr(product, "version", "") or "",
        "status": mapped_status,
    }
    changed = {}
    for field, value in candidates.items():
        if getattr(ci, field, None) != value:
            if field == "status" and value == "retired":
                continue
            changed[field] = value
    if changed:
        previous_status = ci.status
        for field, value in changed.items():
            setattr(ci, field, value)
        ci.record_version = (ci.record_version or 1) + 1
        ci.save(update_fields=list(changed) + ["record_version", "updated_at"])
        record_history(
            ci, actor, "synchronized", source="licensing_sync",
            previous_status=previous_status, new_status=ci.status,
            changed_fields={k: str(v) for k, v in changed.items()},
            detail=f"Synced from software product {product.name}",
        )
    return ci, False


# ---------------------------------------------------------------------------
# Verification / retirement
# ---------------------------------------------------------------------------

def verify_ci(ci, actor, note="", expected_record_version=None):
    """Mark a CI verified (optimistic concurrency checked)."""
    with transaction.atomic():
        locked = ConfigurationItem.objects.select_for_update().get(pk=ci.pk)
        _check_version(locked, expected_record_version)
        locked.last_verified_at = timezone.now()
        locked.verified_by = actor
        locked.record_version = (locked.record_version or 1) + 1
        locked.save(update_fields=[
            "last_verified_at", "verified_by", "record_version", "updated_at",
        ])
        record_history(
            locked, actor, "verified", detail=note or "verified",
            source="manual",
        )
        # Verification closes any outstanding unverified findings
        from .models import ConfigurationDriftFinding

        ConfigurationDriftFinding.objects.filter(
            configuration_item=locked, is_deleted=False,
            finding_type="unverified_ci", status__in=("open", "acknowledged"),
        ).update(
            status="resolved", resolved_at=timezone.now(), resolved_by=actor,
            resolution_note="Verified",
        )
        log_action(
            actor=actor, action="update", instance=locked,
            reason="configuration item verified",
            details={"ci_number": locked.ci_number},
        )
        ci.refresh_from_db()
    return ci


def retirement_impact(ci, max_depth=5):
    """Impact payload used to gate retirement."""
    return analyze_ci_impact(ci, proposed_status="retired", max_depth=max_depth)


def retire_ci(ci, actor, reason, expected_record_version=None,
              acknowledge_impact=False, retirement_date=None):
    """Retire a CI with impact gating, asset checks and relationship policy.

    Returns the retired CI. Raises StaleVersionError, AssetAssignedError or
    ImpactRequiredError (carrying the impact payload) on refusal.
    """
    if not reason or not str(reason).strip():
        raise ValueError("reason is required")

    with transaction.atomic():
        locked = ConfigurationItem.objects.select_for_update().get(pk=ci.pk)
        _check_version(locked, expected_record_version)

        if locked.status in ("retired", "disposed"):
            raise ValueError("CI is already retired")

        if locked.asset_id:
            from assets.models import Asset

            asset = Asset.objects.filter(pk=locked.asset_id).first()
            if asset and asset.status == "assigned":
                raise AssetAssignedError(
                    "linked asset is assigned to a user; unassign it first"
                )

        impact = retirement_impact(locked)
        blocking = (
            impact["affected_count"] > 0
            or bool(impact["affected_services"])
            or bool(impact["single_points_of_failure"])
        )
        if blocking and not acknowledge_impact:
            raise ImpactRequiredError(impact)

        previous_status = locked.status
        locked.status = "retired"
        locked.lifecycle_state = "retired"
        locked.record_version = (locked.record_version or 1) + 1
        detail = str(reason).strip()
        if retirement_date:
            detail = f"{detail} (retirement date: {retirement_date})"
        locked.save(update_fields=[
            "status", "lifecycle_state", "record_version", "updated_at",
        ])

        deactivated = 0
        if RETIRE_DEACTIVATES_RELATIONSHIPS:
            active_rels = ConfigurationItemRelationship.objects.filter(
                is_deleted=False, status="active",
            ).filter(
                source_ci=locked,
            ) | ConfigurationItemRelationship.objects.filter(
                is_deleted=False, status="active",
            ).filter(target_ci=locked)
            for rel in active_rels.select_for_update():
                rel.status = "inactive"
                rel.save(update_fields=["status", "updated_at"])
                ConfigurationItemHistory.objects.create(
                    relationship=rel,
                    actor=actor,
                    event_type="relationship_deactivated",
                    detail=f"Deactivated on retirement of {locked.ci_number}",
                    source="manual",
                )
                deactivated += 1

        record_history(
            locked, actor, "retired",
            previous_status=previous_status, new_status="retired",
            detail=detail, source="manual",
        )
        log_action(
            actor=actor, action="retire", instance=locked, reason=detail,
            details={
                "ci_number": locked.ci_number,
                "affected_count": impact["affected_count"],
                "relationships_deactivated": deactivated,
            },
        )
        ci.refresh_from_db()
    return ci, impact


def replace_ci(ci, replacement_ci, actor):
    """Link a replacement CI to the retired one (replaces relationship)."""
    if not replacement_ci or replacement_ci.id == ci.id:
        return None
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        validate_relationship(replacement_ci, ci, "replaces", status="active")
    except DjangoValidationError:
        return None
    rel = ConfigurationItemRelationship.objects.create(
        source_ci=replacement_ci,
        target_ci=ci,
        relationship_type="replaces",
        status="active",
        created_by=actor,
    )
    record_history(
        ci, actor, "replacement_linked",
        detail=f"Replaced by {replacement_ci.ci_number}",
        relationship=rel, source="manual",
    )
    return rel


# ---------------------------------------------------------------------------
# Relationship lifecycle
# ---------------------------------------------------------------------------


HIERARCHY_MUTATION_LOCK_KEY = 0x434D4248


def _serialize_hierarchy_mutations():
    """Serialize hierarchy mutations across processes/connections.

    select_for_update() on existing relationship rows cannot prevent two
    concurrent transactions from inserting new (phantom) edges.  On PostgreSQL
    a transaction-scoped advisory lock provides a stable, deterministic
    serialization point without adding infrastructure.
    """
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [HIERARCHY_MUTATION_LOCK_KEY],
            )


def create_relationship(source_ci, target_ci, relationship_type, *,
                        status="active", actor=None, description="",
                        confidence="confirmed", source="manual",
                        discovered=False):
    """Validated relationship creation with history."""
    with transaction.atomic():
        if relationship_type in HIERARCHY_PARENT_DIRECTION:
            _serialize_hierarchy_mutations()
            ConfigurationItemRelationship.objects.select_for_update().filter(
                is_deleted=False,
                relationship_type__in=tuple(HIERARCHY_PARENT_DIRECTION),
            ).count()
        validate_relationship(source_ci, target_ci, relationship_type, status=status)
        try:
            rel = ConfigurationItemRelationship.objects.create(
                source_ci=source_ci,
                target_ci=target_ci,
                relationship_type=relationship_type,
                status=status,
                description=description or "",
                confidence=confidence,
                source=source,
                discovered=discovered,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise ValueError("Duplicate relationship.") from exc
        ConfigurationItemHistory.objects.create(
            configuration_item=source_ci,
            relationship=rel,
            actor=actor,
            event_type="relationship_created",
            new_status=status,
            detail=f"{relationship_type} -> {target_ci.ci_number}",
            source=source,
        )
    return rel


def activate_relationship(rel, actor):
    with transaction.atomic():
        locked = ConfigurationItemRelationship.objects.select_for_update().get(
            pk=rel.pk,
        )
        if locked.status == "active":
            return locked
        previous = locked.status
        if locked.relationship_type in HIERARCHY_PARENT_DIRECTION:
            _serialize_hierarchy_mutations()
            ConfigurationItemRelationship.objects.select_for_update().filter(
                is_deleted=False,
                relationship_type__in=tuple(HIERARCHY_PARENT_DIRECTION),
            ).count()
        # activation must not duplicate an existing inverse or create cycles
        validate_relationship(
            locked.source_ci, locked.target_ci,
            locked.relationship_type, status="active",
        )
        locked.status = "active"
        locked.save(update_fields=["status", "updated_at"])
        ConfigurationItemHistory.objects.create(
            configuration_item=locked.source_ci,
            relationship=locked,
            actor=actor,
            event_type="relationship_activated",
            previous_status=previous,
            new_status="active",
            detail=f"{locked.relationship_type} -> {locked.target_ci.ci_number}",
            source="manual",
        )
        rel.refresh_from_db()
    return rel


def deactivate_relationship(rel, actor):
    with transaction.atomic():
        locked = ConfigurationItemRelationship.objects.select_for_update().get(
            pk=rel.pk,
        )
        if locked.status == "inactive":
            return locked
        previous = locked.status
        locked.status = "inactive"
        locked.save(update_fields=["status", "updated_at"])
        ConfigurationItemHistory.objects.create(
            configuration_item=locked.source_ci,
            relationship=locked,
            actor=actor,
            event_type="relationship_deactivated",
            previous_status=previous,
            new_status="inactive",
            detail=f"{locked.relationship_type} -> {locked.target_ci.ci_number}",
            source="manual",
        )
        rel.refresh_from_db()
    return rel


def confirm_relationship(rel, actor):
    """Confirm a proposed relationship (stays active-equivalent)."""
    with transaction.atomic():
        locked = ConfigurationItemRelationship.objects.select_for_update().get(
            pk=rel.pk,
        )
        if locked.status not in ("proposed", "inactive"):
            return locked
        previous = locked.status
        if locked.relationship_type in HIERARCHY_PARENT_DIRECTION:
            _serialize_hierarchy_mutations()
            ConfigurationItemRelationship.objects.select_for_update().filter(
                is_deleted=False,
                relationship_type__in=tuple(HIERARCHY_PARENT_DIRECTION),
            ).count()
        validate_relationship(
            locked.source_ci, locked.target_ci,
            locked.relationship_type, status="active",
        )
        locked.status = "active"
        locked.confidence = "confirmed"
        locked.save(update_fields=["status", "confidence", "updated_at"])
        ConfigurationItemHistory.objects.create(
            configuration_item=locked.source_ci,
            relationship=locked,
            actor=actor,
            event_type="relationship_confirmed",
            previous_status=previous,
            new_status="active",
            detail=f"{locked.relationship_type} -> {locked.target_ci.ci_number}",
            source="manual",
        )
        rel.refresh_from_db()
    return rel
