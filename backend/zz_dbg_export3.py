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
from rest_framework.request import Request
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import RequestFactory

from common import views as common_views

User = get_user_model()
u = User.objects.create_user(
    username="dbg3@x", email="dbg3@example.com", password=make_password("pw12345678"),
    employee_id="E7", first_name="Dbg", last_name="Three", home_department=None,
    role="it_manager")

c = APIClient()
c.force_authenticate(user=u)
resp = c.get("/api/common/exports/employees/?format=csv")
print("VIA CLIENT:", resp.status_code)

view_func = common_views.export_dataset
rf = RequestFactory()
dj_req = rf.get("/api/common/exports/employees/?format=csv")
drf_req = Request(dj_req, parsers=[], authenticators=[], negotiator=None)
drf_req.user = u
try:
    out = view_func(drf_req, dataset="employees")
    print("DIRECT CALL OK", out.status_code, out.content[:200])
except Exception:
    import traceback
    traceback.print_exc()

runner.teardown_databases(old_config)

