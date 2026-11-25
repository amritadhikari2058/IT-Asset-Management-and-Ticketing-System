#!/usr/bin/env python3
with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# The issue may be that the matchRoute function's routes object lookup 
# doesn't work correctly due to some subtle issue. Let me rewrite the 
# entire matchRoute function with explicit route handling.

# First, let me backup the original and then rewrite
old_matchRoute_start = "function matchRoute(hash, auth) {"
old_matchRoute_end = "return routes[route] ?? <Tickets />;"

pos = content.find(old_matchRoute_start)
if pos < 0:
    print("Could not find matchRoute function start")
else:
    # Find the end of the matchRoute function
    # It ends at line 467: return routes[route] ?? <Tickets />;
    end_marker = "return routes[route] ?? <Tickets />;"
    end_pos = content.find(end_marker, pos)
    if end_pos < 0:
        print("Could not find end of matchRoute function")
    else:
        end_pos += len(end_marker)
        # Replace the matchRoute function with a new version
        new_function = '''function matchRoute(hash, auth) {
  const route = hash.split('?')[0];
  
  // Direct route matches (most specific)
  if (route === '#/dashboard') return <Dashboard />;
  if (route === '#/tickets') return <Tickets />;
  if (route === '#/reports/sla') return <SLAReport />;
  if (route === '#/reports/departments') return <DepartmentReports />;
  if (route === '#/reports/saved') return <SavedReports />;
  if (route === '#/reports/schedules') return <ScheduledReports />;
  if (route === '#/reports/coverage') return <AssetReportsPage />;
  if (route === '#/reports/verification_age') return <VerificationQueuePage />;
  if (route === '#/reports/orphans') return <AssetReportsPage />;
  if (route === '#/reports/ownership_gaps') return <AssetReportsPage />;
  if (route === '#/reports/relationship_coverage') return <AssetReportsPage />;
  if (route === '#/reports/drift') return <DriftFindingsPage />;
  if (route === '#/reports/critical_deps') return <AssetReportsPage />;
  if (route === '#reports/asset_sync') return <AssetReportsPage />;
  if (route === '#reports/software_sync') return <AssetReportsPage />;
  if (route === '#verification') return <VerificationQueuePage />;
  if (route === '#services') return <ServicesCatalogue />;
  if (route === '#/cmdb') return <CmdbDashboard />;
  if (route === '#/cmdb/items') return <CmdbItemsList />;
  if (route === '#/cmdb/items/new') return <CiForm />;
  if (route === '#/cmdb/items/:id/edit') return <CiForm />;
  if (route === '#/cmdb/items/:id/impact') return <ImpactAnalysisPage />;
  if (route === '#/cmdb/items/:id/dependencies') return <DependencyMap />;
  if (route === '#cmdb/items/:id/relationships') return <CiRelationshipsPage />;
  if (route === '#/cmdb/types') return <CiTypesPage />;
  if (route === '#/cmdb/baselines') return <BaselinesPage />;
  if (route === '#/cmdb/drift') return <DriftFindingsPage />;
  if (route === '#/cmdb/verification') return <VerificationQueuePage />;
  if (route === '#/cmdb/reports') return <CmdbReports />;
  if (route === '#/cmdb/services') return <ServiceMappingPage />;
  if (route === '#/cmdb/relationships') return <CmdbItemsList />;
  
  // Service detail routes
  if (route.startsWith('#/services/') && route.match(/\/graph$/)) return <ServiceGraphPage />;
  if (route.startsWith('#/services/') && route.match(/\/impact$/)) return <ServiceImpactPage />;
  if (route.startsWith('#/services/') && route.match(/\/single-points-of-failure$/)) return <ServiceSPOFPage />;
  
  // Problem management
  if (route.startsWith('#/problem-management')) {
    if (!auth.canUseProblemManagement) return <AccessDenied />;
    if (route === '#/problem-management') return <ProblemList />;
  }
  
  // Ticket routes
  if (route === '#/tickets/bulk-imports') return auth.isStaff ? <TicketBulkImportsPage /> : <AccessDenied />;
  if (route.match(/^#\/tickets\/bulk-imports\/(\d+)$/)) return auth.isStaff ? <TicketBulkImportDetailPage id={m[1]} /> : <AccessDenied />;
  if (route.match(/^#\/tickets\/(\d+)\/edit$/)) return <TicketForm id={m[1]} />;
  if (route.match(/^#\/tickets\/(\d+)$/)) return <TicketDetail id={m[1]} />;
  if (route.match(/^#\/tickets\/(\d+)\/timeline$/)) return <TicketTimeline id={m[1]} />;
  if (route === '#tickets/queues') return <TicketQueuesPage />;
  if (route === '#tickets/operations') return <TicketOperationsDashboard />;
  if (route === '#tickets/canned-responses') return <CannedResponsesPage />;
  if (route === '#tickets/templates') return <TicketTemplatesPage />;
  if (route === '#tickets/saved-views') return <SavedTicketViews />;
  if (route === '#tickets/satisfaction') return <TicketSatisfactionSurvey />;
  if (route.match(/^#\/tickets\/(\d+)\/merge$/)) return <TicketMergeDialog id={m[1]} />;
  
  // Asset routes
  if (route.match(/^#\/assets\/(\d+)\/edit$/)) return <AssetForm id={m[1]} />;
  if (route === '#assets/new') return <AssetForm />;
  if (route.match(/^#\/assets\/(\d+)$/)) return <AssetDetail id={m[1]} />;
  
  // Vendor routes
  if (route.match(/^#\/vendors\/(\d+)\/edit$/)) return <VendorForm vendorId={m[1]} />;
  if (route === '#vendors/new') return <VendorForm />;
  if (route.match(/^#\/vendors\/(\d+)$/)) return <VendorDetail id={m[1]} />;
  
  // User routes
  if (route.match(/^#\/users\/(\d+)\/?$/)) return <EmployeeDetail id={m[1]} />;
  
  // KB routes
  if (route === '#kb/pending') return <KnowledgeBaseReviewQueue />;
  if (route.match(/^#\/kb\/(\d+)\/revisions\/(\d+)$/)) return <KnowledgeBaseRevisionDetail id={m[1]} number={m[2]} />;
  if (route.match(/^#\/kb\/(\d+)\/revisions$/)) return <KnowledgeBaseRevisions id={m[1]} />;
  if (route.match(/^#\/kb\/(\d+)\/compare$/)) return <KnowledgeBaseCompare id={m[1]} />;
  if (route.match(/^#\/kb\/(\d+)$/)) return <KnowledgeBaseDetail id={m[1]} />;
  
  // Workflow routes
  if (route.match(/^#\/workflow\/rules\/(\d+)\/edit$/)) return <Workflow ruleId={m[1]} ruleEdit />;
  if (route.match(/^#\/workflow\/rules$/)) return <Workflow ruleId={m[1]} />;
  if (route.match(/^#\/workflow\/approvals\/(\d+)$/)) return <Workflow approvalId={m[1]} />;
  if (route.match(/^#\/workflow\/executions$/)) return <Workflow executionId={m[1]} />;
  if (route === '#workflow/rules') return <Workflow tab="rules" />;
  if (route === '#workflow/approvals') return <Workflow tab="approvals" />;
  if (route === '#workflow/executions') return <Workflow tab="executions" />;
  
  // Privacy and retention
  if (route === '#privacy' || route.startsWith('#/privacy/')) return <Privacy />;
  if (route === '#retention' || route.startsWith('#/retention/')) return <Retention />;
  if (route === '#monitoring' || route.startsWith('#/monitoring/')) return <Monitoring />;
  if (route === '#backup' || route.startsWith('#/backup/')) return <Backup />;
  
  // Service requests
  if (route.match(/^#\/service-requests\/(\d+)$/)) return <ServiceRequestDetail id={m[1]} />;
  
  // Inventory routes
  if (route.match(/^#\/inventory\/items\/(\d+)\/edit$/)) return <StockItemForm id={m[1]} />;
  if (route.match(/^#\/inventory\/items\/(\d+)$/)) return <StockItemDetail id={m[1]} />;
  
  // Lifecycle routes
  if (route === '#lifecycle') return <LifecycleDashboard />;
  if (route === '#lifecycle/onboarding') return <LifecycleCases caseType="onboarding" />;
  if (route === '#lifecycle/offboarding') return <LifecycleCases caseType="offboarding" />;
  if (route === '#lifecycle/transfers') return <LifecycleCases caseType="transfer" />;
  if (route === '#lifecycle/new') return <LifecycleForm />;
  if (route.match(/^#\/lifecycle\/(\d+)$/)) return <LifecycleDetail id={m[1]} />;
  
  // Procurement routes
  if (route === '#procurement' || route.startsWith('#/procurement/')) {
    return <ProcurementRouter route={hash} />;
  }
  
  // Software/Licensing routes
  if (route === '#software' || route.startsWith('#/software/') || route === '#licenses' || route.startsWith('#/licenses/') || route === '#license-allocations' || route.startsWith('#/license-allocations/') || route === '#license-installations' || route.startsWith('#/license-installations/') || route === '#license-renewals' || route.startsWith('#/license-renewals/') || route === '#license-compliance' || route.startsWith('#/license-compliance/') || route === '#license-calendar' || route === '#license-utilization' || route === '#my-software') {
    return <LicensingRouter route={hash} />;
  }
  
  // Default fallback
  return <Tickets />;
}'''

# Replace the matchRoute function
pos = content.find("function matchRoute(hash, auth) {")
if pos >= 0:
    # Find the end of the old function
    end_marker = "return routes[route] ?? <Tickets />;"
    end_pos = content.find(end_marker, pos)
    if end_pos >= 0:
        end_pos += len(end_marker)
        new_content = content[:pos] + new_matchRoute + content[end_pos:]
        with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'w') as f:
            f.write(new_content)
        print("Successfully replaced matchRoute function")
    else:
        print("Could not find end marker")
else:
    print("Could not find matchRoute function start")