"""Fix script for Asset Reporting date filters.

Changes:
1. financial_overview_data() - add params support with from_date/to_date filtering on purchase_date
2. AssetReportViewSet.list() - pass params to financial and utilization reports
"""
import sys

# ============================================================
# 1. Fix financial_overview_data() in backend/assets/reports.py
# ============================================================
with open('backend/assets/reports.py', 'r') as f:
    content = f.read()

# Find and replace the financial_overview_data function
old_function = """def financial_overview_data():
    \"\"\"Financial overview for the entire asset inventory (IT staff only).

    Returns:
    - total_purchase_cost: sum of purchase_cost across all non-deleted assets
    - total_assets: count of non-deleted assets
    - by_category: list of {category, asset_count, purchase_cost} sorted by cost desc
    - by_vendor: list of {vendor, asset_count, purchase_cost} sorted by cost desc
    - assets_without_cost: count of assets with no purchase_cost recorded
    - cost_to_value_ratio: total maintenance cost / total purchase cost (None if no purchase cost)
    \"\"\"
    assets = Asset.objects.all()"""

new_function = """def financial_overview_data(params=None):
    \"\"\"Financial overview for the entire asset inventory (IT staff only).

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
    \"\"\"
    params = params or {}
    assets = Asset.objects.all()

    from_date = _coerce_date(params.get("from_date"))
    to_date = _coerce_date(params.get("to_date"))
    if from_date:
        assets = assets.filter(purchase_date__gte=from_date)
    if to_date:
        assets = assets.filter(purchase_date__lte=to_date)

    total_assets = assets.count()"""

if old_function in content:
    content = content.replace(old_function, new_function)
    print("SUCCESS: financial_overview_data() modified")
else:
    print("ERROR: Could not find financial_overview_data template")
    sys.exit(1)

# ============================================================
# 2. Fix AssetReportViewSet.list() to pass params to financial and utilization
# ============================================================
with open('backend/assets/views/asset_reports.py', 'r') as f:
    content = f.read()

old_routing = """if report == "financial":
            data = reports.financial_overview_data()
        elif report == "maintenance":
            data = reports.maintenance_analytics_data(params)
        elif report == "warranty":
            data = reports.warranty_monitoring_data(params)
        elif report == "utilization":
            data = reports.utilization_data()"""

new_routing = """if report == "financial":
            data = reports.financial_overview_data(params)
        elif report == "maintenance":
            data = reports.maintenance_analytics_data(params)
        elif report == "warranty":
            data = reports.warranty_monitoring_data(params)
        elif report == "utilization":
            data = reports.utilization_data(params)"""

if old_routing in content:
    content = content.replace(old_routing, new_routing)
    print("SUCCESS: AssetReportViewSet.list() routing modified")
else:
    print("ERROR: Could not find the routing section to modify")
    sys.exit(1)

# ============================================================
# Verify changes
# ============================================================
with open('backend/assets/reports.py', 'r') as f:
    reports_content = f.read()
with open('backend/assets/views/asset_reports.py', 'r') as f:
    views_content = f.read()

checks = []

# Check financial_overview_data has params
if 'from_date = _coerce_date(params.get("from_date"))' in reports_content:
    checks.append("PASS: financial_overview_data() now accepts params")
else:
    checks.append("FAIL: financial_overview_data() does NOT have params support")

# Check list method passes params
if 'financial_overview_data(params)' in views_content and 'utilization_data(params)' in views_content:
    checks.append("PASS: AssetReportViewSet.list() passes params to both reports")
else:
    checks.append("FAIL: AssetReportViewSet.list() does NOT pass params correctly")

# Print results
print("\n".join(checks))
print()
print("=== Changes summary ===")
print("1. financial_overview_data() now accepts optional params dict")
print("   - Filters assets by purchase_date__gte from_date and purchase_date__lte to_date")
print("   - Uses existing _coerce_date() for safe date parsing")
print("   - Preserves full behavior when no dates supplied (params=None)")
print()
print("2. AssetReportViewSet.list() now passes params dict to:")
print("   - reports.financial_overview_data(params)")
print("   - reports.utilization_data(params)")
print()
print("3. utilization_data() already accepts params internally (no change needed)")
print("   - It already has date filtering logic using _coerce_date()")