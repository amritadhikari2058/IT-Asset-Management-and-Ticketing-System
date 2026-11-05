"""Software Licensing, Subscription, Renewal, and Compliance Models.

Implements the complete software lifecycle:
- SoftwareProduct: Catalog of approved, restricted, prohibited, or retired products.
- LicenseAgreement: Purchased entitlements, subscriptions, contracts, and pools.
- LicenseSecret: Confidential credentials protected by an authenticated encryption boundary.
- LicenseAllocation: Assignment of entitlements to users, devices, or departments.
- SoftwareInstallation: Tracking of actual software presence and compliance state on assets.
- LicenseHistory: Immutable audit trail for all licensing events.
- LicenseDocument: Protected supporting files (contracts, invoices, certificates).
- LicenseRenewal: Governed renewal requests with role-based approval thresholds.
- LicenseComplianceFinding: Deterministic compliance and shortage detections.
"""

from decimal import Decimal
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from common.models import SoftDeleteModel


# ==============================================================================
# CHOICES
# ==============================================================================

PRODUCT_CATEGORY_CHOICES = [
    ("productivity", "Productivity"),
    ("security", "Security"),
    ("development", "Development"),
    ("database", "Database"),
    ("design", "Design"),
    ("engineering", "Engineering"),
    ("communication", "Communication"),
    ("network", "Network"),
    ("erp", "ERP"),
    ("hr", "HR"),
    ("finance", "Finance"),
    ("utility", "Utility"),
    ("operating_system", "Operating System"),
    ("other", "Other"),
]

PLATFORM_CHOICES = [
    ("windows", "Windows"),
    ("macos", "macOS"),
    ("linux", "Linux"),
    ("web", "Web / SaaS"),
    ("mobile", "Mobile"),
    ("cross_platform", "Cross-Platform"),
    ("other", "Other"),
]

LICENSE_MODEL_CHOICES = [
    ("named_user", "Named User"),
    ("device", "Device"),
    ("concurrent", "Concurrent"),
    ("site", "Site"),
    ("enterprise", "Enterprise"),
    ("volume", "Volume"),
    ("oem", "OEM"),
    ("open_source", "Open Source"),
    ("freeware", "Freeware"),
    ("trial", "Trial"),
    ("other", "Other"),
]

APPROVED_STATUS_CHOICES = [
    ("approved", "Approved"),
    ("restricted", "Restricted"),
    ("pending_review", "Pending Review"),
    ("prohibited", "Prohibited"),
    ("retired", "Retired"),
]

RISK_LEVEL_CHOICES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("critical", "Critical"),
    ("unknown", "Unknown"),
]

SUPPORT_STATUS_CHOICES = [
    ("supported", "Supported"),
    ("extended_support", "Extended Support"),
    ("end_of_support", "End of Support"),
    ("unsupported", "Unsupported"),
    ("unknown", "Unknown"),
]

AGREEMENT_TYPE_CHOICES = [
    ("perpetual", "Perpetual"),
    ("subscription", "Subscription"),
    ("trial", "Trial"),
    ("maintenance", "Maintenance"),
    ("support", "Support"),
    ("open_source", "Open Source"),
    ("freeware", "Freeware"),
    ("enterprise", "Enterprise Agreement"),
    ("other", "Other"),
]

AGREEMENT_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("active", "Active"),
    ("expiring", "Expiring"),
    ("expired", "Expired"),
    ("suspended", "Suspended"),
    ("terminated", "Terminated"),
    ("retired", "Retired"),
]

