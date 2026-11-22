#!/usr/bin/env python
import os
import sys

# Set PostgreSQL environment variables
os.environ['DATABASE__ENGINE'] = 'django.db.backends.postgresql'
os.environ['DATABASE__NAME'] = 'ticketing_test'
os.environ['DATABASE__USER'] = 'postgres'
os.environ['DATABASE__HOST'] = 'localhost'
os.environ['DATABASE__PORT'] = '5432'
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
django.setup()

from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=2)

from tickets.test_bulk_import_scalability import TicketBulkImportScalabilityTests
suite = django.test.runner.DiscoverRunner().test_loader.loadTestsFromTestCase(TicketBulkImportScalabilityTests)
result = runner.run_suite(suite)

print('\\n=== BENCHMARK RESULTS ===')
print(f'Tests run: {result.testsRun}')
print(f'Failures: {len(result.failures)}')
print('Errors: {len(result.errors)}')
for test, traceback in result.failures:
    print(f'FAILURE: {test._testMethodName}')
for test, traceback in result.errors:
    print(f'ERROR: {test._testMethodName}')
    
print('\\n=== DONE ===')