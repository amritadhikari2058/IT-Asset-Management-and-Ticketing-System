import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test.utils import setup_test_environment
from django.test.runner import DiscoverRunner

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from rest_framework.views import APIView
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

orig_dispatch = APIView.dispatch


def traced_dispatch(self, request, *args, **kwargs):
    print("DISPATCH ENTER", type(self).__name__, request.method, args, kwargs)
    try:
        resp = orig_dispatch(self, request, *args, **kwargs)
        print("DISPATCH EXIT", type(self).__name__, resp.status_code)
        return resp
    except Exception as exc:
        print("DISPATCH EXC", type(self).__name__, repr(exc))
        raise


APIView.dispatch = traced_dispatch

User = get_user_model()
u = User.objects.create_user(
    username="dbg5@x", email="dbg5@example.com", password=make_password("pw12345678"),
    employee_id="E5", first_name="Dbg", last_name="Five", home_department=None,
    role="it_manager")

c = APIClient()
c.force_authenticate(user=u)
r = c.get("/api/common/exports/assets/?format=xlsx")
print("EXPORT ASSETS:", r.status_code)

runner.teardown_databases(old_config)

