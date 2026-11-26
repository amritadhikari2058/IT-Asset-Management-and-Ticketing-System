import os
import sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, '.')
import django
django.setup()

# Check database tables
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    count = cursor.fetchone()[0]
    print(f'Database tables count: {count}')