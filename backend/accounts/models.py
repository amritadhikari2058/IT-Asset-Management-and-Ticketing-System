"""Accounts: Department + custom email-login User.

Design decisions (confirm if anything looks off):
- Single custom User carries role + employee_id + home_department.
  No separate Employee profile table -> fewer joins, simpler bulk import
  keyed on employee_id, and one place for deactivation vs soft-deletion.
- Deactivation (is_active=False) is SEPARATE from soft deletion
  (is_deleted=True) per your spec. Deactivated users keep history.
- Ticket-creation right is an explicit flag (can_create_tickets) so bulk
  employee updates never silently flip roles/permissions.
"""
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.utils import timezone


class DepartmentQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    def delete(self):
        # Bulk delete() soft-deletes; real removal only via hard_delete().
        return self.alive().update(
            is_deleted=True, deleted_at=timezone.now(), deletion_reason=""
        )

    def hard_delete(self):
        return super().delete()


class DepartmentManager(models.Manager):
    def get_queryset(self):
        return DepartmentQuerySet(self.model, using=self._db).filter(
            is_deleted=False
        )

    def with_deleted(self):
        return DepartmentQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return DepartmentQuerySet(self.model, using=self._db).filter(
            is_deleted=True
        )


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True, default="")
    head = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="headed_departments",
    )
    is_active = models.BooleanField(default=True)
    # soft-deletion fields (kept local to avoid M2M clash on deleted_by
    # related_name with common.SoftDeleteModel)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="departments_deleted",
    )
    deletion_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DepartmentManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def soft_delete(self, by_user=None, reason=""):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.deletion_reason = reason or ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.deletion_reason = ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def delete(self, using=None, keep_parents=False, by_user=None, reason=""):
        self.soft_delete(by_user=by_user, reason=reason or "")
        return (1, {"accounts.Department": 1})

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)


class UserQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    def delete(self):
        return self.alive().update(
            is_deleted=True, deleted_at=timezone.now(), deletion_reason=""
        )

    def hard_delete(self):
        return super().delete()


class UserManager(DjangoUserManager):
    def get_queryset(self):
        return UserQuerySet(self.model, using=self._db).filter(
            is_deleted=False
        )

    def with_deleted(self):
        return UserQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return UserQuerySet(self.model, using=self._db).filter(
            is_deleted=True
        )


class User(AbstractUser):
    """Email-login user. username kept for admin compat; email is unique."""

    ROLE_CHOICES = [
        ("system_admin", "System Admin"),
        ("it_manager", "IT Manager"),
        ("it_support", "IT Support"),
        ("employee", "Employee"),
    ]

    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    employee_id = models.CharField(max_length=30, unique=True)
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="employee"
    )
    home_department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
    phone = models.CharField(max_length=30, blank=True, default="")
    job_title = models.CharField(max_length=100, blank=True, default="")
    can_create_tickets = models.BooleanField(default=True)
    receive_ticket_emails = models.BooleanField(default=True)
    # Self-service opt-out for ticket-event emails ONLY. Defaults True so
    # existing rows and new users keep current behavior. Never gates
    # verification / password-reset emails, in-app notifications, roles,
    # or bulk flows (none of those paths write this field).

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users_deleted",
    )
    deletion_reason = models.TextField(blank=True, default="")

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "employee_id"]

    class Meta:
        ordering = ["employee_id"]
        permissions = [
            ("hard_delete_user", "Can permanently delete users"),
            ("restore_user", "Can restore soft-deleted users"),
        ]

    def __str__(self):
        return f"{self.employee_id} - {self.email} ({self.role})"

    @property
    def is_system_admin(self):
        return self.role == "system_admin" or self.is_superuser

    def soft_delete(self, by_user=None, reason=""):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user if by_user != self else None
        self.deletion_reason = reason or ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.deletion_reason = ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "deleted_by", "deletion_reason",
        ])

    def delete(self, using=None, keep_parents=False, by_user=None, reason=""):
        self.soft_delete(by_user=by_user, reason=reason or "")
        return (1, {"accounts.User": 1})

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)
