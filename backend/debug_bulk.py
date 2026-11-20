"""Debug script for bulk create asset assignment."""
import os, django
from django.conf import settings
settings.ALLOWED_HOSTS += ['testserver', 'localhost', '127.0.0.1']
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from rest_framework.test import APIClient
from accounts.tests import make_users
from tickets.models import Ticket, TicketCategory
from assets.models import Asset, AssetCategory
import uuid

dep, admin, mgr, emp = make_users()
unique_suffix = str(uuid.uuid4())[:8]
tcat = TicketCategory.objects.create(name='SecBulkDebug_' + unique_suffix)
acat = AssetCategory.objects.create(name='AssetDebug_' + unique_suffix)
a = Asset.objects.create(asset_tag='DEBUG_' + unique_suffix, name='DebugAsset', category=acat)

c_emp = APIClient()
c_emp.force_authenticate(user=emp)

print('User role:', getattr(emp, 'role', ''))
print('Is superuser:', emp.is_superuser)

print()
print('=== Bulk create PREVIEW with asset (employee) ===')
resp = c_emp.post('/api/tickets/bulk_create/', {
    'tickets': [
        {'title': 'Bulk with asset', 'description': 'd',
         'category': tcat.pk, 'department': dep.pk, 'asset': a.pk},
    ],
    'preview': True
}, format='json')
print('Status:', resp.status_code)
print('Data:', resp.data)
preview_data = resp.data.get('preview', [{}])[0]
print('  Row valid:', preview_data.get('valid'))
print('  Row errors:', preview_data.get('errors'))

print()
print('=== Bulk create CONFIRM with asset (employee) ===')
resp = c_emp.post('/api/tickets/bulk_create/', {
    'tickets': [
        {'title': 'Bulk with asset', 'description': 'd',
         'category': tcat.pk, 'department': dep.pk, 'asset': a.pk},
    ],
    'preview': False, 'confirm': True
}, format='json')
print('Status:', resp.status_code)
print('Data:', resp.data)

# Check DB
if resp.status_code == 200:
    from tickets.models import Ticket
    t = Ticket.objects.get(pk=resp.data['successful'][0]['id'])
    print('DB asset_id:', t.asset_id)
    print('DB asset tag:', t.asset.asset_tag if t.asset else 'None')