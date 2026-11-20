#!/usr/bin/env python
"""Check Django system status."""
import os
import sys

sys.path.insert(0, '.')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
django.setup()

from django.core.management import call_command

print("Running Django system check...")
call_command('check')
print("Done.")