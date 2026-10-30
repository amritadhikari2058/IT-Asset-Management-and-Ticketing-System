p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
old = """from common.permissions import IsSystemAdmin, is_system_admin
from common.serializers import (
    AuditLogSerializer, NotificationSerializer, RecycleBinEntrySerializer,
)
"""
new = """from common.permissions import IsSystemAdmin, is_system_admin
from common.serializers import (
    AuditLogSerializer, NotificationSerializer, RecycleBinEntrySerializer,
)
from common.exports import EXPORT_RENDERERS
"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")
