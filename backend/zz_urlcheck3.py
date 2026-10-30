import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.urls import get_resolver, resolve

r = get_resolver()
for u in [
    "/api/common/exports/employees/",
    "/api/common/exports/assets/",
    "/api/common/data-integrity/",
]:
    try:
        m = resolve(u)
        print("RESOLVE OK", u, m.view_name, m.kwargs)
    except Exception as e:
        print("RESOLVE FAIL", u, type(e).__name__, e)

