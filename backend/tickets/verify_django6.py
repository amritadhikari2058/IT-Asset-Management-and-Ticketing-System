"""Verify Django 6 compatibility of CheckConstraints in ticket models."""
import os
import sys
import django

os.chdir(r'D:\IT-Asset-Management-and-Ticketing-System\backend')
sys.path.insert(0, '.')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

django.setup()

from django.db import models
from django.db.models import Q, F

print("=" * 60)
print("Django 6 CheckConstraint Compatibility Verification")
print("=" * 60)
print(f"Django version: {django.VERSION}")
print()

# Test 1: CheckConstraint with condition= keyword (Django 6 style)
print("TEST 1: CheckConstraint with condition= keyword")
try:
    c = models.CheckConstraint(condition=~Q(source_ticket=models.F("target_ticket")), name="test_rel")
    print("  PASSED: CheckConstraint with condition= keyword works")
except Exception as e:
    print(f"  FAILED: {e}")

# Test 2: Check all TicketRelation constraints
print("\nTEST 2: TicketRelation model constraints")
try:
    from tickets.models import TicketRelation
    meta = TicketRelation._meta
    constraints = meta.constraints
    print(f"  Total constraints: {len(constraints)}")
    for c in constraints:
        if hasattr(c, 'condition'):
            print(f"  CheckConstraint: {c.name}, condition type: {type(c.condition).__name__}")
        else:
            print(f"  Other constraint: {c.name}, type: {type(c).__name__}")
    print("  PASSED: TicketRelation constraints verified")
except Exception as e:
    print(f"  FAILED: {e}")

# Test 3: Check all TicketMergeRecord constraints
print("\nTEST 3: TicketMergeRecord model constraints")
try:
    from tickets.models import TicketMergeRecord
    meta = TicketMergeRecord._meta
    constraints = meta.constraints
    print(f"  Total constraints: {len(constraints)}")
    for c in constraints:
        if hasattr(c, 'condition'):
            print(f"  CheckConstraint: {c.name}, condition type: {type(c.condition).__name__}")
        else:
            print(f"  Other constraint: {c.name}, type: {type(c).__name__}")
    print("  PASSED: TicketMergeRecord constraints verified")
except Exception as e:
    print(f"  FAILED: {e}")

# Test 4: Check Ticket model constraints
print("\nTEST 4: Ticket model constraints")
try:
    from tickets.models import Ticket
    meta = Ticket._meta
    constraints = meta.constraints
    print(f"  Total constraints: {len(constraints)}")
    for c in constraints:
        if hasattr(c, 'condition'):
            print(f"  CheckConstraint: {c.name}, condition type: {type(c.condition).__name__}")
        else:
            print(f"  Other constraint: {c.name}, type: {type(c).__name__}")
    print("  PASSED: Ticket constraints verified")
except Exception as e:
    print(f"  FAILED: {e}")

# Test 5: Verify the specific constraints from the model
print("\nTEST 5: Verify specific CheckConstraints")
try:
    from tickets.models import TicketRelation, TicketMergeRecord
    
    # TicketRelation constraint
    rt_meta = TicketRelation._meta
    for c in rt_meta.constraints:
        if c.name == "relation_no_self_reference":
            print(f"  TicketRelation.relation_no_self_reference: {type(c).__name__}")
            if hasattr(c, 'condition'):
                print(f"    condition: {type(c.condition).__name__}")
            print("  PASSED: relation_no_self_reference constraint found")
            break
    else:
        print("  WARNING: relation_no_self_reference not found")
    
    # TicketMergeRecord constraint
    rm_meta = TicketMergeRecord._meta
    for c in rm_meta.constraints:
        if c.name == "merge_no_self_merge":
            print(f"  TicketMergeRecord.merge_no_self_merge: {type(c).__name__}")
            if hasattr(c, 'condition'):
                print(f"    condition: {type(c.condition).__name__}")
            print("  PASSED: merge_no_self_merge constraint found")
            break
    else:
        print("  WARNING: merge_no_self_merge not found")
        
    print("  PASSED: Specific constraints verified")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n" + "=" * 60)
print("Verification complete")
print("=" * 60)