BILLING_FREQUENCY_CHOICES = [
    ("one_time", "One-Time"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("annual", "Annual"),
    ("multi_year", "Multi-Year"),
    ("other", "Other"),
]

SECRET_TYPE_CHOICES = [
    ("license_key", "License Key"),
    ("activation_code", "Activation Code"),
    ("admin_account", "Admin Account"),
    ("subscription_identifier", "Subscription Identifier"),
    ("download_credential", "Download Credential"),
    ("other", "Other"),
]

SECRET_STATUS_CHOICES = [
    ("active", "Active"),
    ("rotated", "Rotated"),
    ("revoked", "Revoked"),
    ("expired", "Expired"),
]

ALLOCATION_TYPE_CHOICES = [
    ("user", "User"),
    ("device", "Device"),
    ("department", "Department"),
    ("site", "Site"),
    ("concurrent_reservation", "Concurrent Reservation"),
]

ALLOCATION_STATUS_CHOICES = [
    ("reserved", "Reserved"),
    ("assigned", "Assigned"),
    ("active", "Active"),
    ("suspended", "Suspended"),
    ("revoked", "Revoked"),
    ("expired", "Expired"),
]

INSTALLATION_STATUS_CHOICES = [
    ("installed", "Installed"),
    ("removed", "Removed"),
    ("unknown", "Unknown"),
]

INSTALLATION_SOURCE_CHOICES = [
    ("manual", "Manual"),
    ("inventory_scan", "Inventory Scan"),
    ("service_request", "Service Request"),
    ("deployment_tool", "Deployment Tool"),
    ("other", "Other"),
]

INSTALLATION_COMPLIANCE_CHOICES = [
    ("compliant", "Compliant"),
    ("unlicensed", "Unlicensed"),
    ("over_allocated", "Over-Allocated"),
    ("expired_license", "Expired License"),
    ("prohibited_software", "Prohibited Software"),
    ("version_unsupported", "Unsupported Version"),
    ("unknown", "Unknown"),
]

HISTORY_EVENT_CHOICES = [
    ("agreement_created", "Agreement Created"),
    ("agreement_activated", "Agreement Activated"),
    ("agreement_updated", "Agreement Updated"),
    ("agreement_renewed", "Agreement Renewed"),
    ("agreement_expiring", "Agreement Expiring"),
    ("agreement_expired", "Agreement Expired"),
    ("agreement_suspended", "Agreement Suspended"),
    ("agreement_terminated", "Agreement Terminated"),
    ("agreement_retired", "Agreement Retired"),
    ("secret_added", "Secret Added"),
    ("secret_revealed", "Secret Revealed"),
    ("secret_rotated", "Secret Rotated"),
    ("secret_revoked", "Secret Revoked"),
    ("allocation_reserved", "Allocation Reserved"),
    ("allocation_assigned", "Allocation Assigned"),
    ("allocation_activated", "Allocation Activated"),
    ("allocation_suspended", "Allocation Suspended"),
    ("allocation_revoked", "Allocation Revoked"),
    ("allocation_verified", "Allocation Verified"),
    ("installation_recorded", "Installation Recorded"),
    ("installation_removed", "Installation Removed"),
    ("compliance_changed", "Compliance Changed"),
    ("renewal_review_started", "Renewal Review Started"),
    ("renewal_approved", "Renewal Approved"),
    ("renewal_rejected", "Renewal Rejected"),
    ("renewal_applied", "Renewal Applied"),
    ("renewal_cancelled", "Renewal Cancelled"),
]

DOCUMENT_TYPE_CHOICES = [
    ("agreement", "Agreement / Contract"),
    ("invoice", "Invoice"),
    ("quotation", "Quotation"),
    ("purchase_order_copy", "Purchase Order Copy"),
    ("license_certificate", "License Certificate"),
    ("support_contract", "Support Contract"),
    ("maintenance_agreement", "Maintenance Agreement"),
    ("renewal_notice", "Renewal Notice"),
    ("deployment_guide", "Deployment Guide"),
    ("compliance_evidence", "Compliance Evidence"),
]

DOCUMENT_STATUS_CHOICES = [
    ("active", "Active"),
    ("superseded", "Superseded"),
    ("archived", "Archived"),
]

RENEWAL_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("pending_review", "Pending Review"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    ("superseded", "Superseded"),
]

FINDING_TYPE_CHOICES = [
    ("over_allocated", "Over-Allocated Agreement"),
    ("unlicensed_installation", "Unlicensed Installation"),
    ("expired_agreement", "Expired License Agreement"),
    ("expiring_agreement", "Expiring License Agreement"),
    ("unused_license", "Potentially Unused License"),
    ("duplicate_user_allocation", "Duplicate User Allocation"),
    ("duplicate_device_allocation", "Duplicate Device Allocation"),
    ("prohibited_software", "Prohibited Software Detected"),
    ("unsupported_version", "Unsupported Version"),
    ("missing_documentation", "Missing Required Documentation"),
    ("renewal_overdue", "Renewal Overdue"),
    ("allocation_to_inactive_user", "Allocation to Inactive Employee"),
    ("allocation_to_retired_asset", "Allocation to Inactive/Retired Asset"),
]

SEVERITY_CHOICES = [
    ("info", "Informational"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("critical", "Critical"),
]

FINDING_STATUS_CHOICES = [
    ("open", "Open"),
    ("acknowledged", "Acknowledged"),
    ("resolved", "Resolved"),
    ("false_positive", "False Positive"),
]


def license_document_upload_to(instance, filename):
    """Generate safe, unguessable storage filename for uploaded documents."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    safe_ext = "".join(c for c in ext if c.isalnum())[:10]
    return f"license_documents/{uuid.uuid4().hex}" + (f".{safe_ext}" if safe_ext else "")


# ==============================================================================
# SOFTWARE PRODUCT
# ==============================================================================

class SoftwareProduct(SoftDeleteModel):
    """Catalog of software applications, tools, and platforms."""

    name = models.CharField(max_length=200)
    code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Unique product identifier code (e.g. MS-OFFICE-365).",
    )
    publisher = models.CharField(max_length=200, help_text="Software publisher or author.")
    vendor = models.ForeignKey(
        "assets.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="software_products",
        help_text="Optional commercial vendor or distributor.",
    )
    product_family = models.CharField(max_length=100, blank=True, default="")
    edition = models.CharField(max_length=100, blank=True, default="")
    version = models.CharField(max_length=100, blank=True, default="")
    category = models.CharField(
        max_length=50,
        choices=PRODUCT_CATEGORY_CHOICES,
        default="productivity",
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    website = models.URLField(max_length=255, blank=True, default="")
    platform = models.CharField(
        max_length=50,
        choices=PLATFORM_CHOICES,
        default="cross_platform",
    )
    license_required = models.BooleanField(
        default=True,
        help_text="Indicates whether this software requires purchased or trackable licensing.",
    )
    license_model = models.CharField(
        max_length=50,
        choices=LICENSE_MODEL_CHOICES,
        default="named_user",
    )
    approved_status = models.CharField(
        max_length=50,
        choices=APPROVED_STATUS_CHOICES,
        default="pending_review",
        db_index=True,
    )
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default="low",
    )
    support_status = models.CharField(
        max_length=30,
        choices=SUPPORT_STATUS_CHOICES,
        default="supported",
    )
    support_end_date = models.DateField(null=True, blank=True)
    end_of_life_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Internal notes for IT staff only. Never exposed to regular employees.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_software_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "publisher"]
        indexes = [
            models.Index(fields=["name"], name="sw_prod_name_idx"),
            models.Index(fields=["approved_status"], name="sw_prod_status_idx"),
            models.Index(fields=["category"], name="sw_prod_cat_idx"),
            models.Index(fields=["is_active"], name="sw_prod_active_idx"),
        ]

    def __str__(self):
        parts = [self.name]
        if self.edition:
            parts.append(self.edition)
        if self.version:
            parts.append(f"v{self.version}")
        return f"{' '.join(parts)} ({self.publisher})"

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
            if not self.code:
                self.code = None

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
            if not self.code:
                self.code = None
        super().save(*args, **kwargs)

    @property
    def can_allocate(self) -> bool:
        """Determines if new allocations may be issued for this product."""
        return (
            self.is_active
            and not self.is_deleted
            and self.approved_status not in ("prohibited", "retired")
        )


# ==============================================================================
# LICENSE AGREEMENT
# ==============================================================================

class LicenseAgreement(SoftDeleteModel):
    """Purchased software entitlement, contract, subscription, or license pool."""

    agreement_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Server-generated unique reference (e.g. LIC-2026-00001).",
    )
    software_product = models.ForeignKey(
        SoftwareProduct,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    vendor = models.ForeignKey(
        "assets.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_agreements",
    )
    procurement_purchase_order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_agreements",
    )
    procurement_purchase_order_line = models.ForeignKey(
        "procurement.PurchaseOrderItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_agreements",
    )
    agreement_type = models.CharField(
        max_length=30,
        choices=AGREEMENT_TYPE_CHOICES,
        default="subscription",
    )
    license_model = models.CharField(
        max_length=30,
        choices=LICENSE_MODEL_CHOICES,
        default="named_user",
    )
    status = models.CharField(
        max_length=30,
        choices=AGREEMENT_STATUS_CHOICES,
        default="draft",
        db_index=True,
    )
    purchase_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    renewal_date = models.DateField(null=True, blank=True, db_index=True)
    grace_period_days = models.PositiveIntegerField(
        default=0,
        help_text="Days after expiry date before the license is treated as fully non-compliant.",
    )
    auto_renew = models.BooleanField(default=False)
    renewal_notice_days = models.PositiveIntegerField(
        default=30,
        help_text="Advance notice days for renewals before expiry/renewal date.",
    )
    currency = models.CharField(max_length=10, default="USD")
    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    quantity_purchased = models.PositiveIntegerField(
        default=1,
        help_text="Total purchased seat or device capacity (ignored if unlimited).",
    )
    quantity_reserved = models.PositiveIntegerField(default=0)
    quantity_allocated = models.PositiveIntegerField(default=0)
    quantity_available = models.IntegerField(
        null=True,
        blank=True,
        help_text="Server-calculated available capacity (null for unlimited).",
    )
    concurrent_limit = models.PositiveIntegerField(
        default=0,
        help_text="Maximum allowed concurrent sessions (for concurrent models).",
    )
    maintenance_included = models.BooleanField(default=False)
    support_included = models.BooleanField(default=False)
    support_expiry_date = models.DateField(null=True, blank=True)
    contract_reference = models.CharField(max_length=100, blank=True, default="")
    invoice_reference = models.CharField(max_length=100, blank=True, default="")
    external_subscription_id = models.CharField(max_length=150, blank=True, default="")
    billing_frequency = models.CharField(
        max_length=30,
        choices=BILLING_FREQUENCY_CHOICES,
        default="annual",
    )
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_agreements",
        help_text="Department bearing the software cost or owning the pool.",
    )
    cost_center = models.CharField(max_length=100, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_license_agreements",
    )
    contract_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_license_agreements",
    )
    terms_summary = models.TextField(blank=True, default="")
    internal_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_license_agreements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agreement_number"], name="lic_agr_num_idx"),
            models.Index(fields=["status"], name="lic_agr_status_idx"),
            models.Index(fields=["expiry_date"], name="lic_agr_expiry_idx"),
            models.Index(fields=["renewal_date"], name="lic_agr_renewal_idx"),
            models.Index(fields=["software_product"], name="lic_agr_prod_idx"),
            models.Index(fields=["vendor"], name="lic_agr_vendor_idx"),
            models.Index(fields=["department"], name="lic_agr_dept_idx"),
            models.Index(fields=["owner"], name="lic_agr_owner_idx"),
        ]

    def __str__(self):
        return f"{self.agreement_number} - {self.software_product.name} ({self.status})"

    @property
    def is_unlimited(self) -> bool:
        """Determines if the agreement model provides unlimited seats."""
        return (
            self.license_model in ("site", "enterprise", "open_source", "freeware")
            or self.agreement_type in ("open_source", "freeware", "enterprise")
        )

    @property
    def utilization_percent(self):
        """Calculates current seat utilization as a percentage."""
        if self.is_unlimited:
            return None
        base = self.concurrent_limit if self.license_model == "concurrent" else self.quantity_purchased
        if not base or base <= 0:
            return 0.0
        used = self.quantity_allocated + self.quantity_reserved
        return round((used / base) * 100, 2)

    def clean(self):
        super().clean()
        if self.start_date and self.expiry_date and self.expiry_date < self.start_date:
            raise ValidationError({"expiry_date": "Expiry date cannot be earlier than start date."})
        if self.renewal_date and self.expiry_date and self.renewal_date > self.expiry_date:
            raise ValidationError({"renewal_date": "Renewal date cannot be later than expiry date."})

    def recalculate_counters(self, save=True):
        """Transactionally recalculates allocation counters from actual allocation records."""
        active_allocs = self.allocations.filter(status__in=["assigned", "active"]).count()
        reserved_allocs = self.allocations.filter(status="reserved").count()
        self.quantity_allocated = active_allocs
        self.quantity_reserved = reserved_allocs

        if self.is_unlimited:
            self.quantity_available = None
        elif self.license_model == "concurrent":
            limit = self.concurrent_limit
            used = active_allocs + reserved_allocs
            self.quantity_available = max(0, limit - used)
        else:
            purchased = self.quantity_purchased
            used = active_allocs + reserved_allocs
            self.quantity_available = max(0, purchased - used)

        if save:
            self.save(update_fields=[
                "quantity_allocated",
                "quantity_reserved",
                "quantity_available",
                "updated_at",
            ])


# ==============================================================================
# LICENSE SECRET
# ==============================================================================

class LicenseSecret(models.Model):
    """Encrypted credential or product key attached to a License Agreement."""

    agreement = models.ForeignKey(
        LicenseAgreement,
        on_delete=models.CASCADE,
        related_name="secrets",
    )
    secret_type = models.CharField(
        max_length=50,
        choices=SECRET_TYPE_CHOICES,
        default="license_key",
    )
    label = models.CharField(
        max_length=150,
        help_text="Human-readable label (e.g. Production Enterprise Key, Admin Password).",
    )
    encrypted_value = models.TextField(
        help_text="Ciphertext token. Never read or serialized in plain view.",
    )
    value_fingerprint = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Non-reversible HMAC-SHA256 fingerprint for duplicate detection.",
    )
    last_four = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Last 4 characters of the secret for operator identification.",
    )
    status = models.CharField(
        max_length=30,
        choices=SECRET_STATUS_CHOICES,
        default="active",
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_license_secrets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    last_viewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="viewed_license_secrets",
    )
    rotated_at = models.DateTimeField(null=True, blank=True)
    rotated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rotated_license_secrets",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agreement", "status"], name="lic_sec_agr_st_idx"),
            models.Index(fields=["value_fingerprint"], name="lic_sec_fgp_idx"),
        ]

    def __str__(self):
        return f"{self.label} ({self.get_secret_type_display()}) - ...{self.last_four}"


# ==============================================================================
# LICENSE ALLOCATION
# ==============================================================================

class LicenseAllocation(models.Model):
    """Assignment of a license entitlement to an employee, device, or department."""

    agreement = models.ForeignKey(
        LicenseAgreement,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    allocation_type = models.CharField(
        max_length=30,
        choices=ALLOCATION_TYPE_CHOICES,
        default="user",
        db_index=True,
    )
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="license_allocations",
    )
    assigned_asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="license_allocations",
    )
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="license_allocations",
    )
    allocation_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="External license seat ID or vendor portal assignment reference.",
    )
    status = models.CharField(
        max_length=30,
        choices=ALLOCATION_STATUS_CHOICES,
        default="assigned",
        db_index=True,
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="allocated_licenses",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    activation_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_license_activations",
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_license_allocations",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_license_allocations",
    )
    revocation_reason = models.TextField(blank=True, default="")
    expected_release_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    service_request = models.ForeignKey(
        "services.ServiceRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_allocations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["agreement", "status"], name="lic_alloc_agr_st_idx"),
            models.Index(fields=["assigned_user", "status"], name="lic_alloc_user_st_idx"),
            models.Index(fields=["assigned_asset", "status"], name="lic_alloc_asset_st_idx"),
            models.Index(fields=["department", "status"], name="lic_alloc_dept_st_idx"),
            models.Index(fields=["expected_release_date"], name="lic_alloc_release_idx"),
        ]

    def __str__(self):
        target = "unassigned"
        if self.allocation_type == "user" and self.assigned_user:
            target = f"User {self.assigned_user.email}"
        elif self.allocation_type == "device" and self.assigned_asset:
            target = f"Asset {self.assigned_asset.asset_tag}"
        elif self.allocation_type == "department" and self.department:
            target = f"Dept {self.department.code}"
        elif self.allocation_type == "concurrent_reservation":
            target = f"Concurrent {self.allocation_reference or self.pk}"
        return f"{self.agreement.agreement_number} → {target} [{self.status}]"

    def clean(self):
        super().clean()
        if self.allocation_type == "user" and not self.assigned_user:
            raise ValidationError({"assigned_user": "User allocation requires an assigned user."})
        if self.allocation_type == "device" and not self.assigned_asset:
            raise ValidationError({"assigned_asset": "Device allocation requires an assigned asset."})
        if self.allocation_type == "department" and not self.department:
            raise ValidationError({"department": "Department allocation requires a department."})


# ==============================================================================
# SOFTWARE INSTALLATION
# ==============================================================================

class SoftwareInstallation(models.Model):
    """Presence of installed software on a physical/virtual IT asset."""

    software_product = models.ForeignKey(
        SoftwareProduct,
        on_delete=models.PROTECT,
        related_name="installations",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="software_installations",
    )
    allocation = models.ForeignKey(
        LicenseAllocation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="installations",
    )
    installed_version = models.CharField(max_length=100, blank=True, default="")
    install_date = models.DateField(null=True, blank=True)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="installed_software",
    )
    detected_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=30,
        choices=INSTALLATION_STATUS_CHOICES,
        default="installed",
        db_index=True,
    )
    source = models.CharField(
        max_length=50,
        choices=INSTALLATION_SOURCE_CHOICES,
        default="manual",
    )
    is_authorized = models.BooleanField(default=True)
    compliance_status = models.CharField(
        max_length=50,
        choices=INSTALLATION_COMPLIANCE_CHOICES,
        default="compliant",
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["software_product", "asset"], name="sw_inst_prod_asset_idx"),
            models.Index(fields=["status"], name="sw_inst_status_idx"),
            models.Index(fields=["compliance_status"], name="sw_inst_comp_idx"),
            models.Index(fields=["last_seen_at"], name="sw_inst_seen_idx"),
        ]

    def __str__(self):
        return f"{self.software_product.name} on {self.asset.asset_tag} ({self.status}/{self.compliance_status})"


# ==============================================================================
# LICENSE HISTORY
# ==============================================================================

class LicenseHistory(models.Model):
    """Immutable audit trail for all licensing lifecycle actions."""

    agreement = models.ForeignKey(
        LicenseAgreement,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="history",
    )
    allocation = models.ForeignKey(
        LicenseAllocation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="history",
    )
    installation = models.ForeignKey(
        SoftwareInstallation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="licensing_history_actions",
    )
    event_type = models.CharField(
        max_length=60,
        choices=HISTORY_EVENT_CHOICES,
        db_index=True,
    )
    previous_status = models.CharField(max_length=60, blank=True, default="")
    new_status = models.CharField(max_length=60, blank=True, default="")
    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sanitized non-sensitive event details. Never stores plaintext keys or secrets.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agreement", "created_at"], name="lic_hist_agr_idx"),
            models.Index(fields=["event_type"], name="lic_hist_evt_idx"),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event_type} by {self.actor}"


# ==============================================================================
# LICENSE DOCUMENT
# ==============================================================================

class LicenseDocument(SoftDeleteModel):
    """Supporting file, contract, license certificate, or invoice copy."""

    agreement = models.ForeignKey(
        LicenseAgreement,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=50,
        choices=DOCUMENT_TYPE_CHOICES,
        default="agreement",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_license_documents",
    )
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=license_document_upload_to)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=30,
        choices=DOCUMENT_STATUS_CHOICES,
        default="active",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agreement", "status"], name="lic_doc_agr_st_idx"),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.get_document_type_display()})"


# ==============================================================================
# LICENSE RENEWAL
# ==============================================================================

class LicenseRenewal(models.Model):
    """Proposal to renew an agreement, subject to threshold approval."""

    agreement = models.ForeignKey(
        LicenseAgreement,
        on_delete=models.CASCADE,
        related_name="renewals",
    )
    previous_start_date = models.DateField(null=True, blank=True)
    previous_expiry_date = models.DateField(null=True, blank=True)
    proposed_start_date = models.DateField()
    proposed_expiry_date = models.DateField()
    proposed_quantity = models.PositiveIntegerField(default=1)
    proposed_unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    proposed_total_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(
        max_length=30,
        choices=RENEWAL_STATUS_CHOICES,
        default="draft",
        db_index=True,
    )
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_license_renewals",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_license_renewals",
    )
    requested_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True, default="")
    procurement_purchase_request = models.ForeignKey(
        "procurement.PurchaseRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_renewals",
    )
    procurement_purchase_order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_renewals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agreement", "status"], name="lic_ren_agr_st_idx"),
            models.Index(fields=["proposed_expiry_date"], name="lic_ren_exp_idx"),
        ]

    def __str__(self):
        return f"Renewal for {self.agreement.agreement_number} [{self.status}]"

    def clean(self):
        super().clean()
        if self.proposed_start_date and self.proposed_expiry_date and self.proposed_expiry_date < self.proposed_start_date:
            raise ValidationError({"proposed_expiry_date": "Proposed expiry date cannot precede proposed start date."})


# ==============================================================================
# LICENSE COMPLIANCE FINDING
# ==============================================================================

class LicenseComplianceFinding(models.Model):
    """Deterministic compliance gap, over-allocation, or renewal risk finding."""

    finding_type = models.CharField(
        max_length=60,
        choices=FINDING_TYPE_CHOICES,
        db_index=True,
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default="medium",
        db_index=True,
    )
    software_product = models.ForeignKey(
        SoftwareProduct,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compliance_findings",
    )
    agreement = models.ForeignKey(
        LicenseAgreement,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compliance_findings",
    )
    allocation = models.ForeignKey(
        LicenseAllocation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compliance_findings",
    )
    installation = models.ForeignKey(
        SoftwareInstallation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compliance_findings",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="license_compliance_findings",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="license_compliance_findings",
    )
    status = models.CharField(
        max_length=30,
        choices=FINDING_STATUS_CHOICES,
        default="open",
        db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_license_findings",
    )
    resolution_note = models.TextField(blank=True, default="")
    fingerprint = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Deterministic SHA-256 fingerprint representing the unique issue scope.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["status", "severity"], name="lic_fnd_st_sev_idx"),
            models.Index(fields=["finding_type"], name="lic_fnd_type_idx"),
            models.Index(fields=["fingerprint"], name="lic_fnd_fgp_idx"),
            models.Index(fields=["software_product"], name="lic_fnd_prod_idx"),
            models.Index(fields=["user"], name="lic_fnd_user_idx"),
            models.Index(fields=["asset"], name="lic_fnd_asset_idx"),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title} ({self.status})"
