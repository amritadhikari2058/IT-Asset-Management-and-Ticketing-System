"""Check Django migrations for CheckConstraint compatibility."""
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
print("Django Migrations CheckConstraint Compatibility")
print("=" * 60)
print(f"Django version: {django.VERSION}")
print()

# Check migration files for CheckConstraint usage
import importlib
import os as os_path

migrations_dir = r'D:\IT-Asset-Management-and-Ticketing-System\backend\tickets\migrations'
if os_path.exists(migrations_dir):
    print(f"Checking migrations in: {migrations_dir}")
    print()
    
    # List migration files
    migration_files = [f for f in os_path.listdir(migrations_dir) if f.startswith('00') and f.endswith('.py')]
    print(f"Found {len(migration_files)} migration files")
    print()
    
    for mf in migration_files:
        file_path = os_path.join(migrations_dir, mf)
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check for CheckConstraint usage
            import re
            check_constraints = re.finditer(
                r'models\.CheckConstraint\([^)]+\)', content)
            
            constraint_count = len(list(check_constraints))
            if constraint_count > 0:
                print(f"  {mf}: {constraint_count} CheckConstraint(s) found")
                
                # Show the CheckConstraint lines
                # Reset regex position
                check_constraints = re.finditer(
                    r'models\.CheckConstraint\([^)]+\)', content)
                
                for i, cc in enumerate(check_constraints, 1):
                    line_num = content[:cc.start()].count('\n') + 1
                    # Get the line
                    line_start = content.rfind('\n', 0, cc.start()) + 1
                    line_end = content.find('\n', cc.end())
                    if line_end == -1:
                        line_end = len(content)
                    line = content[line_start:line_end].strip()
                    print(f"    {i}. {line[:100]}...")
            else:
                print(f"  {mf}: No CheckConstraints found")
        except Exception as e:
            print(f"  {mf}: Error reading - {e}")
else:
    print(f"Migrations directory not found: {migrations_dir}")

print("\n" + "=" * 60)
print("Migration check complete")
print("=" * 60)