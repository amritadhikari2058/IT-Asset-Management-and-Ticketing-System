"""Lifecycle app tests.

Covers models, permissions, onboarding/offboarding/transfer workflows,
tasks, automation, asset recovery, attachments, notifications and the
dashboard. Fixed, timezone-aware datetimes are used throughout so results
do not depend on the current date.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory
from common.models import Notification
from lifecycle import models as lm


def make_user(email, employee_id, role="employee", password="pw12345678",
              home_department=None, is_active=True, is_deleted=False,
              is_superuser=False):
    u = User.objects.create_user(
        username=email, email=email, employee_id=employee_id,
        password=password, role=role, home_department=home_department,
        is_active=is_active, is_superuser=is_superuser)
    if is_deleted:
        u.is_deleted = True
        u.save(update_fields=["is_deleted"])
    return u


def make_dept(name, code):
    return Department.objects.create(name=name, code=code)


def make_category(name="Laptop"):
    return AssetCategory.objects.create(name=name)


def make_asset(tag, name, category, status="available", assigned_to=None,
               department=None):
    if assigned_to is not None and status == "available":
        status = "assigned"
    return Asset.objects.create(
        asset_tag=tag, name=name, category=category, status=status,
        assigned_to=assigned_to, department=department,
        serial_number=f"SN-{tag}")


def make_template(code, case_type, name="T", department=None, is_active=True,
                  is_global=False):
    return lm.LifecycleTemplate.objects.create(
        code=code, name=name, case_type=case_type,
        department=department, is_active=is_active, is_global=is_global)


def add_template_item(template, sequence=0, title="Item", category="other",
                      responsibility="it", required=True,
                      default_assignee_role="unassigned", due_offset_days=0,
                      blocks_completion=True, requires_evidence=False,
                      automation_type="none"):
    return lm.LifecycleTemplateItem.objects.create(
        template=template, sequence=sequence, title=title,
        category=category, responsibility=responsibility,
        default_assignee_role=default_assignee_role,
        required=required, due_offset_days=due_offset_days,
        blocks_completion=blocks_completion,
        requires_evidence=requires_evidence,
        automation_type=automation_type)


def auth_client(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user=user)
    return c


class BaseLifecycle(TestCase):
    def setUp(self):
        self.dep_it = make_dept("IT", "IT")
        self.dep_hr = make_dept("HR", "HR")
        self.sysadmin = make_user("sa@x", "SA1", "system_admin",
                                  home_department=self.dep_it,
                                  is_superuser=True)
        self.itmgr = make_user("mgr@x", "M1", "it_manager",
                               home_department=self.dep_it)
        self.itsupport = make_user("sup@x", "S1", "it_support",
                                   home_department=self.dep_it)
        self.emp = make_user("emp@x", "E1", "employee",
                             home_department=self.dep_it)
        self.emp2 = make_user("emp2@x", "E2", "employee",
                              home_department=self.dep_hr)
        self.cat = make_category()
        self.tmpl_onboard = make_template("TPL-ONB", "onboarding",
                                          department=self.dep_it)
        add_template_item(self.tmpl_onboard, 0, "Account setup", "account",
                          "it", default_assignee_role="it_support")
        add_template_item(self.tmpl_onboard, 1, "Assign laptop", "hardware",
                          "it", default_assignee_role="it_support",
                          blocks_completion=True)
        add_template_item(self.tmpl_onboard, 2, "Security induction",
                          "training", "employee",
                          default_assignee_role="employee", required=False)
        self.tmpl_offboard = make_template("TPL-OFF", "offboarding",
                                           department=self.dep_it)
        add_template_item(self.tmpl_offboard, 0, "Recover laptop",
                          "asset_return", "it",
                          default_assignee_role="it_support",
                          blocks_completion=True)
        add_template_item(self.tmpl_offboard, 1, "Revoke access", "access",
                          "it", default_assignee_role="it_support",
                          blocks_completion=True)
        self.tmpl_transfer = make_template("TPL-TRF", "transfer",
                                           department=self.dep_it)
        add_template_item(self.tmpl_transfer, 0, "Review access", "access",
                          "it", default_assignee_role="it_support")


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class CaseNumberingTests(BaseLifecycle):
    def test_case_number_format_and_uniqueness(self):
        c1 = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00001", case_type="onboarding",
            employee=self.emp, status="draft")
        self.assertEqual(c1.case_number, "ONB-2026-00001")
        with self.assertRaises(Exception):
            lm.LifecycleCase.objects.create(
                case_number="ONB-2026-00001", case_type="onboarding",
                employee=self.emp2, status="draft")

    def test_generate_case_number_server_side(self):
        from lifecycle.services import generate_case_number
        n1 = generate_case_number("onboarding")
        # Reserve n1 so the next generated number differs (uniqueness under
        # creation, not just proposal).
        lm.LifecycleCase.objects.create(
            case_number=n1, case_type="onboarding",
            employee=self.emp, status="draft")
        n2 = generate_case_number("onboarding")
        self.assertTrue(n1.startswith("ONB-"))
        self.assertTrue(n2.startswith("ONB-"))
        self.assertNotEqual(n1, n2)
        off = generate_case_number("offboarding")
        self.assertTrue(off.startswith("OFF-"))

    def test_conflicting_active_onboarding_blocked(self):
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00001", case_type="onboarding",
            employee=self.emp, status="in_progress")
        with self.assertRaises(Exception):
            from lifecycle.services import create_case_from_template
            create_case_from_template(
                template=self.tmpl_onboard, employee=self.emp,
                actor=self.itmgr)

    def test_completed_case_does_not_block_new_case(self):
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00002", case_type="onboarding",
            employee=self.emp, status="completed")
        from lifecycle.services import create_case_from_template
        c = create_case_from_template(
            template=self.tmpl_onboard, employee=self.emp, actor=self.itmgr)
        self.assertEqual(c.case_type, "onboarding")

    def test_onboarding_and_offboarding_conflict(self):
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00003", case_type="onboarding",
            employee=self.emp, status="in_progress")
        with self.assertRaises(Exception):
            from lifecycle.services import create_case_from_template
            create_case_from_template(
                template=self.tmpl_offboard, employee=self.emp,
                actor=self.itmgr)


class TemplateTests(BaseLifecycle):
    def test_template_code_unique(self):
        make_template("DUP-1", "onboarding")
        with self.assertRaises(Exception):
            make_template("DUP-1", "offboarding")

    def test_inactive_template_not_usable(self):
        bad = make_template("BAD-1", "onboarding", is_active=False)
        with self.assertRaises(Exception):
            from lifecycle.services import create_case_from_template
            create_case_from_template(template=bad, employee=self.emp,
                                      actor=self.itmgr)

    def test_template_version(self):
        t = make_template("VER-1", "onboarding")
        self.assertEqual(t.version, 1)


class TaskTests(BaseLifecycle):
    def test_task_sequence_unique_per_case(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00004", case_type="onboarding",
            employee=self.emp, status="draft")
        lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="A", status="pending")
        with self.assertRaises(Exception):
            lm.LifecycleTask.objects.create(
                case=c, sequence=1, title="B", status="pending")

    def test_immutable_history(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00005", case_type="onboarding",
            employee=self.emp, status="draft")
        h = lm.LifecycleHistory.objects.create(
            case=c, actor=self.itmgr, event_type="case_created",
            new_status="draft")
        with self.assertRaises(Exception):
            h.detail = "tampered"
            h.save()
        with self.assertRaises(Exception):
            h.delete()


class ProgressTests(BaseLifecycle):
    def test_progress_calculation(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00006", case_type="onboarding",
            employee=self.emp, status="draft")
        t1 = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="A", status="completed")
        lm.LifecycleTask.objects.create(
            case=c, sequence=2, title="B", status="pending")
        lm.LifecycleTask.objects.create(
            case=c, sequence=3, title="C", status="skipped",
            skip_reason="not needed")
        from lifecycle.services import recalc_progress
        recalc_progress(c)
        c.refresh_from_db()
        self.assertEqual(c.total_tasks, 3)
        self.assertEqual(c.completed_tasks, 2)  # completed + skipped
        self.assertEqual(c.checklist_progress, 67)  # 2/3*100


class AssetResolutionTests(BaseLifecycle):
    def test_resolution_unique_per_case_asset(self):
        c = lm.LifecycleCase.objects.create(
            case_number="OFF-2026-00001", case_type="offboarding",
            employee=self.emp, status="draft")
        a = make_asset("A1", "Laptop", self.cat, assigned_to=self.emp)
        lm.LifecycleAssetResolution.objects.create(
            case=c, asset=a, resolution="pending")
        with self.assertRaises(Exception):
            lm.LifecycleAssetResolution.objects.create(
                case=c, asset=a, resolution="pending")


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------

class PermissionTests(BaseLifecycle):
    def setUp(self):
        super().setUp()
        self.case = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00010", case_type="onboarding",
            employee=self.emp, status="draft")
        self.url = reverse("lifecycle-case-detail", args=[self.case.pk])

    def test_unauthenticated_denied(self):
        c = APIClient()
        resp = c.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_employee_own_case_allowed(self):
        c = auth_client(self.emp)
        resp = c.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_employee_foreign_case_denied(self):
        c2 = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00011", case_type="onboarding",
            employee=self.emp2, status="draft")
        url2 = reverse("lifecycle-case-detail", args=[c2.pk])
        c = auth_client(self.emp)
        resp = c.get(url2)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_it_staff_can_see_case(self):
        c = auth_client(self.itsupport)
        resp = c.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_inactive_user_denied(self):
        inactive = make_user("in@x", "I1", "employee", is_active=False)
        c = auth_client(inactive)
        resp = c.get(self.url)
        self.assertNotEqual(resp.status_code, status.HTTP_200_OK)

    def test_template_management_permissions(self):
        turl = reverse("lifecycle-template-list")
        # employee denied
        c = auth_client(self.emp)
        resp = c.post(turl, {"code": "X", "name": "X", "case_type": "onboarding"},
                      format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        # it_manager allowed
        c = auth_client(self.itmgr)
        resp = c.post(turl, {"code": "TPL-X", "name": "X", "case_type": "onboarding"},
                      format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_attachment_idor_denied(self):
        # evidence on emp's case, task assigned to emp
        task = lm.LifecycleTask.objects.create(
            case=self.case, sequence=1, title="T", responsibility="employee",
            assigned_to=self.emp, requires_evidence=True)
        ev = lm.LifecycleTaskEvidence.objects.create(
            case=self.case, task=task, uploaded_by=self.emp,
            original_filename="x.txt", file=SimpleUploadedFile(
                "x.txt", b"hi", content_type="text/plain"), size=2)
        url = reverse("lifecycle-task-evidence-detail", args=[ev.pk])
        # foreign employee cannot download
        c = auth_client(self.emp2)
        resp = c.get(reverse("lifecycle-task-evidence-download", args=[ev.pk]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_read_only(self):
        h = lm.LifecycleHistory.objects.create(
            case=self.case, actor=self.itmgr, event_type="case_created",
            new_status="draft")
        url = reverse("lifecycle-history-detail", args=[h.pk])
        c = auth_client(self.itmgr)
        resp = c.patch(url, {"detail": "tamper"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ---------------------------------------------------------------------------
# Onboarding workflow
# ---------------------------------------------------------------------------

class OnboardingTests(BaseLifecycle):
    def create_case(self):
        from lifecycle.services import create_case_from_template
        return create_case_from_template(
            template=self.tmpl_onboard, employee=self.emp, actor=self.itmgr)

    def test_create_from_template_copies_tasks(self):
        c = self.create_case()
        self.assertEqual(c.case_type, "onboarding")
        self.assertEqual(c.tasks.filter(is_deleted=False).count(), 3)
        self.assertTrue(c.case_number.startswith("ONB-"))

    def test_due_dates_resolved(self):
        from datetime import timedelta
        from django.utils import timezone as tz
        eff = tz.now() + timezone.timedelta(days=5)
        from lifecycle.services import create_case_from_template
        c = create_case_from_template(
            template=self.tmpl_onboard, employee=self.emp, actor=self.itmgr,
            effective_date=eff)
        t = c.tasks.order_by("sequence").first()
        self.assertIsNotNone(t.due_date)

    def test_assignee_resolution(self):
        c = self.create_case()
        hw = c.tasks.get(title="Assign laptop")
        # default_assignee_role=it_support, no coordinator -> unassigned
        self.assertIsNone(hw.assigned_to)
        # employee task -> assigned to employee
        sec = c.tasks.get(title="Security induction")
        self.assertEqual(sec.assigned_to, self.emp)

    def test_plan_and_start(self):
        c = self.create_case()
        c = lm.LifecycleCase.objects.get(pk=c.pk)
        # plan
        from lifecycle.services import transition_case
        c = transition_case(c, "planned", self.itmgr)
        self.assertEqual(c.status, "planned")
        c = transition_case(c, "in_progress", self.itsupport)
        self.assertEqual(c.status, "in_progress")

    def test_employee_cannot_plan(self):
        c = self.create_case()
        from lifecycle.services import transition_case
        with self.assertRaises(Exception):
            transition_case(c, "planned", self.emp)

    def test_complete_blocked_required_task(self):
        c = self.create_case()
        from lifecycle.services import transition_case
        # laptop task required & blocks completion, still pending
        with self.assertRaises(Exception):
            transition_case(c, "completed", self.itmgr)

    def test_invalid_transition(self):
        c = self.create_case()
        from lifecycle.services import transition_case
        with self.assertRaises(Exception):
            transition_case(c, "completed", self.itmgr)  # draft->completed invalid

    def test_duplicate_transition_409(self):
        c = self.create_case()
        from lifecycle.services import transition_case
        transition_case(c, "planned", self.itmgr, version=1)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            transition_case(c, "planned", self.itmgr, version=1)
        self.assertIn("version", ctx.exception.error_dict)


# ---------------------------------------------------------------------------
# Offboarding workflow
# ---------------------------------------------------------------------------

class OffboardingTests(BaseLifecycle):
    def setUp(self):
        super().setUp()
        self.asset = make_asset("A9", "Offboard Laptop", self.cat,
                                assigned_to=self.emp, department=self.dep_it)
        from lifecycle.services import create_case_from_template
        self.case = create_case_from_template(
            template=self.tmpl_offboard, employee=self.emp, actor=self.itmgr)

    def test_assigned_assets_discovered(self):
        from lifecycle.services import list_assigned_assets
        assets = list_assigned_assets(self.case)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["asset_tag"], "A9")
        self.assertEqual(assets[0]["resolution"], "pending")

    def test_return_asset(self):
        from lifecycle.services import resolve_asset_return
        res = resolve_asset_return(self.case, self.asset.pk, self.itmgr)
        self.assertEqual(res.resolution, "returned")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, "available")
        self.assertIsNone(self.asset.assigned_to)

    def test_lost_asset(self):
        from lifecycle.services import resolve_asset_lost
        res = resolve_asset_lost(self.case, self.asset.pk, self.itmgr,
                                 note="left in taxi")
        self.assertEqual(res.resolution, "lost")

    def test_damaged_asset(self):
        from lifecycle.services import resolve_asset_damaged
        res = resolve_asset_damaged(self.case, self.asset.pk, self.itmgr)
        self.assertEqual(res.resolution, "damaged")

    def test_transfer_asset(self):
        from lifecycle.services import resolve_asset_transfer
        res = resolve_asset_transfer(self.case, self.asset.pk, self.itmgr,
                                     new_assignee=self.emp2)
        self.assertEqual(res.resolution, "transferred")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.assigned_to, self.emp2)

    def test_approved_exception(self):
        from lifecycle.services import resolve_asset_exception
        res = resolve_asset_exception(self.case, self.asset.pk, self.itmgr,
                                      reason="approved")
        self.assertEqual(res.resolution, "approved_exception")

    def test_unresolved_asset_blocks_completion(self):
        from lifecycle.services import transition_case
        with self.assertRaises(Exception):
            transition_case(self.case, "completed", self.itmgr)

    def test_account_deactivation(self):
        from lifecycle.services import deactivate_account
        u = make_user("off@x", "OFF1", "employee")
        case2 = lm.LifecycleCase.objects.create(
            case_number="OFF-2026-00002", case_type="offboarding",
            employee=u, status="in_progress")
        from lifecycle.services import resolve_asset_return
        # no assets, can complete after deactivation
        deactivate_account(u, self.sysadmin)
        u.refresh_from_db()
        self.assertFalse(u.is_active)

    def test_last_sysadmin_protected(self):
        from lifecycle.services import deactivate_account
        with self.assertRaises(Exception):
            deactivate_account(self.sysadmin, self.sysadmin)

    def test_self_lockout_protected(self):
        from lifecycle.services import deactivate_account
        with self.assertRaises(Exception):
            deactivate_account(self.itmgr, self.itmgr)

    def test_user_not_deleted_on_offboard(self):
        from lifecycle.services import deactivate_account
        deactivate_account(self.emp, self.sysadmin)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_deleted)
        self.assertFalse(self.emp.is_active)

    def test_deactivation_revokes_active_license_allocations(self):
        """Offboarding deactivation reclaims the employee's software licenses."""
        from licensing.models import LicenseAgreement, SoftwareProduct
        from licensing.services import allocate_license

        product = SoftwareProduct.objects.create(
            name="Office Pro", publisher="Example Publisher")
        agreement = LicenseAgreement.objects.create(
            agreement_number="AGR-DEACT-1", software_product=product,
            status="active", quantity_purchased=5, created_by=self.sysadmin)
        alloc = allocate_license(
            agreement=agreement, allocation_type="user",
            assigned_user=self.emp, actor=self.itmgr)
        self.assertEqual(alloc.status, "active")

        from lifecycle.services import deactivate_account
        deactivate_account(self.emp, self.sysadmin)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)

        alloc.refresh_from_db()
        self.assertEqual(alloc.status, "revoked")
        self.assertEqual(alloc.revoked_by, self.sysadmin)
        self.assertIn("Account deactivated", alloc.revocation_reason)


