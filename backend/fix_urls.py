"""Fix urls.py syntax."""
content = open('backend/monitoring/urls.py').read()
content = content.replace(
    'path("reports/target-coverage/", views.ReportViewSet.as_view({"get": "target_coverage"},',
    'path("reports/target-coverage/", views.ReportViewSet.as_view({"get": "target_coverage"})),'
)
open('backend/monitoring/urls.py', 'w').write(content)
print('Fixed')