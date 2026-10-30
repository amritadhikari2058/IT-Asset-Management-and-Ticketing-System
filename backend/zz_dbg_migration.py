import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.apps import apps as real_apps
from django.db.models import Count

from accounts.models import User

Asset = real_apps.get_model("assets", "Asset")
Assignment = real_apps.get_model("assets", "Assignment")

print("assigned-no-holder:", list(Asset.objects.filter(status="assigned", assigned_to__isnull=True).values_list("id", "asset_tag", "status")))
print("ineligible-with-holder:", list(Asset.objects.filter(status__in=["retired", "lost"], assigned_to__isnull=False)))
print("open-no-holder:", list(Assignment.objects.filter(returned_at__isnull=True, assigned_to__isnull=True)))
print("all assets assigned:", list(Asset.objects.values_list("id", "asset_tag", "status", "assigned_to_id")))
print("all assignments:", list(Assignment.objects.values_list("id", "asset_id", "assigned_to_id", "returned_at")))
print("deleted holders:", list(User.objects.filter(is_deleted=True, assignments_received__returned_at__isnull=True)))

