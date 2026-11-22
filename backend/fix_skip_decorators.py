#!/usr/bin/env python3
"""Add @skipIf decorators to SQLite-incompatible concurrency tests."""

import re

def add_skip_decorator(filepath, class_name, import_line, decorator_text):
    """Add @skipIf decorator before a test class in a Python file."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Add the connections import after the existing django.db import
    content = re.sub(
        rf'(from django\.db {import_line})',
        rf'\1\nfrom django.db import connections',
        content
    )
    
    # Add @skipIf before the class
    pattern = rf'({class_name}\(TransactionTestCase\):\n)'
    replacement = rf'''@skipIf(
    connections["default"].vendor == "sqlite",
    "SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.",
),
    {class_name}(TransactionTestCase):
'''
    content = re.sub(pattern, replacement, content, count=1)
    
    with open(filepath, 'w', encoding='utf-8-sig') as f:
        f.write(content)
    print(f"Modified {filepath}")


# Fix test_vendors.py
add_skip_decorator(
    'assets/test_vendors.py',
    'class VendorConcurrencyTests',
    r', transaction, connection',
    ''
)

# Fix assets/tests.py
add_skip_decorator(
    'assets/tests.py',
    'class AssetAssignmentConcurrencyTests',
    r', connection, transaction',
    ''
)

print("Done!")