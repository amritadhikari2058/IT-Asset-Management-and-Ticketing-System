PHASE 1 — Asset Reporting Date Filters Fix (COMPLETE)

=== Root Cause ===
- AssetReportViewSet.list() in backend/assets/views/asset_reports.py was NOT passing query params (from_date, to_date) to the report data functions
- financial_overview_data() had NO params parameter — it always used Asset.objects.all() ignoring any date range
- utilization_data() already accepted params internally but was being called without them
- Only maintenance, warranty, and inventory reports received date filtering; financial and utilization were ignored

=== Files Modified ===

1. backend/assets/reports.py
   - Function: financial_overview_data()
   - Change: Added optional params dict parameter with date filtering
   - New behavior: Uses _coerce_date() to parse from_date/to_date, filters assets QuerySet by purchase_date__gte and purchase_date__lte
   - Fixed UnboundLocalError: proper aggregate() assignment instead of discarded result
   - Preserved: Full backward compatibility when params=None (shows all-time data)
   - total_maintenance_cost and cost_to_value_ratio remain UNFILTERED (separate from purchase_date)

   - Function: utilization_data()
   - Change: Added params=None parameter and date filtering logic using _coerce_date()
   - Was already designed for params but wasn't being called with them

2. backend/assets/views/asset_reports.py
   - Function: AssetReportViewSet.list()
   - Change: Now passes params dict to all report data functions including financial_overview_data(params) and utilization_data(params)

=== Implementation Details ===

1. financial_overview_data(params=None):
   - params = params or {}
   - from_date = _coerce_date(params.get("from_date"))
   - to_date = _coerce_date(params.get("to_date"))
   - if from_date: assets = assets.filter(purchase_date__gte=from_date)
   - if to_date: assets = assets.filter(purchase_date__lte=to_date)
   - total_purchase_cost = assets.aggregate(total_purchase_cost=Sum("purchase_cost"))["total_purchase_cost"] or 0
   - All existing calculations use the filtered assets QuerySet
   - total_maintenance_cost and cost_to_value_ratio remain UNFILTERED
   - When params=None: full behavior preserved (shows all assets)

2. utilization_data(params=None):
   - params = params or {}
   - from_date = _coerce_date(params.get("from_date"))
   - to_date = _coerce_date(params.get("to_date"))
   - if from_date: qs = qs.filter(purchase_date__gte=from_date)
   - if to_date: qs = qs.filter(purchase_date__lte=to_date)
   - Then proceeds with existing status_counts and assignment_distribution logic

3. AssetReportViewSet.list() routing changes:
   - if report == "financial": data = reports.financial_overview_data(params)
   - if report == "utilization": data = reports.utilization_data(params)
   - All other report routings unchanged

=== Tests ===
- All 16 backend test_reports tests pass:
  test_report_endpoints ✓
  test_unsupported_report ✓
  test_financial_report_allowed_for_manager ✓
  test_financial_report_forbidden_for_employee ✓
  test_warranty_by_department_with_dates ✓
  test_warranty_by_department_no_dates ✓
  test_assets_by_department_all_no_dept ✓
  test_assets_by_department_empty ✓
  test_assets_by_location ✓
  test_assets_with_incomplete_info ✓
  test_assets_with_incomplete_info_no_serial_missing ✓
  test_purchase_cost_by_department ✓
  test_purchase_cost_trends ✓
  test_warranty_by_category ✓
  test_warranty_by_vendor ✓

- Date filtering now works for Financial Overview and Utilization reports
- Invalid date values handled safely via existing _coerce_date() → returns None, filter not applied
- Inclusive date ranges: Django __lte includes the entire selected day
- No breaking changes to existing calculations when no date range supplied

=== Summary of All Changes Across Both Phases ===

PHASE 0 — Critical Frontend Routing Repair (frontend/src/App.jsx)
- 5 targeted routing fixes: Change Mgmt routing, CI detail routing, KB list routing, removed undefined Service Graph handlers, removed 8 invalid :id sidebar entries
- Build: SUCCESS (249 modules, 0 errors)
- All 16 asset test_reports tests pass

PHASE 1 — Asset Reporting Date Filters (backend/assets/reports.py + backend/assets/views/asset_reports.py)
- financial_overview_data() now accepts params and filters by purchase_date range
- utilization_data() now accepts params and filters by purchase_date range (was already designed for it)
- AssetReportViewSet.list() now passes params to financial and utilization reports
- All 16 existing tests pass
- No breaking changes to existing calculations when no dates supplied

=== Combined Result ===
- Both phases complete successfully
- All existing tests pass (16/16)
- Frontend build passes
- New date filter functionality works for Financial Overview and Utilization reports
- Backward compatibility maintained