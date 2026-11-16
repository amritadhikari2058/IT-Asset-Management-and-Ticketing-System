from django.db import transaction
from django.utils import timezone
from .models import ConfigurationItem, ConfigurationItemHistory, ConfigurationItemType, ConfigurationBaseline, ConfigurationDriftFinding

def _type_for_asset(asset):
    name = (getattr(asset, "category", None) and getattr(asset.category, "name", "")) or ""
    low = name.lower()
    if "server" in low: return "Server"
    if "laptop" in low: return "Laptop"
    if "network" in low: return "Network Device"
    if "printer" in low: return "Printer"
    return "Workstation"

def sync_asset_to_ci(asset, actor=None, create_missing=True, update_existing=True):
    ci = ConfigurationItem.objects.filter(asset=asset, is_deleted=False).first()
    created = False
    if ci is None:
        if not create_missing:
            return None, False
        ctype_name = _type_for_asset(asset)
        ctype = ConfigurationItemType.objects.filter(name=ctype_name, is_deleted=False).first() or ConfigurationItemType.objects.filter(is_deleted=False).first()
        if ctype is None:
            ctype = ConfigurationItemType.objects.create(name=ctype_name, code=ctype_name.upper().replace(" ","_"), category="hardware", is_system=False)
        ci = ConfigurationItem.objects.create(
            name=getattr(asset, "name", "") or getattr(asset, "asset_tag", ""),
            ci_type=ctype,
            asset=asset,
            department=getattr(asset, "department", None),
            vendor=getattr(asset, "vendor", None),
            manufacturer=getattr(asset, "manufacturer", "") if hasattr(asset,"manufacturer") else "",
            model=getattr(asset, "model", "") if hasattr(asset,"model") else "",
            serial_number=getattr(asset, "serial_number", "") if hasattr(asset,"serial_number") else "",
            status="active" if getattr(asset, "status", "") in ("active", "in_service", "deployed") else "planned",
            source="asset_sync",
            created_by=actor,
        )
        created = True
        ConfigurationItemHistory.objects.create(configuration_item=ci, actor=actor, event_type="created", source="asset_sync")
    else:
        if update_existing:
            ci.name = getattr(asset, "name", "") or ci.name
            ci.department = getattr(asset, "department", ci.department)
            ci.vendor = getattr(asset, "vendor", ci.vendor)
            ci.save(update_fields=["name","department","vendor","updated_at"])
            ci.record_version = (ci.record_version or 1)+1
            ci.save(update_fields=["record_version"])
            ConfigurationItemHistory.objects.create(configuration_item=ci, actor=actor, event_type="synchronized", source="asset_sync")
    return ci, created

def sync_software_product_to_ci(product, actor=None):
    ci = ConfigurationItem.objects.filter(software_product=product, is_deleted=False).first()
    created = False
    if ci is None:
        ctype = ConfigurationItemType.objects.filter(name="Software Product", is_deleted=False).first()
        if ctype is None:
            ctype = ConfigurationItemType.objects.create(name="Software Product", code="SOFTWARE_PRODUCT", category="software", is_system=False)
        ci = ConfigurationItem.objects.create(
            name=getattr(product, "name", ""),
            ci_type=ctype,
            software_product=product,
            version=getattr(product, "version", "") or "",
            status="active" if getattr(product, "is_active", True) else "inactive",
            source="licensing_sync",
            created_by=actor,
        )
        created = True
    else:
        ci.name = getattr(product, "name", ci.name)
        ci.version = getattr(product, "version", ci.version)
        ci.save(update_fields=["name","version","updated_at"])
    ConfigurationItemHistory.objects.create(configuration_item=ci, actor=actor, event_type="synchronized", source="licensing_sync")
    return ci, created

def get_upstream_dependencies(ci, max_depth=5):
    visited = set()
    result = []
    stack = [(ci.id, 0)]
    while stack:
        cid, d = stack.pop()
        if cid in visited or d > max_depth:
            continue
        visited.add(cid)
        if cid != ci.id:
            result.append(cid)
        if d < max_depth:
            for rel in ConfigurationItem.objects.filter(outgoing_relationships__source_ci_id=cid, outgoing_relationships__status="active", outgoing_relationships__is_deleted=False).values_list("outgoing_relationships__target_ci_id", flat=True):
                if rel not in visited:
                    stack.append((rel, d+1))
    return result

def get_downstream_dependents(ci, max_depth=5):
    visited = set()
    result = []
    stack = [(ci.id, 0)]
    while stack:
        cid, d = stack.pop()
        if cid in visited or d > max_depth:
            continue
        visited.add(cid)
        if cid != ci.id:
            result.append(cid)
        if d < max_depth:
            for rel in ConfigurationItem.objects.filter(incoming_relationships__target_ci_id=cid, incoming_relationships__status="active", incoming_relationships__is_deleted=False).values_list("incoming_relationships__source_ci_id", flat=True):
                if rel not in visited:
                    stack.append((rel, d+1))
    return result

def analyze_ci_impact(ci, proposed_status=None, max_depth=5):
    downstream = get_downstream_dependents(ci, max_depth)
    affected_services = []
    return {
        "configuration_item": ci.id,
        "proposed_status": proposed_status,
        "affected_ci_ids": downstream,
        "affected_ci_count": len(downstream),
        "affected_services": affected_services,
        "max_depth": max_depth,
    }

def create_baseline(name, scope_type, cis, actor=None):
    from .models import ConfigurationBaseline
    import json, hashlib
    b = ConfigurationBaseline.objects.create(name=name, scope_type=scope_type, created_by=actor)
    b.configuration_items.set(cis)
    snapshot = {}
    for ci in cis:
        snapshot[str(ci.id)] = {"name": ci.name, "status": ci.status, "criticality": ci.criticality, "version": ci.version, "attributes": ci.attributes}
    b.snapshot = snapshot
    raw = json.dumps(snapshot, sort_keys=True)
    b.checksum = hashlib.sha256(raw.encode()).hexdigest()
    b.save(update_fields=["snapshot","checksum","updated_at"])
    for ci in cis:
        from .models import ConfigurationItemHistory
        ConfigurationItemHistory.objects.create(configuration_item=ci, actor=actor, event_type="baseline_created", source="manual")
    return b

def compare_ci_to_baseline(ci, baseline):
    snap = (baseline.snapshot or {}).get(str(ci.id), {})
    diffs = []
    for k in ["name","status","criticality","version","attributes"]:
        if snap.get(k) != getattr(ci, k if k != "attributes" else "attributes", None):
            diffs.append({"field": k, "expected": snap.get(k), "actual": getattr(ci, k)})
    return diffs

def evaluate_configuration_drift(ci, baseline=None, actor=None):
    baseline = baseline or ConfigurationBaseline.objects.filter(configuration_items=ci, status="approved").order_by("-created_at").first()
    if not baseline:
        return []
    diffs = compare_ci_to_baseline(ci, baseline)
    findings = []
    for d in diffs:
        fp = hashlib.sha256(f"{ci.id}:{baseline.id}:{d['field']}".encode()).hexdigest()
        finding, _ = ConfigurationDriftFinding.objects.get_or_create(
            fingerprint=fp,
            defaults={"configuration_item": ci, "baseline": baseline, "finding_type": "field_changed", "severity": "medium", "field_name": d["field"], "expected_value": str(d["expected"]), "actual_value": str(d["actual"]), "source": "drift_task"},
        )
        findings.append(finding)
    return findings
