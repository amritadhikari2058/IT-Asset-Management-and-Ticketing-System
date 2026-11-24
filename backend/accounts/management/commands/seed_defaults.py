"""Seed default categories, departments, and demo users.

Run: python manage.py seed_defaults
Idempotent: uses get_or_create so re-runs are safe.
"""
from django.core.management.base import BaseCommand

TICKET_CATEGORIES = [
    ("Hardware", "Laptops, desktops, and components"),
    ("Software", "OS, apps, licenses, installs"),
    ("Network and Internet", "LAN, WiFi, VPN, connectivity"),
    ("Email and Accounts", "Email, logins, password resets"),
    ("Printer and Peripheral", "Printers, scanners, accessories"),
    ("Access and Permissions", "Access requests, role changes"),
    ("Other", "Anything else"),
]

ASSET_CATEGORIES = [
    ("Laptop", "Portable computers"),
    ("Desktop", "Desktop computers"),
    ("Monitor", "Displays"),
    ("Printer", "Printers and scanners"),
    ("Network Device", "Routers, switches, APs"),
    ("Furniture", "Desks, chairs"),
]

DEPARTMENTS = [
    ("Engineering", "ENG", "Product engineering"),
    ("Human Resources", "HR", "People operations"),
    ("Finance", "FIN", "Billing and payroll"),
]


class Command(BaseCommand):
    help = "Seed default categories, departments, and demo users."

    def handle(self, *args, **options):
        from accounts.models import Department, User
        from assets.models import AssetCategory
        from tickets.models import TicketCategory, TicketSLA

        for name, desc in TICKET_CATEGORIES:
            TicketCategory.all_objects.get_or_create(
                name=name, defaults={"description": desc, "is_active": True})
        for name, desc in ASSET_CATEGORIES:
            AssetCategory.all_objects.get_or_create(
                name=name, defaults={"description": desc, "is_active": True})
        for name, code, desc in DEPARTMENTS:
            Department.all_objects.get_or_create(
                code=code, defaults={"name": name, "description": desc})

        # Default SLA targets per priority (hours). Idempotent.
        for priority, hours in (
            ("critical", 4), ("high", 8), ("medium", 24), ("low", 72),
        ):
            TicketSLA.all_objects.get_or_create(
                priority=priority,
                defaults={"target_resolution_hours": hours, "is_active": True})

        eng = Department.objects.filter(code="ENG").first()
        demos = [
            ("ADM001", "admin@local", "system_admin", "admin12345"),
            ("MGR001", "manager@local", "it_manager", "manager12345"),
            ("SUP001", "support@local", "it_support", "support12345"),
            ("EMP001", "employee@local", "employee", "employee12345"),
        ]
        for eid, email, role, pwd in demos:
            # Resolve an existing row by employee_id, username, or email so
            # re-seeding repairs drifted/legacy rows instead of crashing on
            # the unique username/email constraints.
            user = (User.all_objects.filter(employee_id=eid).first()
                    or User.all_objects.filter(username=email).first()
                    or User.all_objects.filter(email=email).first())
            created = user is None
            if created:
                user = User(employee_id=eid, username=email, email=email,
                            role=role, home_department=eng)
            user.employee_id = eid
            user.username = email
            user.email = email
            user.role = role
            user.home_department = eng
            user.is_active = True
            user.is_deleted = False
            user.deleted_at = None
            user.deleted_by = None
            # Always (re)apply the documented demo password so seeded
            # credentials match README/e2e expectations after drift.
            user.set_password(pwd)
            user.save()
        self.stdout.write(self.style.SUCCESS(
            "Seeded ticket(7)/asset(6) categories, 3 departments, 4 demo users."))
