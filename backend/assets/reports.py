"""Asset reporting and analytics aggregations.

Read-only ORM-driven reporting for the Asset Management module:
- Financial overview (purchase cost totals, by category, by vendor, by department, by location)
- Maintenance analytics (expenditure, by category/vendor, frequently maintained)
- Warranty monitoring (expired, expiring, without warranty, by department/category/vendor)
- Asset utilization (counts by status, assignment distribution)
- Asset inventory analytics (by department, location, vendor, lifecycle, completeness)

All endpoints are IT-staff-only read operations that respect existing
query-parameter filtering conventions.
"""
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractYear, ExtractMonth
from django.utils import timezone
from decimal import Decimal

from assets.models import (
    Asset,
    AssetCategory,
    Assignment,
    Disposal,
    Maintenance,
    Vendor,
)


def _today():
    return timezone.now().date()


def _scalar(value):
    """Return a single filter value, tolerating list-valued param containers."""
    if isinstance(value, (list, tuple)):
        return value[-1] if value else None
    return value


def _coerce_date(value):
    """Accept a ``date`` or an ISO date string; return a ``date`` or ``None``."""
    value = _scalar(value)
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        y, m, d = [int(x) for x in str(value)[:10].split("-")]
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _validate_positive_integer(value, field_name):
    """Validate an optional positive integer query parameter."""
    raw = _scalar(value)
    if raw in (None, ""):
        return None
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive integer.")
    if number < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
    return number


def validate_report_params(params=None):
    """Validate shared report query params supplied through an HTTP request.

    Malformed dates and non-positive pagination values are rejected with a
    clear error instead of being silently ignored or causing a 500.
    """
    params = params or {}
    from_raw = _scalar(params.get("from_date"))
    to_raw = _scalar(params.get("to_date"))
    from_date = _coerce_date(from_raw)
    to_date = _coerce_date(to_raw)
    if from_raw not in (None, "") and from_date is None:
        raise ValueError("from_date must be a valid ISO date (YYYY-MM-DD).")
    if to_raw not in (None, "") and to_date is None:
        raise ValueError("to_date must be a valid ISO date (YYYY-MM-DD).")
    if from_date and to_date and from_date > to_date:
        raise ValueError("from_date must be on or before to_date.")
    _validate_positive_integer(params.get("page"), "page")
    _validate_positive_integer(params.get("page_size"), "page_size")


def _status_counts(queryset, field="status"):
    """Zero-filled {status: count} for Asset status values."""
    counts = {
        "available": 0,
        "assigned": 0,
        "in_repair": 0,
        "retired": 0,
        "lost": 0,
        "disposed": 0,
    }
    for row in queryset.values(field).annotate(_n=Count("id")):
        key = row[field]
        if key in counts:
            counts[key] = row["_n"]
    return counts


def financial_overview_data(params=None):
    """Financial overview for the entire asset inventory (IT staff only).

    Optional query params dict:
    - from_date: filter assets with purchase_date >= this date (ISO date string)
    - to_date: filter assets with purchase_date <= this date (ISO date string)

    Returns:
    - total_purchase_cost: sum of purchase_cost across filtered assets
    - total_assets: count of filtered assets
    - by_category: list of {category, asset_count, purchase_cost} sorted by cost desc
    - by_vendor: list of {vendor, asset_count, purchase_cost} sorted by cost desc
    - assets_without_cost: count of filtered assets with no purchase_cost recorded
    - cost_to_value_ratio: total maintenance cost / total purchase cost (None if no purchase cost)
    """
    params = params or {}
    assets = Asset.objects.all()

    from_date = _coerce_date(params.get("from_date"))
    to_date = _coerce_date(params.get("to_date"))
    if from_date:
        assets = assets.filter(purchase_date__gte=from_date)
    if to_date:
        assets = assets.filter(purchase_date__lte=to_date)

    total_assets = assets.count()

    total_purchase_cost = assets.aggregate(
        total_purchase_cost=Sum("purchase_cost", output_field=None)
    )["total_purchase_cost"] or 0

    by_category = (
        assets.values("category__name")
        .annotate(asset_count=Count("id"), purchase_cost=Sum("purchase_cost"))
        .order_by("-purchase_cost")
    )
    by_vendor = (
        assets.values("vendor__name")
        .annotate(asset_count=Count("id"), purchase_cost=Sum("purchase_cost"))
        .order_by("-purchase_cost")
    )

    assets_without_cost = assets.filter(purchase_cost__isnull=True).count()

    total_maintenance_cost = Maintenance.objects.aggregate(
        s=Sum("cost", output_field=None)
    )["s"]
    total_maintenance_cost = total_maintenance_cost or 0

    cost_to_value_ratio = None
    if total_purchase_cost:
        cost_to_value_ratio = round(
            total_maintenance_cost / total_purchase_cost * 100, 2
        )

    return {
        "total_assets": total_assets,
        "total_purchase_cost": total_purchase_cost,
        "assets_without_cost": assets_without_cost,
        "total_maintenance_cost": total_maintenance_cost,
        "cost_to_value_ratio": cost_to_value_ratio,
        "by_category": [
            {
                "category": row["category__name"] or "Uncategorized",
                "asset_count": row["asset_count"],
                "purchase_cost": row["purchase_cost"] or 0,
            }
            for row in by_category
        ],
        "by_vendor": [
            {
                "vendor": row["vendor__name"] or "No vendor",
                "asset_count": row["asset_count"],
                "purchase_cost": row["purchase_cost"] or 0,
            }
            for row in by_vendor
        ],
    }