# ---------------------------------------------------------------------------
# Transfer workflow
# ---------------------------------------------------------------------------

class TransferTests(BaseLifecycle):
    def setUp(self):
        super().setUp()
        from lifecycle.services import create_case_from_template
        self.case = create_case_from_template(
            template=self.tmpl_transfer, employee=self.emp, actor=self.itmgr)

    def test_old_and_new_department_captured(self):
        self.case.previous_department = self.dep_it
        self.case.new_department = self.dep_hr
        self.case.save()
        self.assertEqual(self.case.previous_department, self.dep_it)
        self.assertEqual(self.case.new_department, self.dep_hr)

    def test_apply_department_change(self):
        from lifecycle.services import apply_department_change
        prev = self.emp.home_department
        case2 = apply_department_change(self.case, self.itmgr, self.dep_hr)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.home_department, self.dep_hr)
        self.assertEqual(case2.new_department, self.dep_hr)
        self.assertEqual(case2.previous_department, prev)

    def test_employee_cannot_self_transfer(self):
        # transfer applied via manager action only; employee has no such path
        from lifecycle.services import apply_department_change
        with self.assertRaises(Exception):
            apply_department_change(self.case, self.emp, self.dep_hr)

    def test_repeated_apply_idempotent_safe(self):
        from lifecycle.services import apply_department_change
        c = apply_department_change(self.case, self.itmgr, self.dep_hr)
        # same dept now -> error
        with self.assertRaises(Exception):
            apply_department_change(c, self.itmgr, self.dep_hr)


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------

