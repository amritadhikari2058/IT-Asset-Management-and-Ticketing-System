#!/usr/bin/env python3
"""Fix SkipTest import in test files."""

def fix_vendor():
    with open('assets/test_vendors.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Add import for SkipTest if not present
    if 'from django.test import' in content and 'SkipTest' not in content:
        # Add SkipTest to the existing from django.test import line
        content = content.replace(
            'from django.test import TestCase, TransactionTestCase, override_settings',
            'from django.test import SkipTest, TestCase, TransactionTestCase, override_settings'
        )
    elif 'from django.test import TestCase' in content:
        # Try to find and update
        pass
    
    with open('assets/test_vendors.py', 'w', encoding='utf-8-sig') as f:
        f.write(content)
    
    print("Fixed vendor import")

def fix_asset():
    with open('assets/tests.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    if 'from django.test import' in content and 'SkipTest' not in content:
        content = content.replace(
            'from django.test import TestCase, TransactionTestCase, override_settings',
            'from django.test import SkipTest, TestCase, TransactionTestCase, override_settings'
        )
    
    with open('assets/tests.py', 'w', encoding='utf-8-sig') as f:
        f.write(content)
    
    print("Fixed asset import")

if __name__ == '__main__':
    fix_vendor()
    fix_asset()
    print("\nDone!")