def maintenance_analytics_data(params=None):
    """Maintenance analytics for IT staff.

    Optional query params (dict):
    - status: filter by maintenance status
    - maintenance_type: filter by type
    - q: search title/asset
    - from_date/to_date: date range on scheduled_date

    Returns:
    - total_records, total_cost, completed_cost, pending_count
    - by_status: {status: count}
    - by_type: {type: count}
    - by_category: [{category, count, cost}] sorted by cost desc
    - by_vendor: [{vendor, count, cost}] sorted by cost desc
    - top_assets: [{asset_tag, name, count, cost}] top 10 by maintenance count
    - overdue_count
    - most_recent_maintenance: date or None
    """
    params = params or {}
    today = _today()
    qs = Maintenance.objects.select_related("asset", "asset__category", "asset__vendor").all()

    asset = _scalar(params.get("asset"))
    if asset:
        try:
            qs = qs.filter(asset_id=int(asset))
        except (TypeError, ValueError):
            qs = qs.none()

    status = _scalar(params.get("status"))
    if status:
        qs = qs.filter(status=status)
    maintenance_type = _scalar(params.get("maintenance_type"))
    if maintenance_type:
        qs = qs.filter(maintenance_type=maintenance_type)
    q = (_scalar(params.get("q")) or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
        )
    date_from = _coerce_date(params.get("from_date"))
    date_to = _coerce_date(params.get("to_date"))
    if date_from:
        qs = qs.filter(scheduled_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(scheduled_date__date__lte=date_to)

    total_records = qs.count()
    completed = qs.filter(status="completed")
    total_cost = qs.aggregate(s=Sum("cost"))["s"] or 0
    completed_cost = completed.aggregate(s=Sum("cost"))["s"] or 0
    pending_count = qs.filter(status__in=["scheduled", "in_progress", "overdue"]).count()
    overdue_count = qs.filter(status="overdue").count()

    by_status = {}
    for row in qs.values("status").annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]

    by_type = {}
    for row in qs.values("maintenance_type").annotate(n=Count("id")):
        by_type[row["maintenance_type"]] = row["n"]

    by_category = (
        qs.values("asset__category__name")
        .annotate(count=Count("id"), cost=Sum("cost"))
        .order_by("-cost")
    )
    by_vendor = (
        qs.values("asset__vendor__name")
        .annotate(count=Count("id"), cost=Sum("cost"))
        .order_by("-cost")
    )

    top_assets = (
        qs.values("asset__asset_tag", "asset__name", "asset_id")
        .annotate(count=Count("id"), cost=Sum("cost"))
        .order_by("-count", "-cost")[:10]
    )

    most_recent = qs.order_by("-scheduled_date").values("scheduled_date").first()
    most_recent_date = (
        most_recent["scheduled_date"].date() if most_recent and most_recent["scheduled_date"] else None
    )

    return {
        "total_records": total_records,
        "total_cost": total_cost,
        "completed_cost": completed_cost,
        "pending_count": pending_count,
        "overdue_count": overdue_count,
        "by_status": by_status,
        "by_type": by_type,
        "by_category": [
            {
                "category": row["asset__category__name"] or "Uncategorized",
                "count": row["count"],
                "cost": row["cost"] or 0,
            }
            for row in by_category
        ],
        "by_vendor": [
            {
                "vendor": row["asset__vendor__name"] or "No vendor",
                "count": row["count"],
                "cost": row["cost"] or 0,
            }
            for row in by_vendor
        ],
        "top_assets": [
            {
                "asset_tag": row["asset__asset_tag"],
                "name": row["asset__name"],
                "asset_id": row["asset_id"],
                "count": row["count"],
                "cost": row["cost"] or 0,
            }
            for row in top_assets
        ],
        "most_recent_maintenance": most_recent_date,
    }


