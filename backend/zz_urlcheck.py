import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.urls import get_resolver

r = get_resolver()
for p in sorted(str(x.pattern) for x in r.url_patterns):
    print(p)
for u in ["api/common/exports/employees/", "api/common/data-integrity/", "api/common/assets/"]:
    try:
        m = r.resolve(u)
        print("RESOLVE OK", u, m.view_name)
    except Exception as e:
        print("RESOLVE FAIL", u, e)

