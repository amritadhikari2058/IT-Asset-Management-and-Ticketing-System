#!/usr/bin/env python3
"""Add SQLite skip check to concurrency test setUp methods."""

def add_skip_to_vendor():
    """Add SQLite skip check to VendorConcurrencyTests.setUp."""
    with open('assets/test_vendors.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Find the setUp method in VendorConcurrencyTests and add skip check
    # The class starts at "class VendorConcurrencyTests(TransactionTestCase):"
    # The setUp method follows after
    
    # Add a check at the beginning of setUp that skips on SQLite
    old_setUp_pattern = """    def setUp(self):
        self.dep, self.admin, self.mgr, self.support, self.emp = _make_roles()
        self.c = APIClient()
        self.c.force_authenticate(user=self.mgr)"""
    
    new_setUp = """    def setUp(self):
        from django.db import connections
        if connections['default'].vendor == 'sqlite':
            raise SkipTest('SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.')
        self.dep, self.admin, self.mgr, self.support, self.emp = _make_roles()
        self.c = APIClient()
        self.c.force_authenticate(user=self.mgr)"""
    
    if 'def setUp(self):' in content and 'raise SkipTest' not in content:
        content = content.replace(old_setUp_pattern, new_setUp)
        with open('assets/test_vendors.py', 'w', encoding='utf-8-sig') as f:
            f.write(content)
        print("Added SQLite skip check to test_vendors.py setUp")
    else:
        print("Skip check already present or setUp not found in test_vendors.py")

def add_skip_to_asset():
    """Add SQLite skip check to AssetAssignmentConcurrencyTests.setUp."""
    with open('assets/tests.py', 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Find the setUp method in AssetAssignmentConcurrencyTests and add skip check
    old_setUp_pattern = """    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)"""
    
    new_setUp = """    def setUp(self):
        from django.db import connections
        if connections['default'].vendor == 'sqlite':
            raise SkipTest('SQLite does not support concurrent writes via ThreadPoolExecutor; requires PostgreSQL for reliable verification.')
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.e2 = User.objects.create_user(
            username="e2@x", email="e2@example.com", employee_id="E2",
            password="pw12345678", home_department=self.dep)"""
    
    if 'def setUp(self):' in content and 'raise SkipTest' not in content:
        content = content.replace(old_setUp_pattern, new_setUp)
        with open('assets/tests.py', 'w', encoding='utf-8-sig') as f:
            f.write(content)
        print("Added SQLite skip check to assets/tests.py setUp")
    else:
        print("Skip check already present or setUp not found in assets/tests.py")

if __name__ == '__main__':
    add_skip_to_vendor()
    add_skip_to_asset()
    print("\nDone!")