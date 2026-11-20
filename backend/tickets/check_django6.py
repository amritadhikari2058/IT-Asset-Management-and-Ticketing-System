import os
import sys

# Set up Django environment
os.chdir(r'D:\IT-Asset-Management-and-Ticketing-System\backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
django.setup()

from django.db import models
from django.db.models import Q, F

print("Django version:", django.VERSION)
print()

# Test 1: CheckConstraint with condition= keyword (Django 6 style)
try:
    c = models.CheckConstraint(condition=~Q(source_ticket=models.F("target_ticket")), name="test_rel")
    print("TEST 1 PASSED: CheckConstraint with condition= keyword works")
except Exception as e:
    print(f"TEST 1 FAILED: {e}")

# Test 2: CheckConstraint with check= positional (old Django style - should fail in Django 6)
try:
    c = models.CheckConstraint(~Q(source_ticket=models.F("target_ticket")), name="test_rel_old")
    print("TEST 2 PASSED: CheckConstraint with check= positional works (unexpected in Django 6)")
except TypeError as e:
    print(f"TEST 2 FAILED (expected in Django 6): {e}")
except Exception as e:
    print(f"TEST 2 FAILED with different error: {e}")

# Test 3: Check all ticket model constraints
print("\nTEST 3: Checking TicketRelation constraints...")
try:
    from tickets.models import TicketRelation
    meta = TicketRelation._meta
    constraints = meta.constraints
    for c in constraints:
        if hasattr(c, 'condition'):
            print(f"  CheckConstraint: {c.name}, condition type: {type(c.condition)}")
        else:
            print(f"  Other constraint: {c.name}, type: {type(c).__name__}")
except Exception as e:
    print(f"TEST 3 FAILED: {e}")

print("\nTEST 4: Checking TicketMergeRecord constraints...")
try:
    from tickets.models import TicketMergeRecord
    meta = TicketMergeRecord._meta
    constraints = meta.constraints
    for c in constraints:
        if hasattr(c, 'condition'):
            print(f"  CheckConstraint: {c.name}, condition type: {type(c.condition)}")
        else:
            print(f"  Other constraint: {c.name}, type: {type(c).__name__}")
except Exception as e:
    print(f"TEST 4 FAILED: {e}")

# Test 5: Try to import and check the full ticket model
print("\nTEST 5: Full ticket model check...")
try:
    from tickets.models import Ticket
    meta = Ticket._meta
    print(f"  Ticket model meta constraints count: {len(meta.constraints)}")
    for c in meta.constraints:
        if hasattr(c, 'condition'):
            print(f"    CheckConstraint: {c.name}, condition type: {type(c.condition)}")
        else:
            print(f"    Other constraint: {c.name}, type: {type(c).__name__}")
except Exception as e:
    print(f"TEST 5 FAILED: {e}")

print("\nDone!")