def warranty_monitoring_data(params=None):
    """Warranty monitoring for IT staff.

    Optional query params:
    - expiring_in_days: window for "expiring soon" (default 30, 90, 180)
    - from_date/to_date: restrict warranty_expiry range

    Returns:
    - expired_count: warranty_expiry < today
    - expiring_soon: {30: n, 90: n, 180: n}
    - without_warranty: assets with no warranty_expiry
    - total_with_warranty: assets that have warranty_expiry set
    - expiring_list: [{asset_tag, name, category, vendor, expiry, days_left}] sorted by expiry
    """
    params = params or {}
    today = _today()
    qs = Asset.objects.select_related("category", "vendor").all()

    date_from = _coerce_date(params.get("from_date"))
    date_to = _coerce_date(params.get("to_date"))
    if date_from:
        qs = qs.filter(warranty_expiry__gte=date_from)
    if date_to:
        qs = qs.filter(warranty_expiry__lte=date_to)

    total_with_warranty = qs.filter(warranty_expiry__isnull=False).count()
    without_warranty = qs.filter(warranty_expiry__isnull=True).count()

    expired_qs = qs.filter(warranty_expiry__lt=today)
    expired_count = expired_qs.count()

    expiring_soon = {}
    for window in [30, 90, 180]:
        from datetime import timedelta
        limit = today + timedelta(days=window)
        expiring_soon[window] = qs.filter(
            warranty_expiry__gte=today, warranty_expiry__lte=limit
        ).count()

    expiring_list = (
        qs.filter(
            warranty_expiry__gte=today,
            warranty_expiry__lte=today + timedelta(days=90),
        )
        .order_by("warranty_expiry")[:50]
    )

    return {
        "total_with_warranty": total_with_warranty,
        "without_warranty": without_warranty,
        "expired_count": expired_count,
        "expiring_soon": expiring_soon,
        "expiring_list": [
            {
                "asset_tag": a.asset_tag,
                "name": a.name,
                "category": a.category.name if a.category else None,
                "vendor": a.vendor.name if a.vendor else None,
                "expiry": a.warranty_expiry.isoformat() if a.warranty_expiry else None,
                "days_left": (a.warranty_expiry - today).days if a.warranty_expiry else None,
            }
            for a in expiring_list
        ],
        "most_recent_warranty_expiry": (
            qs.filter(warranty_expiry__isnull=False)
            .order_by("-warranty_expiry")
            .values("warranty_expiry")
            .first()
        ),
    }


def utilization_data(params=None):
    """Asset utilization insights (IT staff only).

    Optional query params dict:
    - from_date: filter assets with purchase_date >= this date (ISO date string)
    - to_date: filter assets with purchase_date <= this date (ISO date string)

    Returns:
    - status_counts: {status: count}
    - total_assets
    - assigned_count, available_count, maintenance_count, retired_count, disposed_count, lost_count
    - assignment_distribution: [{employee, employee_id, department, asset_count}] top holders
    """
    params = params or {}
    qs = Asset.objects.all()

    from_date = _coerce_date(params.get("from_date"))
    to_date = _coerce_date(params.get("to_date"))
    if from_date:
        qs = qs.filter(purchase_date__gte=from_date)
    if to_date:
        qs = qs.filter(purchase_date__lte=to_date)
    status_counts = _status_counts(qs)

    total_assets = qs.count()
    assigned_count = status_counts["assigned"]
    available_count = status_counts["available"]
    maintenance_count = status_counts["in_repair"]
    retired_count = status_counts["retired"]
    disposed_count = status_counts["disposed"]
    lost_count = status_counts["lost"]

    # Assignment distribution: who holds the most assets
    from django.contrib.auth import get_user_model
    User = get_user_model()
    assignment_distribution = None
    try:
        assignment_distribution = (
            qs.filter(status="assigned")
            .select_related("assigned_to", "assigned_to__home_department")
            .values(
                "assigned_to__employee_id",
                "assigned_to__email",
                "assigned_to__first_name",
                "assigned_to__last_name",
                "assigned_to__home_department__name",
            )
            .annotate(asset_count=Count("id"))
            .order_by("-asset_count")[:20]
        )
    except Exception:
        assignment_distribution = []


    return {
        "status_counts": status_counts,
        "total_assets": total_assets,
        "assigned_count": assigned_count,
        "available_count": available_count,
        "maintenance_count": maintenance_count,
        "retired_count": retired_count,
        "disposed_count": disposed_count,
        "lost_count": lost_count,
        "assignment_distribution": [
            {
                "employee_id": row["assigned_to__employee_id"],
                "employee_name": (
                    f"{row['assigned_to__first_name']} {row['assigned_to__last_name']}".strip()
                    or row["assigned_to__email"]
                ),
                "email": row["assigned_to__email"],
                "department": row.get("assigned_to__home_department__name"),
                "asset_count": row["asset_count"],
            }
            for row in (assignment_distribution or [])
        ],
    }


