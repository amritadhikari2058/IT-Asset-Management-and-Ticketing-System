"""Export builders for Software Licensing datasets (CSV, XLSX, PDF, DOCX).

Adheres to strict data governance:
- Plaintext secrets, encrypted values, credentials, and passwords are NEVER exported.
- Spreadsheet formula injection protection applied via string escaping.
- Role-based permissions enforced before dataset generation.
"""

from typing import Any, Dict, List, Optional
from django.db.models import Q
from common.exports import _cell, _csv_bytes, _escape, _xlsx_bytes
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseRenewal,
    SoftwareInstallation,
    SoftwareProduct,
)
from licensing.permissions import is_employee, is_it_staff


def product_rows(user=None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    filters = filters or {}
    qs = SoftwareProduct.objects.filter(is_deleted=False)

    if is_employee(user):
        qs = qs.filter(approved_status__in=["approved", "restricted"])

    category = filters.get("category")
    if category:
        qs = qs.filter(category=category)

    rows = []
    for p in qs.order_by("name"):
        rows.append({
            "id": p.pk,
            "name": p.name,
            "code": p.code or "",
            "publisher": p.publisher,
            "edition": p.edition or "",
            "version": p.version or "",
            "category": p.category,
            "platform": p.platform,
            "license_model": p.license_model,
            "approved_status": p.approved_status,
            "support_status": p.support_status,
            "is_active": "true" if p.is_active else "false",
        })
    return rows


def agreement_rows(user=None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if is_employee(user):
        return []
    filters = filters or {}
    qs = LicenseAgreement.objects.filter(is_deleted=False).select_related("software_product", "vendor", "department")

    rows = []
    for a in qs.order_by("-created_at"):
        rows.append({
            "id": a.pk,
            "agreement_number": a.agreement_number,
            "product_name": a.software_product.name,
            "vendor_name": a.vendor.name if a.vendor else "",
            "agreement_type": a.agreement_type,
            "license_model": a.license_model,
            "status": a.status,
            "expiry_date": str(a.expiry_date) if a.expiry_date else "",
            "renewal_date": str(a.renewal_date) if a.renewal_date else "",
            "quantity_purchased": a.quantity_purchased if not a.is_unlimited else "Unlimited",
            "quantity_allocated": a.quantity_allocated,
            "quantity_available": a.quantity_available if not a.is_unlimited else "Unlimited",
            "utilization_percent": f"{a.utilization_percent}%" if a.utilization_percent is not None else "N/A",
            "total_cost": str(a.total_cost),
            "currency": a.currency,
            "department": a.department.name if a.department else "",
        })
    return rows


def allocation_rows(user=None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    filters = filters or {}
    qs = LicenseAllocation.objects.all().select_related("agreement__software_product", "assigned_user", "assigned_asset", "department")

    if is_employee(user):
        qs = qs.filter(assigned_user=user)

    rows = []
    for al in qs.order_by("-assigned_at"):
        rows.append({
            "id": al.pk,
            "reference": al.allocation_reference,
            "agreement_number": al.agreement.agreement_number,
            "product_name": al.agreement.software_product.name,
            "allocation_type": al.allocation_type,
            "status": al.status,
            "user_email": al.assigned_user.email if al.assigned_user else "",
            "asset_tag": al.assigned_asset.asset_tag if al.assigned_asset else "",
            "department": al.department.name if al.department else "",
            "assigned_at": al.assigned_at.isoformat() if al.assigned_at else "",
            "expected_release_date": al.expected_release_date.isoformat() if al.expected_release_date else "",
        })
    return rows


def installation_rows(user=None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if is_employee(user):
        return []
    filters = filters or {}
    qs = SoftwareInstallation.objects.all().select_related("software_product", "asset", "allocation")

    rows = []
    for inst in qs.order_by("-detected_at"):
        rows.append({
            "id": inst.pk,
            "product_name": inst.software_product.name,
            "asset_tag": inst.asset.asset_tag,
            "installed_version": inst.installed_version,
            "status": inst.status,
            "compliance_status": inst.compliance_status,
            "detected_at": inst.detected_at.isoformat() if inst.detected_at else "",
            "source": inst.source,
        })
    return rows


def compliance_finding_rows(user=None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if is_employee(user):
        return []
    qs = LicenseComplianceFinding.objects.all().select_related("software_product", "agreement", "asset", "user")

    rows = []
    for fnd in qs.order_by("-detected_at"):
        rows.append({
            "id": fnd.pk,
            "finding_type": fnd.finding_type,
            "severity": fnd.severity,
            "title": fnd.title,
            "status": fnd.status,
            "product_name": fnd.software_product.name if fnd.software_product else "",
            "agreement_number": fnd.agreement.agreement_number if fnd.agreement else "",
            "detected_at": fnd.detected_at.isoformat() if fnd.detected_at else "",
        })
    return rows


DATASET_BUILDERS = {
    "software_products": product_rows,
    "license_agreements": agreement_rows,
    "license_allocations": allocation_rows,
    "software_installations": installation_rows,
    "license_compliance_findings": compliance_finding_rows,
}


def export_dataset(dataset_name: str, fmt: str = "csv", user=None, filters=None) -> bytes:
    """Generate safe exported file bytes (CSV or XLSX) for the specified dataset."""
    builder = DATASET_BUILDERS.get(dataset_name)
    if not builder:
        raise ValueError(f"Unknown dataset '{dataset_name}'.")

    rows = builder(user=user, filters=filters)
    if not rows:
        fields = ["info"]
        rows = [{"info": "No matching records found."}]
    else:
        fields = list(rows[0].keys())

    if fmt == "xlsx":
        return _xlsx_bytes(rows, fields, title=dataset_name.replace("_", " ").title())
    return _csv_bytes(rows, fields)
