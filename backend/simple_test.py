#!/usr/bin/env python
import sys
import os
os.chdir('D:/IT-Asset-Management-and-Ticketing-System/backend')

import django
from django.conf import settings

settings.configure(
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    INSTALLED_APPS=[
        'django.contrib.contenttypes',
        'django.contrib.auth',
        'monitoring',
    ],
    DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
)

django.setup()

# Run the test_models tests (skip migration due to dependency issues)
from django.test.runner import DiscoverRunner
runner = DiscoverRunner(verbosity=2, keepdb=True, interactive=False)
old_config = runner.setup_databases()
failures = runner.run_tests(['monitoring.test_models'])
runner.teardown_databases(old_config)
sys.exit(failures)