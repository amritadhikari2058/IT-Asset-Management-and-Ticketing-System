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
        from tickets.models import TicketCategory

        for name, desc in TICKET_CATEGORIES:
            TicketCategory.all_objects.get_or_create(
                name=name, defaults={"description": desc, "is_active": True})
        for name, desc in ASSET_CATEGORIES:
            AssetCategory.all_objects.get_or_create(
                name=name, defaults={"description": desc, "is_active": True})
        for name, code, desc in DEPARTMENTS:
            Department.all_objects.get_or_create(
                code=code, defaults={"name": name, "description": desc})

        eng = Department.objects.filter(code="ENG").first()
        demos = [
            ("ADM001", "admin@local", "system_admin", "admin12345"),
            ("MGR001", "manager@local", "it_manager", "manager12345"),
            ("SUP001", "support@local", "it_support", "support12345"),
            ("EMP001", "employee@local", "employee", "employee12345"),
        ]
        for eid, email, role, pwd in demos:
            user, created = User.objects.with_deleted().get_or_create(
                employee_id=eid,
                defaults={"username": email, "email": email, "role": role,
                          "home_department": eng})
            user.email = email
            user.username = email
            user.role = role
            user.home_department = eng
            user.is_active = True
            if created or not user.has_usable_password():
                user.set_password(pwd)
            user.save()
        self.stdout.write(self.style.SUCCESS(
            "Seeded ticket(7)/asset(6) categories, 3 departments, 4 demo users."))
