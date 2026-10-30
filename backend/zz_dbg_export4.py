import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test.utils import setup_test_environment
from django.test.runner import DiscoverRunner

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()
u = User.objects.create_user(
    username="dbg4@x", email="dbg4@example.com", password=make_password("pw12345678"),
    employee_id="E6", first_name="Dbg", last_name="Four", home_department=None,
    role="it_manager")

c = APIClient()
c.force_authenticate(user=u)
r1 = c.get("/api/common/data-integrity/")
print("INTEGRITY:", r1.status_code)
r2 = c.get("/api/common/exports/assets/?format=xlsx")
print("EXPORT ASSETS:", r2.status_code)
r3 = c.get("/api/common/notifications/")
print("NOTIF:", r3.status_code)

runner.teardown_databases(old_config)

