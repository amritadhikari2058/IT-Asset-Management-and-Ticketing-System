import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.urls import get_resolver, reverse
from django.urls import URLPattern

r = get_resolver()
seen = []

def walk(patterns, prefix=""):
    for p in patterns:
        pattern = getattr(p, "pattern", None)
        route = str(pattern) if pattern is not None else str(p)
        name = getattr(p, "name", None)
        if any(k in route for k in ("common", "exports", "data-int", "audit", "notif", "privacy")):
            seen.append((prefix + route, name))
        if hasattr(p, "url_patterns"):
            walk(p.url_patterns, prefix + (str(pattern) if pattern is not None else ""))
            prefix = prefix  # keep prefix flat for display

walk(r.url_patterns)
for s in seen:
    print(s)
print("reverse data-integrity:", reverse("data-integrity"))
print("reverse export:", reverse("export", kwargs={"dataset": "employees"}))

