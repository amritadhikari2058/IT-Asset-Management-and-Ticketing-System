import os
import sys

os.chdir(r'D:\IT-Asset-Management-and-Ticketing-System\backend')
sys.path.insert(0, '.')

import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# Fix for test server host header
from django.conf import settings
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']

django.setup()

from django.test.runner import DiscoverRunner
runner = DiscoverRunner(verbosity=2)
# Run all BulkAndHistoryTests
suite = runner.test_loader.loadTestsFromTestCase(
    runner.test_loader.loadTestsFromName(
        'tickets.tests.BulkAndHistoryTests')._Tests__bases__[0] if hasattr(runner.test_loader.loadTestsFromName(
            'tickets.tests.BulkAndHistoryTests'), '_Tests__bases__') else None)
# Simpler: just load and run the test case class
from tickets.tests import BulkAndHistoryTests
suite = runner.test_loader.loadTestsFromTestCase(BulkAndHistoryTests)
runner.run_suite(suite)