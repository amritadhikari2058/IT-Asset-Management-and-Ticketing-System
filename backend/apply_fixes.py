#!/usr/bin/env python3
"""Apply skipIf decorators to concurrency tests."""

import sys

def apply_vendor_fixes():
    """Fix test_vendors.py."""
    with open('assets/test_vendors.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Add connections import after the existing django.db import
    old_import = 'from django.db import IntegrityError, transaction, connection'
    new_import = old_import + '\nfrom django.db import connections'
    content = content.replace(old_import, new_import)
    
    # Add @skipIf before VendorConcurrencyTests class
    # Find the class definition and add decorator before it
    class_marker = 'class VendorConcurrencyTests(TransactionTestCase):'
    if class_marker in content and '@skipIf' not in content:
        # Insert the @skipIf decorator before the class
        decorator = '''\n@skipIf(
    connections["default"].vendor == "sqlite",
    "SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.",
),
'''
        # Find the position right before the class line
        pos = content.find(class_marker)
        if pos >= 0:
            # Insert decorator before the class
            content = content[:pos] + decorator + content[pos:]
    
    with open('assets/test_vendors.py', 'w', encoding='utf-8-sig') as f:
        f.write(content)
    
    print("Applied vendor fixes")

def apply_asset_fixes():
    """Fix assets/tests.py."""
    with open('assets/tests.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Add connections import
    old_import = 'from django.db import IntegrityError, connection, transaction'
    new_import = old_import + '\nfrom django.db import connections'
    content = content.replace(old_import, new_import)
    
    # Add @skipIf before AssetAssignmentConcurrencyTests class
    class_marker = 'class AssetAssignmentConcurrencyTests(TransactionTestCase):'
    if class_marker in content and '@skipIf' not in content:
        decorator = '''\n@skipIf(
    connections["default"].vendor == "sqlite",
    "SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.",
),
'''
        pos = content.find(class_marker)
        if pos >= 0:
            content = content[:pos] + decorator + content[pos:]
    
    with open('assets/tests.py', 'w', encoding='utf-8-sig') as f:
        f.write(content)
    
    print("Applied asset fixes")

if __name__ == '__main__':
    apply_vendor_fixes()
    apply_asset_fixes()
    print("\nAll fixes applied!")