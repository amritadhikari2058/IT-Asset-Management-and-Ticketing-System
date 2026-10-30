p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\urls.py"
src = open(p, encoding="utf-8").read()
new_src = '''from django.urls import path

from common.privacy_views import PrivacyErasureViewSet
from common.views import (AuditLogViewSet, NotificationViewSet,  # noqa: F401
                          data_integrity)

from rest_framework import routers

router = routers.DefaultRouter()
router.register("audit-logs", AuditLogViewSet, basename="auditlog")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("privacy-erasures", PrivacyErasureViewSet,
                basename="privacyerasure")

urlpatterns = [
    path("data-integrity/", data_integrity, name="data-integrity"),
    path("", include(router.urls)),
]
'''
open(p, "w", encoding="utf-8").write(new_src)

p2 = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src2 = open(p2, encoding="utf-8").read()
assert "from django.urls import" not in src2
src2 = src2.replace("from django.db import transaction",
                    "from django.db import transaction\nfrom django.urls import path", 1)
open(p2, "w", encoding="utf-8").write(src2)
print("urls patched")
