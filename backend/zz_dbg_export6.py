import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test.utils import setup_test_environment
from django.test.runner import DiscoverRunner

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from rest_framework.views import APIView as AV
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

orig_handle = AV.handle_exception


def traced_handle(self, exc):
    import traceback
    print("HANDLE_EXCEPTION", type(exc).__name__, repr(exc))
    traceback.print_exc()
    raise exc


AV.handle_exception = traced_handle

User = get_user_model()
u = User.objects.create_user(
    username="dbg6@x", email="dbg6@example.com", password=make_password("pw12345678"),
    employee_id="E4", first_name="Dbg", last_name="Six", home_department=None,
    role="it_manager")

c = APIClient()
c.force_authenticate(user=u)
r = c.get("/api/common/exports/assets/?format=xlsx")
print("EXPORT ASSETS:", r.status_code)

runner.teardown_databases(old_config)

