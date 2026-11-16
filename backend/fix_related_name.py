"""Fix related_name clash for acknowledged_by field."""
content = open('backend/monitoring/models.py').read()
content = content.replace(
    'related_name="acknowledged_alerts"',
    'related_name="monitoring_acknowledged_alerts"'
)
open('backend/monitoring/models.py', 'w').write(content)
print('Fixed related_name clash')