def asset_report_data(params=None):
    """Filtered asset inventory data for export/reporting (IT staff only).

    Optional query params:
    - q, status, category, department, vendor: filters (same as list endpoint)
    - from_date/to_date: purchase_date range
    - page/page_size: pagination

    Returns paginated asset rows with all relevant fields for reporting.
    """
    params = params or {}
    qs = Asset.objects.select_related(
        "category", "assigned_to", "department", "vendor"
    ).all()

    q = (_scalar(params.get("q")) or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(asset_tag__icontains=q)
            | Q(serial_number__icontains=q)
            | Q(location__icontains=q)
            | Q(department__name__icontains=q)
        )
    status = _scalar(params.get("status"))
    if status:
        qs = qs.filter(status=status)
    category = _scalar(params.get("category"))
    if category:
        qs = qs.filter(category_id=category)
    department = _scalar(params.get("department"))
    if department:
        qs = qs.filter(department_id=department)
    vendor = _scalar(params.get("vendor"))
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    from_date = _coerce_date(params.get("from_date"))
    to_date = _coerce_date(params.get("to_date"))
    if from_date:
        qs = qs.filter(purchase_date__gte=from_date)
    if to_date:
        qs = qs.filter(purchase_date__lte=to_date)

    total = qs.count()
    page_size = int(_scalar(params.get("page_size", 100)) or 100)
    page = int(_scalar(params.get("page", 1)) or 1)
    offset = (page - 1) * page_size
    rows_qs = qs[offset : offset + page_size]

    rows = [
        {
            "id": a.pk,
            "asset_tag": a.asset_tag,
            "name": a.name,
            "category": a.category.name if a.category else None,
            "status": a.status,
            "location": a.location,
            "department": a.department.name if a.department else None,
            "vendor": a.vendor.name if a.vendor else None,
            "assigned_to": (
                f"{a.assigned_to.first_name} {a.assigned_to.last_name}".strip()
                or a.assigned_to.email
            )
            if a.assigned_to
            else None,
            "serial_number": a.serial_number,
            "description": a.description,
            "purchase_date": a.purchase_date.isoformat() if a.purchase_date else None,
            "warranty_start": a.warranty_start.isoformat() if a.warranty_start else None,
            "warranty_expiry": a.warranty_expiry.isoformat() if a.warranty_expiry else None,
            "purchase_cost": str(a.purchase_cost) if a.purchase_cost is not None else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows_qs
    ]

    return {
        "items": rows,
        "count": total,
        "page": page,
        "page_size": page_size,
        "has_next": offset + page_size < total,
        "has_prev": page > 1,
    }


def assets_by_department():
    """Assets grouped by department.

    Returns:
        {total, by_department} where by_department is a list of
        {department, asset_count} sorted by asset_count desc.
        Uncategorized (null department) included.
    """
    qs = Asset.objects.select_related("department").all()
    result = (
        qs.values("department__name")
        .annotate(asset_count=Count("id"))
        .order_by("-asset_count")
    )
    rows = [
        {
            "department": row["department__name"] or "No department",
            "asset_count": row["asset_count"],
        }
        for row in result
    ]
    return {"total": len(rows), "by_department": rows}


def assets_by_location():
    """Assets grouped by location.

    Returns:
        {total, by_location} where by_location is a list of
        {location, asset_count} sorted by asset_count desc.
        Assets with blank location grouped as "Unassigned".
    """
    qs = Asset.objects.select_related().all()
    result = (
        qs.values("location")
        .annotate(asset_count=Count("id"))
        .order_by("-asset_count")
    )
    rows = [
        {
            "location": row["location"] or "Unassigned",
            "asset_count": row["asset_count"],
        }
        for row in result
    ]
    return {"total": len(rows), "by_location": rows}


def assets_with_incomplete_info():
    """Assets missing critical inventory information.

    Returns counts of assets missing department, vendor, serial number,
    or with no purchase cost recorded. Useful for data quality audits.

    Returns:
        - total: count of assets with at least one missing field
        - missing_department: assets with no department
        - missing_vendor: assets with no vendor
        - missing_serial: assets with no serial number
        - missing_purchase_cost: assets with no purchase cost
    """
    qs = Asset.objects.all()

    missing_department = qs.filter(department__isnull=True).count()
    missing_vendor = qs.filter(vendor__isnull=True).count()
    missing_serial = qs.filter(serial_number="").count()
    missing_purchase_cost = qs.filter(purchase_cost__isnull=True).count()

    # Assets with at least one of the above missing
    total = (
        qs.filter(Q(department__isnull=True) | Q(vendor__isnull=True)
                  | Q(serial_number="") | Q(purchase_cost__isnull=True))
        .count()
    )

    return {
        "total": total,
        "missing_department": missing_department,
        "missing_vendor": missing_vendor,
        "missing_serial": missing_serial,
        "missing_purchase_cost": missing_purchase_cost,
    }


def warranty_by_department(params=None):
    """Warranty status grouped by department.

    Optional query params:
    - from_date/to_date: restrict warranty_expiry range

    Returns:
        - by_department: [{department, total, expired, expiring_30, expiring_90, expiring_180, without}]
        - total_with_warranty: overall count with warranty
        - total_without_warranty: overall count without warranty
    """
    params = params or {}
    today = timezone.now().date()
    qs = Asset.objects.select_related("category", "vendor", "department").all()

    date_from = _coerce_date(params.get("from_date"))
    date_to = _coerce_date(params.get("to_date"))
    if date_from:
        qs = qs.filter(warranty_expiry__gte=date_from)
    if date_to:
        qs = qs.filter(warranty_expiry__lte=date_to)

    total_with_warranty = qs.filter(warranty_expiry__isnull=False).count()
    total_without_warranty = qs.filter(warranty_expiry__isnull=True).count()

    by_department = (
        qs.filter(department__isnull=False)
        .values("department__name")
        .annotate(
            total=Count("id"),
            expired=Count("id", filter=Q(warranty_expiry__lt=today)),
            expiring_30=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                             warranty_expiry__lte=today + timedelta(days=30)),
            ),
            expiring_90=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=90)),
            ),
            expiring_180=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=180)),
            ),
            without=Count("id", filter=Q(warranty_expiry__isnull=True)),
        )
        .order_by("-total")
    )

    return {
        "by_department": [
            {
                "department": row["department__name"],
                "total": row["total"],
                "expired": row["expired"],
                "expiring_30": row["expiring_30"],
                "expiring_90": row["expiring_90"],
                "expiring_180": row["expiring_180"],
                "without": row["without"],
            }
            for row in by_department
        ],
        "total_with_warranty": total_with_warranty,
        "total_without_warranty": total_without_warranty,
    }


