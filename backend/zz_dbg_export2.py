import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test.utils import setup_test_environment
from django.test.runner import DiscoverRunner

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()
u = User.objects.create_user(
    username="dbg@x", email="dbg@example.com", password=make_password("pw12345678"),
    employee_id="E9", first_name="Dbg", last_name="User", home_department=None,
    role="it_manager")

c = Client()
c.force_login(u)
resp = c.get("/api/common/exports/employees/?format=csv")
print("STATUS", resp.status_code)
print("BODY", resp.content[:800])

runner.teardown_databases(old_config)

