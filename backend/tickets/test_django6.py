import os
import sys
os.chdir(r'D:\IT-Asset-Management-and-Ticketing-System\backend')
sys.path.insert(0, '.')

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import models
from django.db.models import Q, F

# Test 1: CheckConstraint with condition= keyword
try:
    c = models.CheckConstraint(condition=~Q(source_ticket=models.F("target_ticket")), name="test_rel")
    print("TEST 1 PASSED: CheckConstraint with condition= keyword works")
except Exception as e:
    print(f"TEST 1 FAILED: {e}")

# Test 2: CheckConstraint with check= positional (old style)
try:
    c = models.CheckConstraint(~Q(source_ticket=models.F("target_ticket")), name="test_rel_old")
    print("TEST 2 PASSED: CheckConstraint with check= positional works")
except Exception as e:
    print(f"TEST 2 FAILED: {e}")

# Test 3: Check all ticket model constraints
from tickets.models import TicketRelation, TicketMergeRecord
print("\nTEST 3: Checking TicketRelation constraints...")
try:
    meta = TicketRelation._meta
    constraints = meta.constraints
    for c in constraints:
        print(f"  Constraint: {c.name}, type: {type(c).__name__}")
except Exception as e:
    print(f"TEST 3 FAILED: {e}")

print("\nTEST 4: Checking TicketMergeRecord constraints...")
try:
    meta = TicketMergeRecord._meta
    constraints = meta.constraints
    for c in constraints:
        print(f"  Constraint: {c.name}, type: {type(c).__name__}")
except Exception as e:
    print(f"TEST 4 FAILED: {e}")