def warranty_by_category(params=None):
    """Warranty status grouped by asset category.

    Optional query params:
    - from_date/to_date: restrict warranty_expiry range

    Returns:
        - by_category: [{category, total, expired, expiring_30, expiring_90, expiring_180, without}]
        - total_with_warranty: overall count with warranty
        - total_without_warranty: overall count without warranty
    """
    params = params or {}
    today = timezone.now().date()
    qs = Asset.objects.select_related("category", "vendor").all()

    date_from = _coerce_date(params.get("from_date"))
    date_to = _coerce_date(params.get("to_date"))
    if date_from:
        qs = qs.filter(warranty_expiry__gte=date_from)
    if date_to:
        qs = qs.filter(warranty_expiry__lte=date_to)

    total_with_warranty = qs.filter(warranty_expiry__isnull=False).count()
    total_without_warranty = qs.filter(warranty_expiry__isnull=True).count()

    by_category = (
        qs.filter(category__isnull=False)
        .values("category__name")
        .annotate(
            total=Count("id"),
            expired=Count("id", filter=Q(warranty_expiry__lt=today)),
            expiring_30=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=30)),
            ),
            expiring_90=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=90)),
            ),
            expiring_180=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=180)),
            ),
            without=Count("id", filter=Q(warranty_expiry__isnull=True)),
        )
        .order_by("-total")
    )

    return {
        "by_category": [
            {
                "category": row["category__name"],
                "total": row["total"],
                "expired": row["expired"],
                "expiring_30": row["expiring_30"],
                "expiring_90": row["expiring_90"],
                "expiring_180": row["expiring_180"],
                "without": row["without"],
            }
            for row in by_category
        ],
        "total_with_warranty": total_with_warranty,
        "total_without_warranty": total_without_warranty,
    }


