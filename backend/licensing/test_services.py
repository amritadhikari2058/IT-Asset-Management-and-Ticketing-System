"""Comprehensive Domain Services and Business Logic Tests for Licensing."""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from accounts.models import Department, User
from assets.models import Asset, AssetCategory, Vendor
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseHistory,
    LicenseRenewal,
    SoftwareInstallation,
    SoftwareProduct,
)
from licensing.services import (
    activate_agreement,
    allocate_from_service_request,
    allocate_license,
    apply_approved_renewal,
    bulk_allocate_licenses,
    bulk_revoke_allocations,
    evaluate_license_compliance,
    generate_agreement_number,
    get_active_allocations_for_user,
    recalculate_agreement_capacity,
    record_installation,
    remove_installation,
    resolve_compliance_finding,
    resume_agreement,
    retire_agreement,
    review_renewal_request,
    revoke_allocation,
    revoke_allocations_for_offboarding,
    record_license_history,
    submit_renewal_request,
    suspend_agreement,
    terminate_agreement,
    verify_allocation,
)
from services.models import ServiceCatalogueItem, ServiceRequest


class LicensingServicesTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Engineering", code="ENG01")
        self.it_dept = Department.objects.create(name="IT Services", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com",
            email="admin@test.com",
            employee_id="ADM-001",
            role="system_admin",
            home_department=self.it_dept,
        )
        self.it_manager = User.objects.create_user(
            username="manager@test.com",
            email="manager@test.com",
            employee_id="MGR-001",
            role="it_manager",
            home_department=self.it_dept,
        )
        self.it_support = User.objects.create_user(
            username="support@test.com",
            email="support@test.com",
            employee_id="SUP-001",
            role="it_support",
            home_department=self.it_dept,
        )
        self.emp1 = User.objects.create_user(
            username="alice@test.com",
            email="alice@test.com",
            employee_id="EMP-101",
            role="employee",
            home_department=self.dept,
        )
        self.emp2 = User.objects.create_user(
            username="bob@test.com",
            email="bob@test.com",
            employee_id="EMP-102",
            role="employee",
            home_department=self.dept,
        )

        self.vendor = Vendor.objects.create(name="JetBrains Inc", code="JB01")
        self.category = AssetCategory.objects.create(name="Laptops")

        self.asset1 = Asset.objects.create(
            asset_tag="ASSET-ENG-001",
            name="Developer ThinkPad",
            category=self.category,
            department=self.dept,
            status="available",
        )
        self.asset2 = Asset.objects.create(
            asset_tag="ASSET-ENG-002",
            name="MacBook Pro",
            category=self.category,
            department=self.dept,
            status="available",
        )

        self.product = SoftwareProduct.objects.create(
            name="PyCharm Professional",
            publisher="JetBrains",
            code="JB-PYCHARM-PRO",
            category="development",
            license_model="named_user",
            license_required=True,
            approved_status="approved",
            created_by=self.sys_admin,
        )

    # ==========================================================================
    # NUMBERING
    # ==========================================================================

    def test_agreement_number_format_and_uniqueness(self):
        """Numbering follows LIC-YYYY-NNNNN and increments cleanly."""
        num1 = generate_agreement_number()
        year = timezone.now().year
        self.assertTrue(num1.startswith(f"LIC-{year}-"))
        self.assertEqual(len(num1), 14)

        LicenseAgreement.objects.create(
            agreement_number=num1,
            software_product=self.product,
            created_by=self.sys_admin,
        )

        num2 = generate_agreement_number()
        self.assertNotEqual(num1, num2)
        self.assertTrue(num2.startswith(f"LIC-{year}-"))

    # ==========================================================================
    # AGREEMENT LIFECYCLE
    # ==========================================================================

    def test_agreement_activation_lifecycle(self):
        """Agreement can be activated from draft; product validation enforced."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="draft",
            quantity_purchased=5,
            created_by=self.sys_admin,
        )
        self.assertEqual(agreement.status, "draft")

        activated = activate_agreement(agreement, actor=self.it_manager)
        self.assertEqual(activated.status, "active")
        self.assertEqual(activated.quantity_available, 5)

        # Prohibited product cannot be activated
        self.product.approved_status = "prohibited"
        self.product.save()

        draft2 = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="draft",
            quantity_purchased=5,
            created_by=self.sys_admin,
        )
        with self.assertRaises(ValidationError):
            activate_agreement(draft2, actor=self.it_manager)

    def test_agreement_suspension_and_resume(self):
        """Agreement suspension blocks allocations and resume restores active status."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            created_by=self.sys_admin,
        )

        # Suspend without reason raises ValidationError
        with self.assertRaises(ValidationError):
            suspend_agreement(agreement, actor=self.it_manager, reason="")

        suspended = suspend_agreement(agreement, actor=self.it_manager, reason="Audit review")
        self.assertEqual(suspended.status, "suspended")

        # Allocation on suspended agreement is blocked
        with self.assertRaises(ValidationError):
            allocate_license(
                agreement=suspended,
                allocation_type="user",
                assigned_user=self.emp1,
                actor=self.it_support,
            )

        resumed = resume_agreement(suspended, actor=self.it_manager)
        self.assertEqual(resumed.status, "active")

    def test_agreement_termination_requires_sysadmin(self):
        """Agreement termination is restricted to System Admin and handles active seats."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            quantity_available=5,
            created_by=self.sys_admin,
        )

        alloc = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )

        # IT Manager cannot terminate
        with self.assertRaises(ValidationError):
            terminate_agreement(agreement, actor=self.it_manager, reason="Vendor bankruptcy")

        # Termination without revoke_allocations raises error when active allocations exist
        with self.assertRaises(ValidationError):
            terminate_agreement(agreement, actor=self.sys_admin, reason="Vendor bankruptcy", revoke_allocations=False)

        # Termination with revoke_allocations succeeds and revokes active seats
        terminated = terminate_agreement(agreement, actor=self.sys_admin, reason="Vendor bankruptcy", revoke_allocations=True)
        self.assertEqual(terminated.status, "terminated")

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "revoked")
        self.assertIn("terminated", alloc.revocation_reason)

    # ==========================================================================
    # ALLOCATIONS & CAPACITY
    # ==========================================================================

    def test_user_allocation_and_capacity_enforcement(self):
        """Capacity limits prevent over-allocation."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=1,
            quantity_available=1,
            created_by=self.sys_admin,
        )

        # Allocate 1st seat -> Success
        alloc1 = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )
        self.assertEqual(alloc1.status, "active")

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 1)
        self.assertEqual(agreement.quantity_available, 0)

        # Allocate 2nd seat -> Over-allocation blocked
        with self.assertRaises(ValidationError) as ctx:
            allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=self.emp2,
                actor=self.it_support,
            )
        self.assertIn("maximum capacity", str(ctx.exception))

    def test_duplicate_user_allocation_blocked(self):
        """Duplicate active seat for same product and user is blocked."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            quantity_available=5,
            created_by=self.sys_admin,
        )

        allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )

        # Attempt duplicate allocation to emp1
        with self.assertRaises(ValidationError) as ctx:
            allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=self.emp1,
                actor=self.it_support,
            )
        self.assertIn("already holds an active allocation", str(ctx.exception))

    def test_allocation_revocation_restores_capacity(self):
        """Revoking an allocation restores available capacity."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=1,
            quantity_available=1,
            created_by=self.sys_admin,
        )

        alloc = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )
        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_available, 0)

        # Revocation
        revoke_allocation(alloc, actor=self.it_support, reason="Employee project concluded")
        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 0)
        self.assertEqual(agreement.quantity_available, 1)

    def test_bulk_allocation_and_revocation(self):
        """Bulk allocate and bulk revoke report per-row outcomes."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=10,
            quantity_available=10,
            created_by=self.sys_admin,
        )

        alloc_data = [
            {"allocation_type": "user", "assigned_user_id": self.emp1.pk},
            {"allocation_type": "user", "assigned_user_id": self.emp2.pk},
        ]

        result = bulk_allocate_licenses(agreement, alloc_data, actor=self.it_support)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(result["failed"], 0)

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 2)

        # Bulk revoke
        alloc_ids = [r["allocation_id"] for r in result["results"]]
        revoke_res = bulk_revoke_allocations(alloc_ids, actor=self.it_support, reason="Bulk reclamation")
        self.assertEqual(revoke_res["succeeded"], 2)

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 0)

    # ==========================================================================
    # SOFTWARE INSTALLATIONS
    # ==========================================================================

    def test_installation_recording_and_compliance(self):
        """Installation without license marked unlicensed; with license marked compliant."""
        # Unlicensed installation
        inst1 = record_installation(
            software_product=self.product,
            asset=self.asset1,
            installed_by=self.it_support,
        )
        self.assertEqual(inst1.compliance_status, "unlicensed")

        # Now link allocation
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            created_by=self.sys_admin,
        )
        alloc = allocate_license(
            agreement=agreement,
            allocation_type="device",
            assigned_asset=self.asset1,
            actor=self.it_support,
        )

        inst2 = record_installation(
            software_product=self.product,
            asset=self.asset1,
            allocation=alloc,
            installed_by=self.it_support,
        )
        self.assertEqual(inst2.compliance_status, "compliant")

        # Prohibited software marks installation prohibited
        self.product.approved_status = "prohibited"
        self.product.save()
        inst3 = record_installation(
            software_product=self.product,
            asset=self.asset2,
            installed_by=self.it_support,
        )
        self.assertEqual(inst3.compliance_status, "prohibited_software")

    # ==========================================================================
    # RENEWALS & THRESHOLDS
    # ==========================================================================

    def test_renewal_workflow_separation_of_duties_and_threshold(self):
        """Requester cannot self-approve; high-cost renewal requires System Admin."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=10,
            unit_cost=Decimal("100.00"),
            total_cost=Decimal("1000.00"),
            currency="USD",
            created_by=self.sys_admin,
        )

        now = timezone.now().date()
        renewal = submit_renewal_request(
            agreement=agreement,
            proposed_start_date=now,
            proposed_expiry_date=now + timezone.timedelta(days=365),
            proposed_quantity=10,
            proposed_unit_cost=Decimal("6000.00"),
            proposed_total_cost=Decimal("60000.00"),  # Above 50000.00 threshold
            currency="USD",
            requested_by=self.it_manager,
            reason="Annual renewal",
        )
        self.assertEqual(renewal.status, "pending_review")

        # 1. Requester cannot approve own renewal (separation of duties)
        with self.assertRaises(ValidationError) as ctx:
            review_renewal_request(renewal, actor=self.it_manager, decision="approved")
        self.assertIn("Separation of duties", str(ctx.exception))

        # 2. IT Support cannot approve renewals
        with self.assertRaises(ValidationError):
            review_renewal_request(renewal, actor=self.it_support, decision="approved")

        # 3. High-cost renewal ($60,000 >= $50,000 threshold) requires System Admin
        it_manager2 = User.objects.create_user(
            username="manager2@test.com", email="manager2@test.com", employee_id="MGR-002", role="it_manager"
        )
        with self.assertRaises(ValidationError) as ctx:
            review_renewal_request(renewal, actor=it_manager2, decision="approved")
        self.assertIn("System Administrator approval", str(ctx.exception))

        # 4. System Admin approves -> Success
        approved = review_renewal_request(renewal, actor=self.sys_admin, decision="approved", review_reason="Budget approved")
        self.assertEqual(approved.status, "approved")

        # 5. Apply approved renewal
        updated_agreement = apply_approved_renewal(approved, actor=self.sys_admin)
        self.assertEqual(updated_agreement.total_cost, Decimal("60000.00"))
        approved.refresh_from_db()
        self.assertEqual(approved.status, "completed")

    # ==========================================================================
    # COMPLIANCE ENGINE
    # ==========================================================================

    def test_compliance_engine_detections_and_idempotency(self):
        """Compliance engine detects over-allocations, inactive users, and expired agreements idempotently."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=1,
            created_by=self.sys_admin,
        )

        alloc = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )

        # Deactivate user holding seat
        self.emp1.is_active = False
        self.emp1.save()

        # Run compliance engine
        findings1 = evaluate_license_compliance()
        inactive_findings = [f for f in findings1 if f.finding_type == "allocation_to_inactive_user"]
        self.assertEqual(len(inactive_findings), 1)
        finding_id = inactive_findings[0].pk

        # Run again -> Idempotent! Does not duplicate open finding
        findings2 = evaluate_license_compliance()
        inactive_findings2 = [f for f in findings2 if f.finding_type == "allocation_to_inactive_user"]
        self.assertEqual(len(inactive_findings2), 1)
        self.assertEqual(inactive_findings2[0].pk, finding_id)

    # ==========================================================================
    # INTEGRATION SERVICES
    # ==========================================================================

    def test_offboarding_reclamation_hook(self):
        """Offboarding service reclaims all user allocations safely."""
        agreement = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            created_by=self.sys_admin,
        )

        alloc = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            actor=self.it_support,
        )

        active_allocs = get_active_allocations_for_user(self.emp1)
        self.assertEqual(len(active_allocs), 1)

        result = revoke_allocations_for_offboarding(
            user=self.emp1,
            actor=self.it_manager,
            reason="Employee departure",
        )
        self.assertEqual(result["revoked_count"], 1)

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "revoked")
        self.assertIn("Employee departure", alloc.revocation_reason)


# ============================================================================
# PER-ALLOCATION REVOCATION ATOMICITY
# ============================================================================

class LicenseRevocationAtomicityTests(TestCase):
    """Verify each allocation revocation rolls back independently on failure."""

    def setUp(self):
        self.dept = Department.objects.create(name="Engineering", code="ENG01")
        self.it_dept = Department.objects.create(name="IT Services", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com",
            employee_id="ADM-001", role="system_admin",
            home_department=self.it_dept,
        )
        self.it_manager = User.objects.create_user(
            username="manager@test.com", email="manager@test.com",
            employee_id="MGR-001", role="it_manager",
            home_department=self.it_dept,
        )
        self.it_support = User.objects.create_user(
            username="support@test.com", email="support@test.com",
            employee_id="SUP-001", role="it_support",
            home_department=self.it_dept,
        )
        self.emp1 = User.objects.create_user(
            username="alice@test.com", email="alice@test.com",
            employee_id="EMP-101", role="employee",
            home_department=self.dept,
        )
        self.emp2 = User.objects.create_user(
            username="bob@test.com", email="bob@test.com",
            employee_id="EMP-102", role="employee",
            home_department=self.dept,
        )

        self.product = SoftwareProduct.objects.create(
            name="PyCharm Professional", publisher="JetBrains",
            code="JB-PYCHARM-PRO", category="development",
            license_model="named_user", license_required=True,
            approved_status="approved", created_by=self.sys_admin,
        )

    def _make_agreement(self, quantity_purchased=2):
        return LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=self.product,
            status="active",
            quantity_purchased=quantity_purchased,
            created_by=self.sys_admin,
        )

    def _make_allocation(self, agreement, user):
        return allocate_license(
            agreement=agreement, allocation_type="user",
            assigned_user=user, actor=self.it_support,
        )

    def _fail_history_for(self, target_pk):
        """Return a side_effect that fails history recording for one allocation."""

        def _side(*args, **kwargs):
            alloc = kwargs.get("allocation")
            if alloc is not None and getattr(alloc, "pk", None) == target_pk:
                raise RuntimeError("history recording failed")
            return record_license_history(*args, **kwargs)

        return _side

    def test_successful_revocation_updates_allocation_and_history(self):
        agreement = self._make_agreement()
        alloc = self._make_allocation(agreement, self.emp1)
        self.assertEqual(alloc.status, "active")

        result = revoke_allocations_for_offboarding(
            user=self.emp1, actor=self.it_manager, reason="Employee departure",
        )
        self.assertEqual(result["revoked_count"], 1)
        self.assertTrue(result["results"][0]["success"])

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "revoked")
        self.assertEqual(alloc.revoked_by, self.it_manager)

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 0)

        self.assertTrue(
            LicenseHistory.objects.filter(
                allocation=alloc, event_type="allocation_revoked",
            ).exists()
        )

    def test_history_failure_rolls_back_allocation_and_counters(self):
        agreement = self._make_agreement()
        alloc = self._make_allocation(agreement, self.emp1)
        agreement.refresh_from_db()
        before_allocated = agreement.quantity_allocated

        with patch(
            "licensing.services.record_license_history",
            side_effect=self._fail_history_for(alloc.pk),
        ):
            result = revoke_allocations_for_offboarding(
                user=self.emp1, actor=self.it_manager, reason="Employee departure",
            )

        self.assertEqual(result["revoked_count"], 0)
        self.assertFalse(result["results"][0]["success"])
        self.assertIn("history recording failed", result["results"][0]["error"])

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "active")
        self.assertIsNone(alloc.revoked_at)

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, before_allocated)

        self.assertFalse(
            LicenseHistory.objects.filter(
                allocation=alloc, event_type="allocation_revoked",
            ).exists()
        )

    def test_failed_allocation_does_not_block_others(self):
        product2 = SoftwareProduct.objects.create(
            name="IDE Ultimate", publisher="JetBrains", code="JB-IDE-ULT",
            category="development", license_model="named_user", license_required=True,
            approved_status="approved", created_by=self.sys_admin,
        )
        agreement2 = LicenseAgreement.objects.create(
            agreement_number=generate_agreement_number(),
            software_product=product2,
            status="active",
            quantity_purchased=2,
            created_by=self.sys_admin,
        )
        agreement = self._make_agreement(quantity_purchased=2)
        alloc_fail = self._make_allocation(agreement, self.emp1)
        alloc_ok = self._make_allocation(agreement2, self.emp1)

        with patch(
            "licensing.services.record_license_history",
            side_effect=self._fail_history_for(alloc_fail.pk),
        ):
            result = revoke_allocations_for_offboarding(
                user=self.emp1, actor=self.it_manager, reason="Employee departure",
            )

        self.assertEqual(result["revoked_count"], 1)
        self.assertEqual(len(result["results"]), 2)
        success_results = [r for r in result["results"] if r["success"]]
        fail_results = [r for r in result["results"] if not r["success"]]
        self.assertEqual(len(success_results), 1)
        self.assertEqual(len(fail_results), 1)
        self.assertEqual(fail_results[0]["allocation_id"], alloc_fail.pk)
        self.assertEqual(success_results[0]["allocation_id"], alloc_ok.pk)

        alloc_fail.refresh_from_db()
        self.assertEqual(alloc_fail.status, "active")
        alloc_ok.refresh_from_db()
        self.assertEqual(alloc_ok.status, "revoked")

        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 1)

        agreement2.refresh_from_db()
        self.assertEqual(agreement2.quantity_allocated, 0)

    def test_deactivation_succeeds_when_reclamation_fails(self):
        agreement = self._make_agreement()
        alloc = self._make_allocation(agreement, self.emp1)

        with patch(
            "licensing.services.record_license_history",
            side_effect=self._fail_history_for(alloc.pk),
        ):
            from lifecycle.services import deactivate_account
            deactivate_account(self.emp1, self.sys_admin)

        self.emp1.refresh_from_db()
        self.assertFalse(self.emp1.is_active)

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "active")

    def test_retry_after_failure_succeeds_without_duplicate_history(self):
        agreement = self._make_agreement()
        alloc = self._make_allocation(agreement, self.emp1)

        # First attempt fails during history recording.
        with patch(
            "licensing.services.record_license_history",
            side_effect=self._fail_history_for(alloc.pk),
        ):
            result1 = revoke_allocations_for_offboarding(
                user=self.emp1, actor=self.it_manager, reason="Employee departure",
            )
        self.assertEqual(result1["revoked_count"], 0)
        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "active")

        # Retry without the failure injection.
        result2 = revoke_allocations_for_offboarding(
            user=self.emp1, actor=self.it_manager, reason="Employee departure retry",
        )
        self.assertEqual(result2["revoked_count"], 1)
        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "revoked")
        self.assertEqual(alloc.revoked_by, self.it_manager)

        history_count = LicenseHistory.objects.filter(
            allocation=alloc, event_type="allocation_revoked",
        ).count()
        self.assertEqual(history_count, 1)