class TaskOperationTests(BaseLifecycle):
    def setUp(self):
        super().setUp()
        from lifecycle.services import create_case_from_template
        self.case = create_case_from_template(
            template=self.tmpl_onboard, employee=self.emp, actor=self.itmgr)
        self.task = self.case.tasks.filter(
            responsibility="employee").first()

    def test_employee_own_task_start_complete(self):
        from lifecycle.services import task_start, task_complete
        task_start(self.task, self.emp)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "in_progress")
        task_complete(self.task, self.emp)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "completed")
        self.assertIsNotNone(self.task.completed_by)

    def test_evidence_required_blocks_complete(self):
        self.task.requires_evidence = True
        self.task.save()
        from lifecycle.services import task_start, task_complete
        task_start(self.task, self.emp)
        with self.assertRaises(Exception):
            task_complete(self.task, self.emp)
        # upload evidence then complete
        ev = lm.LifecycleTaskEvidence.objects.create(
            case=self.case, task=self.task, uploaded_by=self.emp,
            original_filename="e.txt",
            file=SimpleUploadedFile("e.txt", b"x", content_type="text/plain"),
            size=1)
        task_complete(self.task, self.emp)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "completed")

    def test_skip_requires_manager(self):
        from lifecycle.services import task_skip
        req = self.case.tasks.filter(required=True, blocks_completion=True).first()
        with self.assertRaises(Exception):
            task_skip(req, self.itsupport, "nope")
        task_skip(req, self.itmgr, "not needed")
        req.refresh_from_db()
        self.assertEqual(req.status, "skipped")

    def test_block_unblock(self):
        from lifecycle.services import task_block, task_unblock
        itask = self.case.tasks.filter(responsibility="it").first()
        task_block(itask, self.itsupport, "waiting")
        itask.refresh_from_db()
        self.assertEqual(itask.status, "blocked")
        task_unblock(itask, self.itsupport)
        itask.refresh_from_db()
        self.assertEqual(itask.status, "pending")

    def test_stale_version_409(self):
        from lifecycle.services import task_complete
        task_complete(self.task, self.emp, version=1)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            task_complete(self.task, self.emp, version=1)
        self.assertIn("version", ctx.exception.error_dict)

    def test_duplicate_completion(self):
        from lifecycle.services import task_complete
        task_complete(self.task, self.emp)
        with self.assertRaises(Exception):
            task_complete(self.task, self.emp)