def warranty_by_vendor(params=None):
    """Warranty status grouped by vendor.

    Optional query params:
    - from_date/to_date: restrict warranty_expiry range

    Returns:
        - by_vendor: [{vendor, total, expired, expiring_30, expiring_90, expiring_180, without}]
        - total_with_warranty: overall count with warranty
        - total_without_warranty: overall count without warranty
    """
    params = params or {}
    today = timezone.now().date()
    qs = Asset.objects.select_related("category", "vendor").all()

    date_from = _coerce_date(params.get("from_date"))
    date_to = _coerce_date(params.get("to_date"))
    if date_from:
        qs = qs.filter(warranty_expiry__gte=date_from)
    if date_to:
        qs = qs.filter(warranty_expiry__lte=date_to)

    total_with_warranty = qs.filter(warranty_expiry__isnull=False).count()
    total_without_warranty = qs.filter(warranty_expiry__isnull=True).count()

    by_vendor = (
        qs.filter(vendor__isnull=False)
        .values("vendor__name")
        .annotate(
            total=Count("id"),
            expired=Count("id", filter=Q(warranty_expiry__lt=today)),
            expiring_30=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=30)),
            ),
            expiring_90=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=90)),
            ),
            expiring_180=Count(
                "id",
                filter=Q(warranty_expiry__gte=today,
                           warranty_expiry__lte=today + timedelta(days=180)),
            ),
            without=Count("id", filter=Q(warranty_expiry__isnull=True)),
        )
        .order_by("-total")
    )

    return {
        "by_vendor": [
            {
                "vendor": row["vendor__name"],
                "total": row["total"],
                "expired": row["expired"],
                "expiring_30": row["expiring_30"],
                "expiring_90": row["expiring_90"],
                "expiring_180": row["expiring_180"],
                "without": row["without"],
            }
            for row in by_vendor
        ],
        "total_with_warranty": total_with_warranty,
        "total_without_warranty": total_without_warranty,
    }


def purchase_cost_by_department():
    """Purchase cost grouped by department.

    Returns:
        {by_department, total} where by_department is a list of
        {department, asset_count, purchase_cost} sorted by purchase_cost desc.
        Uncategorized (null department) included.
    """
    qs = Asset.objects.select_related("department").all()
    result = (
        qs.values("department__name")
        .annotate(asset_count=Count("id"), purchase_cost=Sum("purchase_cost"))
        .order_by("-purchase_cost")
    )
    rows = [
        {
            "department": row["department__name"] or "No department",
            "asset_count": row["asset_count"],
            "purchase_cost": row["purchase_cost"] or 0,
        }
        for row in result
    ]
    total_purchase_cost = sum((r["purchase_cost"] for r in rows), Decimal("0"))
    return {"by_department": rows, "total": total_purchase_cost}


def purchase_cost_trends():
    """Purchase cost trends over time by month.

    Returns monthly purchase costs for assets with purchase_date set.
    Uses purchase_date year-month grouping.

    Returns:
        {total_assets, by_month} where by_month is a list of
        {month, year, purchase_cost, asset_count} sorted by month desc.
    """
    qs = Asset.objects.filter(purchase_date__isnull=False).all()
    result = (
        qs.annotate(
            year=ExtractYear("purchase_date"),
            month=ExtractMonth("purchase_date"),
        )
        .values("year", "month")
        .annotate(
            purchase_cost=Sum("purchase_cost"),
            asset_count=Count("id"),
        )
        .order_by("-year", "-month")[:24]
    )
    rows = []
    for row in result:
        rows.append({
            "month": row["month"],
            "year": row["year"],
            "purchase_cost": row["purchase_cost"] or 0,
            "asset_count": row["asset_count"],
        })
    total_assets = sum((r["asset_count"] for r in rows), 0)
    return {"total_assets": total_assets, "by_month": rows}
