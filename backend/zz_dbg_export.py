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
from accounts.tests import auth, make_users
from django.test import override_settings

with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
    dep, admin, mgr, emp = make_users()
    c = APIClient()
    auth(c, mgr)
    res = c.get("/api/common/exports/employees/?format=csv")
    print("STATUS", res.status_code)
    print("DATA", getattr(res, "data", None))
    print("CONTENT-TYPE", res.get("Content-Type"))
    print("DISP", res.get("Content-Disposition"))

runner.teardown_databases(old_config)