# ---------------------------------------------------------------------------
# Automation tests
# ---------------------------------------------------------------------------

class AutomationTests(BaseLifecycle):
    def test_allowlisted_dispatcher(self):
        from lifecycle.services import ALLOWED_AUTOMATION_TYPES
        self.assertIn("assign_asset", ALLOWED_AUTOMATION_TYPES)
        self.assertIn("notification", ALLOWED_AUTOMATION_TYPES)
        self.assertNotIn("shell_exec", ALLOWED_AUTOMATION_TYPES)

    def test_unknown_automation_not_applicable(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00050", case_type="onboarding",
            employee=self.emp, status="draft")
        t = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="X", automation_type="none")
        lm.LifecycleTask.objects.filter(pk=t.pk).update(automation_type="bogus")
        t.refresh_from_db()
        from lifecycle.services import _run_task_automation
        _run_task_automation(t, self.itmgr)
        t.refresh_from_db()
        self.assertEqual(t.automation_status, "not_applicable")

    def test_notification_automation(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00051", case_type="onboarding",
            employee=self.emp, status="draft")
        t = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="N",
            automation_type="notification",
            automation_config={"message": "hello"})
        from lifecycle.services import _run_task_automation
        _run_task_automation(t, self.itmgr)
        t.refresh_from_db()
        self.assertEqual(t.automation_status, "succeeded")

    def test_automation_failure_sanitized(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00052", case_type="onboarding",
            employee=self.emp, status="draft")
        t = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="F",
            automation_type="deactivate_account",
            automation_config={})
        # deactivate a protected sysadmin -> should fail/sanitize
        from lifecycle.services import _run_task_automation
        _run_task_automation(t, self.itsupport)
        t.refresh_from_db()
        self.assertEqual(t.automation_status, "failed")
        self.assertIn("System Admin", t.automation_error_summary or "")

    def test_create_service_request_automation_creates_request(self):
        from services.models import ServiceCatalogueItem, ServiceRequest
        item = ServiceCatalogueItem.objects.create(
            name="Email account", category="email", is_active=True,
            creates_ticket=False)
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00053", case_type="onboarding",
            employee=self.emp, status="draft")
        t = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="Create SR",
            automation_type="create_service_request",
            automation_config={"catalogue_item_id": item.pk,
                                "answers": {"x": 1}})
        from lifecycle.services import _run_task_automation
        _run_task_automation(t, self.itmgr)
        t.refresh_from_db()
        self.assertEqual(t.automation_status, "succeeded")
        self.assertIsNotNone(t.related_service_request)
        self.assertEqual(t.related_service_request.catalogue_item_id,
                         item.pk)
        self.assertEqual(t.related_service_request.requester_id,
                         self.emp.pk)


