import os, sys
sys.path.insert(0, r'D:\IT-Asset-Management-and-Ticketing-System\backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DATABASE__ENGINE'] = 'django.db.backends.sqlite3'
os.environ['DATABASE__NAME'] = ':memory:'

import django
django.setup()

from django.test.utils import CaptureQueriesContext
from django.db import connection

# First, create some test data
from tickets.models import TicketCategory
from accounts.models import User, Department

category, _ = TicketCategory.objects.get_or_create(name="Hardware")
dept, _ = Department.objects.get_or_create(name="IT", code="IT")

user, _ = User.objects.get_or_create(
    username='testuser',
    defaults={'email': 'test@example.com', 'role': 'it_manager'}
)

# Test query counts for different row sizes
for size in [5, 25, 100]:
    with CaptureQueriesContext(connection) as queries:
        # Create rows with category, department, assignee
        rows = []
        for i in range(size):
            row = {
                'title': f'Ticket {i}',
                'description': 'Test',
                'category': category.pk,
                'department': dept.pk,
                'assignee': user.pk,
            }
            rows.append(row)
        
        # Now count queries that would happen during _resolve_references
        # The _resolve_references function queries for all unique refs at once
        cat_ids = set(int(r['category']) for r in rows if r.get('category'))
        dept_ids = set(int(r['department']) for r in rows if r.get('department'))
        user_ids = set(int(r['assignee']) for r in rows if r.get('assignee'))
        
        # Category query
        if cat_ids:
            cats = TicketCategory.objects.filter(pk__in=cat_ids)
            _ = {c.pk: c for c in cats}
        
        # Department query  
        if dept_ids:
            depts = Department.objects.filter(pk__in=dept_ids)
            _ = {d.pk: d for d in depts}
        
        # User query
        if user_ids:
            users = User.objects.filter(pk__in=user_ids)
            _ = {u.pk: u for u in users}
    
    print(f'size={size}: query count = {len(queries)}')
    for q in queries:
        print(f'  {q.sql[:80]}')

# Now test the assertion: query_counts[100] <= query_counts[5] + 1
print()
print("Assertion test: query_counts[100] <= query_counts[5] + 1")
print(f"  100: {len(queries)}" if 'queries' in dir() else "  100: N/A")