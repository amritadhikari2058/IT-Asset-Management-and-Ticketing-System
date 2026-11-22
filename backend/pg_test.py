import os
os.environ['DATABASE__ENGINE'] = 'django.db.backends.postgresql'
os.environ['DATABASE__NAME'] = 'ticketing_test'
os.environ['DATABASE__USER'] = 'postgres'
os.environ['DATABASE__HOST'] = 'localhost'
os.environ['DATABASE__PORT'] = '5432'
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
django.setup()

from django.db import connection
print('Database vendor:', connection.vendor)
print('Connection OK')