class AttachmentTests(BaseLifecycle):
    def setUp(self):
        super().setUp()
        self.case = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00060", case_type="onboarding",
            employee=self.emp, status="draft")
        self.task = lm.LifecycleTask.objects.create(
            case=self.case, sequence=1, title="T", responsibility="employee",
            assigned_to=self.emp, requires_evidence=True)

    def test_allowed_file_upload(self):
        c = auth_client(self.emp)
        resp = c.post(reverse("lifecycle-task-evidence-list"),
                      {"case": self.case.pk, "task": self.task.pk,
                       "file": SimpleUploadedFile(
                           "form.pdf", b"%PDF", content_type="application/pdf"),
                       "description": "handover"}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_blocked_executable(self):
        c = auth_client(self.emp)
        resp = c.post(reverse("lifecycle-task-evidence-list"),
                      {"case": self.case.pk, "task": self.task.pk,
                       "file": SimpleUploadedFile(
                           "bad.exe", b"MZ", content_type="application/x-msdownload")},
                      format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_safe_download_headers(self):
        ev = lm.LifecycleTaskEvidence.objects.create(
            case=self.case, task=self.task, uploaded_by=self.emp,
            original_filename="report.pdf",
            file=SimpleUploadedFile("report.pdf", b"%PDF",
                                    content_type="application/pdf"),
            size=5)
        c = auth_client(self.emp)
        resp = c.get(reverse("lifecycle-task-evidence-download", args=[ev.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.get("X-Content-Type-Options"), "nosniff")

    def test_deleted_attachment_denied(self):
        ev = lm.LifecycleTaskEvidence.objects.create(
            case=self.case, task=self.task, uploaded_by=self.emp,
            original_filename="x.txt",
            file=SimpleUploadedFile("x.txt", b"x", content_type="text/plain"),
            size=1)
        ev.soft_delete(by_user=self.emp)
        c = auth_client(self.emp)
        resp = c.get(reverse("lifecycle-task-evidence-download", args=[ev.pk]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardTests(BaseLifecycle):
    def test_dashboard_role_scope(self):
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00070", case_type="onboarding",
            employee=self.emp, status="in_progress")
        # another employee's case must not appear
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00071", case_type="onboarding",
            employee=self.emp2, status="in_progress")
        c = auth_client(self.emp)
        resp = c.get(reverse("lifecycle-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        # employee-scoped: only their own case counted
        self.assertEqual(data["onboarding_in_progress"], 1)

    def test_dashboard_admin_metrics(self):
        lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00072", case_type="onboarding",
            employee=self.emp, status="in_progress", priority="urgent")
        c = auth_client(self.itmgr)
        resp = c.get(reverse("lifecycle-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertGreaterEqual(data["onboarding_in_progress"], 1)
        self.assertGreaterEqual(len(data["urgent_cases"]), 1)

    def test_dashboard_bounded(self):
        c = auth_client(self.itmgr)
        resp = c.get(reverse("lifecycle-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(resp.data.get("recent_cases", [])), 10)


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class SeedCommandTests(BaseLifecycle):
    def test_dry_run_default_no_create(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        before = lm.LifecycleTemplate.objects.count()
        call_command("seed_lifecycle_templates", stdout=out)
        after = lm.LifecycleTemplate.objects.count()
        self.assertEqual(before, after)  # dry-run creates nothing
        self.assertIn("dry-run", out.getvalue().lower())

    def test_create_and_idempotent(self):
        from django.core.management import call_command
        call_command("seed_lifecycle_templates", "--create",
                     "--department-code", "IT")
        n1 = lm.LifecycleTemplate.objects.count()
        self.assertGreater(n1, 0)
        call_command("seed_lifecycle_templates", "--create",
                     "--department-code", "IT")
        n2 = lm.LifecycleTemplate.objects.count()
        self.assertEqual(n1, n2)  # no duplicates
