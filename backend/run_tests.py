#!/usr/bin/env python
import os
import sys

sys.path.insert(0, r'E:\OneDrive\Desktop\Ticket and Asset Management System\backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_test'

import django
django.setup()

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=2)
failures, errors = runner.run_test_labels(
    ['accounts.tests'],
    extra=None,
    pattern='test_*.py',
    test_modules=None,
)

print(f'\n=== Test Results ===')
print(f'Failures: {failures}')
print(f'Errors: {errors}')
sys.exit(0 if not failures and not errors else 1)