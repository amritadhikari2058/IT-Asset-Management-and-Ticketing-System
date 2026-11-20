"""Verification script for ticket-asset assignment fixes."""
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

# Use unique names with uuid to avoid collisions
unique_suffix = str(uuid.uuid4())[:8]
tcat = TicketCategory.objects.create(name='SecTestCat_' + unique_suffix)
acat = AssetCategory.objects.create(name='SecTestAssetCat_' + unique_suffix)
a = Asset.objects.create(asset_tag='TA_' + unique_suffix, name='TestAsset_' + unique_suffix, category=acat)

c_emp = APIClient()
c_emp.force_authenticate(user=emp)

# Test 1: Employee creating ticket WITH asset should now fail
print('=== Test 1: Employee creating ticket with asset (should FAIL / 403) ===')
resp = c_emp.post('/api/tickets/', {
    'title': 'Test with asset',
    'description': 'd',
    'category': tcat.pk,
    'department': dep.pk,
    'asset': a.pk,
}, format='json')
print('  Status:', resp.status_code)
print('  Expected: 403 (Forbidden)')
assert resp.status_code == 403, f'FAIL: Expected 403, got {resp.status_code}'
print('  PASS')

# Test 2: Manager creating ticket WITH asset should still work
print()
print('=== Test 2: Manager creating ticket with asset (should PASS / 201) ===')
c_mgr = APIClient()
c_mgr.force_authenticate(user=mgr)
resp = c_mgr.post('/api/tickets/', {
    'title': 'Test with asset',
    'description': 'd',
    'category': tcat.pk,
    'department': dep.pk,
    'asset': a.pk,
}, format='json')
print('  Status:', resp.status_code)
print('  Expected: 201 (Created)')
assert resp.status_code == 201, f'FAIL: Expected 201, got {resp.status_code}'
print('  PASS')

# Test 3: Employee bulk create WITH asset - asset silently stripped, ticket created without it
print()
print('=== Test 3: Employee bulk create with asset (asset silently stripped) ===')
resp = c_emp.post('/api/tickets/bulk_create/', {
    'tickets': [
        {'title': 'Bulk with asset', 'description': 'd',
         'category': tcat.pk, 'department': dep.pk, 'asset': a.pk},
    ],
    'preview': False, 'confirm': True
}, format='json')
print('  Status:', resp.status_code)
print('  Data:', resp.data)
# Should succeed (200) but ticket created without asset in DB
assert resp.status_code == 200, f'FAIL: Expected 200, got {resp.status_code}'
# Verify DB: asset should be None since employee cannot assign
from tickets.models import Ticket
t = Ticket.objects.get(pk=resp.data['successful'][0]['id'])
print('  DB asset_id:', t.asset_id)
print('  DB asset tag:', t.asset.asset_tag if t.asset else 'None')
assert t.asset_id is None, f'FAIL: Expected asset_id to be None, got {t.asset_id}'
print('  PASS (asset silently stripped)')

# Test 4: Employee bulk create PREVIEW should show asset error
print()
print('=== Test 4: Employee bulk create PREVIEW with asset ===')
c_emp2 = APIClient()
c_emp2.force_authenticate(user=emp)
resp = c_emp2.post('/api/tickets/bulk_create/', {
    'tickets': [
        {'title': 'Bulk with asset', 'description': 'd',
         'category': tcat.pk, 'department': dep.pk, 'asset': a.pk},
    ],
    'preview': True
}, format='json')
print('  Status:', resp.status_code)
print('  Data:', resp.data)
# Should show the ticket as invalid due to asset assignment
errors = resp.data.get('invalid', [])
has_asset_error = any(
    e.get('errors', {}).get('asset') for e in errors
)
assert has_asset_error, 'FAIL: Expected asset error in preview'
print('  PASS (asset error shown in preview)')

# Test 5: Employee creating ticket WITHOUT asset should still work
print()
print('=== Test 5: Employee creating ticket without asset (should PASS / 201) ===')
c_emp3 = APIClient()
c_emp3.force_authenticate(user=emp)
resp = c_emp3.post('/api/tickets/', {
    'title': 'Ticket without asset',
    'description': 'd',
    'category': tcat.pk,
    'department': dep.pk,
}, format='json')
print('  Status:', resp.status_code)
print('  Expected: 201 (Created)')
assert resp.status_code == 201, f'FAIL: Expected 201, got {resp.status_code}'
print('  PASS')

print()
print('All verification tests PASSED!')