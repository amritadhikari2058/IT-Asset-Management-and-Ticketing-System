import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from accounts.models import Department, User


department = Department.objects.get(pk=1)
users = [
    ("admin@local", "admin12345", "system_admin", "ADM001"),
    ("employee@local", "employee123", "employee", "EMP001"),
    ("employee1@local", "employee123", "employee", "E2E001"),
    ("employee2@local", "employee123", "employee", "E2E002"),
    ("itstaff@local", "itstaff123", "it_support", "E2E003"),
]

for email, password, role, employee_id in users:
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={"username": email, "employee_id": employee_id, "role": role},
    )
    user.username = email
    user.role = role
    user.home_department = department
    user.set_password(password)
    user.save()

print("Prepared isolated E2E users:", ", ".join(email for email, *_ in users))
