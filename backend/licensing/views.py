"""REST API Views for Software Products, Agreements, Secrets, and Allocations.

Provides endpoints for complete license lifecycle management:
- Software Products catalog (with Employee-safe projections).
- License Agreements with controlled lifecycle actions and capacity calculations.
- Protected License Secrets with fail-closed reveal and no-store security headers.
- License Allocations with bulk operations and offboarding hooks.
- Software Installations and compliance monitoring.
- Governed License Renewals with threshold enforcement.
- Operational Compliance Findings.
- Protected Document Downloads with nosniff and Content-Disposition headers.
- Executive Dashboard, Renewal Calendar, and Utilization Reports.
"""

from collections import defaultdict
from decimal import Decimal
import os

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.attachment_security import add_download_security_headers, safe_content_disposition_filename
from common.audit import log_action
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseDocument,
    LicenseHistory,
    LicenseRenewal,
    LicenseSecret,
    SoftwareInstallation,
    SoftwareProduct,
)
from licensing.permissions import (
    LicenseAgreementPermission,
    LicenseAllocationPermission,
    LicenseCompliancePermission,
    LicenseDocumentPermission,
    LicenseRenewalPermission,
    LicenseSecretPermission,
    SoftwareInstallationPermission,
    SoftwareProductPermission,
    is_employee,
    is_it_manager,
    is_it_staff,
    is_system_admin,
)
from licensing.security import (
    compute_secret_fingerprint,
    decrypt_secret,
    encrypt_secret,
    extract_last_four,
    is_encryption_available,
)
from licensing.serializers import (
    AgreementActionSerializer,
    AllocateDeviceSerializer,
    AllocateUserSerializer,
    AllocationActionSerializer,
    BulkAllocateSerializer,
    BulkRevokeSerializer,
    ComplianceResolveSerializer,
    EmployeeLicenseAllocationSerializer,
    EmployeeSoftwareProductSerializer,
    LicenseAgreementSerializer,
    LicenseAllocationSerializer,
    LicenseComplianceFindingSerializer,
    LicenseDocumentSerializer,
    LicenseHistorySerializer,
    LicenseRenewalActionSerializer,
    LicenseRenewalSerializer,
    LicenseSecretRevealResponseSerializer,
    LicenseSecretRotateSerializer,
    LicenseSecretSerializer,
    ReserveConcurrentSerializer,
    SoftwareInstallationSerializer,
    SoftwareProductSerializer,
)
from licensing.services import (
    activate_agreement,
    activate_allocation,
    allocate_license,
    apply_approved_renewal,
    bulk_allocate_licenses,
    bulk_revoke_allocations,
    CONSUMING_ALLOCATION_STATUSES,
    evaluate_license_compliance,
    get_agreement_entitlement_limit,
    get_offboarding_allocation_preview,
    reconcile_agreement_entitlements,
    reconcile_entitlements_summary,
    recalculate_agreement_capacity,
    record_installation,
    remediate_compliance_finding,
    record_license_history,
    remove_installation,
    release_allocation,
    resolve_compliance_finding,
    resume_agreement,
    retire_agreement,
    review_renewal_request,
    revoke_allocation,
    revoke_allocations_for_offboarding,
    submit_renewal_request,
    suspend_agreement,
    suspend_allocation,
    terminate_agreement,
    verify_allocation,
)


class StandardResultsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ==============================================================================
# SOFTWARE PRODUCT VIEWSET
# ==============================================================================

class SoftwareProductViewSet(viewsets.ModelViewSet):
    """Software Product Catalog ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [SoftwareProductPermission]

    def get_serializer_class(self):
        if is_employee(self.request.user):
            return EmployeeSoftwareProductSerializer
        return SoftwareProductSerializer

    def get_queryset(self):
        user = self.request.user
        qs = SoftwareProduct.objects.filter(is_deleted=False)

        if is_employee(user):
            # Employees only see non-deleted, approved or restricted software
            qs = qs.filter(approved_status__in=["approved", "restricted"])
        else:
            # Filter by parameters
            category = self.request.query_params.get("category")
            if category:
                qs = qs.filter(category=category)
            status_param = self.request.query_params.get("status")
            if status_param:
                qs = qs.filter(approved_status=status_param)
            platform = self.request.query_params.get("platform")
            if platform:
                qs = qs.filter(platform=platform)
            is_active = self.request.query_params.get("is_active")
            if is_active is not None:
                qs = qs.filter(is_active=is_active.lower() == "true")

        # Search parameter
        q = self.request.query_params.get("search") or self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(publisher__icontains=q)
                | Q(product_family__icontains=q)
                | Q(edition__icontains=q)
                | Q(version__icontains=q)
            )

        return qs.select_related("vendor", "created_by").order_by("name")

    def perform_destroy(self, instance):
        # Soft delete
        instance.soft_delete(by_user=self.request.user)
        log_action(
            actor=self.request.user,
            action="soft_delete",
            instance=instance,
            reason="Software product soft-deleted.",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        product = self.get_object()
        if not is_it_manager(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        product.approved_status = "approved"
        product.save(update_fields=["approved_status", "updated_at"])
        log_action(actor=request.user, action="update", instance=product, reason="Product approved for use.")
        return Response({"id": product.pk, "approved_status": product.approved_status})

    @action(detail=True, methods=["post"])
    def restrict(self, request, pk=None):
        product = self.get_object()
        if not is_it_manager(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        product.approved_status = "restricted"
        product.save(update_fields=["approved_status", "updated_at"])
        log_action(actor=request.user, action="update", instance=product, reason="Product restricted.")
        return Response({"id": product.pk, "approved_status": product.approved_status})

    @action(detail=True, methods=["post"])
    def prohibit(self, request, pk=None):
        product = self.get_object()
        if not is_system_admin(request.user):
            return Response({"detail": "Only System Admins can prohibit software products."}, status=status.HTTP_403_FORBIDDEN)
        product.approved_status = "prohibited"
        product.save(update_fields=["approved_status", "updated_at"])
        log_action(actor=request.user, action="update", instance=product, reason="Product prohibited.")
        # Trigger compliance scan on prohibited product
        evaluate_license_compliance(software_product=product, actor=request.user)
        return Response({"id": product.pk, "approved_status": product.approved_status})

    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        product = self.get_object()
        if not is_system_admin(request.user):
            return Response({"detail": "Only System Admins can retire software products."}, status=status.HTTP_403_FORBIDDEN)
        product.approved_status = "retired"
        product.is_active = False
        product.save(update_fields=["approved_status", "is_active", "updated_at"])
        log_action(actor=request.user, action="update", instance=product, reason="Product retired.")
        return Response({"id": product.pk, "approved_status": product.approved_status})

    @action(detail=True, methods=["get"])
    def agreements(self, request, pk=None):
        product = self.get_object()
        if is_employee(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        agrs = product.agreements.filter(is_deleted=False).select_related("software_product", "vendor", "department")
        serializer = LicenseAgreementSerializer(agrs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def installations(self, request, pk=None):
        product = self.get_object()
        if is_employee(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        insts = product.installations.filter(status="installed").select_related("software_product", "asset", "installed_by")
        serializer = SoftwareInstallationSerializer(insts, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def compliance(self, request, pk=None):
        product = self.get_object()
        if is_employee(request.user):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        findings = product.compliance_findings.filter(status="open").select_related("software_product", "user", "asset")
        serializer = LicenseComplianceFindingSerializer(findings, many=True, context={"request": request})
        return Response(serializer.data)


# ==============================================================================
# LICENSE AGREEMENT VIEWSET
# ==============================================================================

class LicenseAgreementViewSet(viewsets.ModelViewSet):
    """License Agreement ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseAgreementPermission]
    serializer_class = LicenseAgreementSerializer

    def get_queryset(self):
        qs = LicenseAgreement.objects.filter(is_deleted=False)
        params = self.request.query_params

        status_param = params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        agr_type = params.get("agreement_type")
        if agr_type:
            qs = qs.filter(agreement_type=agr_type)
        lic_model = params.get("license_model")
        if lic_model:
            qs = qs.filter(license_model=lic_model)
        vendor_id = params.get("vendor")
        if vendor_id:
            qs = qs.filter(vendor_id=vendor_id)
        dept_id = params.get("department")
        if dept_id:
            qs = qs.filter(department_id=dept_id)
        product_id = params.get("software_product")
        if product_id:
            qs = qs.filter(software_product_id=product_id)

        # Search parameter
        q = params.get("search") or params.get("q")
        if q:
            qs = qs.filter(
                Q(agreement_number__icontains=q)
                | Q(software_product__name__icontains=q)
                | Q(vendor__name__icontains=q)
                | Q(contract_reference__icontains=q)
                | Q(invoice_reference__icontains=q)
                | Q(external_subscription_id__icontains=q)
            )

        return qs.select_related("software_product", "vendor", "department", "owner", "contract_manager")

    def perform_update(self, serializer):
        agreement = serializer.save()
        agreement.recalculate_counters(save=True)
        evaluate_license_compliance(agreement=agreement, actor=self.request.user)

    def perform_destroy(self, instance):
        # Prevent deletion if active allocations exist
        active_count = instance.allocations.filter(status__in=["assigned", "active", "reserved"]).count()
        if active_count > 0:
            raise ValidationError(
                f"Cannot delete agreement '{instance.agreement_number}' with {active_count} active allocation(s). "
                "Revoke all seats before deleting."
            )
        instance.soft_delete(by_user=self.request.user)
        log_action(
            actor=self.request.user,
            action="soft_delete",
            instance=instance,
            reason="Agreement deleted.",
        )

    # ---- Lifecycle Transition Actions ----

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        agreement = self.get_object()
        try:
            res = activate_agreement(agreement, request.user)
            return Response(LicenseAgreementSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        agreement = self.get_object()
        reason = request.data.get("reason", "").strip()
        try:
            res = suspend_agreement(agreement, request.user, reason)
            return Response(LicenseAgreementSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        agreement = self.get_object()
        try:
            res = resume_agreement(agreement, request.user)
            return Response(LicenseAgreementSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def terminate(self, request, pk=None):
        agreement = self.get_object()
        reason = request.data.get("reason", "").strip()
        revoke_all = bool(request.data.get("revoke_allocations", False))
        try:
            res = terminate_agreement(agreement, request.user, reason, revoke_allocations=revoke_all)
            return Response(LicenseAgreementSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        agreement = self.get_object()
        reason = request.data.get("reason", "").strip()
        try:
            res = retire_agreement(agreement, request.user, reason)
            return Response(LicenseAgreementSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def recalculate(self, request, pk=None):
        agreement = self.get_object()
        res = recalculate_agreement_capacity(agreement)
        return Response(LicenseAgreementSerializer(res, context={"request": request}).data)

    # ---- Allocation Actions ----

    @action(detail=True, methods=["post"], url_path="allocate-user")
    def allocate_user(self, request, pk=None):
        agreement = self.get_object()
        serializer = AllocateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            alloc = allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=serializer.validated_data["assigned_user"],
                actor=request.user,
                notes=serializer.validated_data.get("notes", ""),
                expected_release_date=serializer.validated_data.get("expected_release_date"),
                allow_duplicate=serializer.validated_data.get("allow_duplicate", False),
            )
            return Response(LicenseAllocationSerializer(alloc, context={"request": request}).data, status=status.HTTP_201_CREATED)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="allocate-device")
    def allocate_device(self, request, pk=None):
        agreement = self.get_object()
        serializer = AllocateDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            alloc = allocate_license(
                agreement=agreement,
                allocation_type="device",
                assigned_asset=serializer.validated_data["assigned_asset"],
                actor=request.user,
                notes=serializer.validated_data.get("notes", ""),
                expected_release_date=serializer.validated_data.get("expected_release_date"),
                allow_duplicate=serializer.validated_data.get("allow_duplicate", False),
            )
            return Response(LicenseAllocationSerializer(alloc, context={"request": request}).data, status=status.HTTP_201_CREATED)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="reserve-concurrent")
    def reserve_concurrent(self, request, pk=None):
        agreement = self.get_object()
        serializer = ReserveConcurrentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            alloc = allocate_license(
                agreement=agreement,
                allocation_type="concurrent_reservation",
                actor=request.user,
                notes=serializer.validated_data.get("notes", ""),
                expected_release_date=serializer.validated_data.get("expected_release_date"),
            )
            return Response(LicenseAllocationSerializer(alloc, context={"request": request}).data, status=status.HTTP_201_CREATED)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="bulk-allocate")
    def bulk_allocate(self, request, pk=None):
        agreement = self.get_object()
        serializer = BulkAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = bulk_allocate_licenses(
            agreement=agreement,
            allocations_data=serializer.validated_data["allocations"],
            actor=request.user,
        )
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="bulk-revoke")
    def bulk_revoke(self, request, pk=None):
        agreement = self.get_object()
        serializer = BulkRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = bulk_revoke_allocations(
            allocation_ids=serializer.validated_data["allocation_ids"],
            actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(result, status=status.HTTP_200_OK)

    # ---- Associated Objects ----

    @action(detail=True, methods=["get"])
    def allocations(self, request, pk=None):
        agreement = self.get_object()
        allocs = agreement.allocations.filter(status__in=["assigned", "active", "reserved"]).select_related("assigned_user", "assigned_asset", "department")
        serializer = LicenseAllocationSerializer(allocs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        agreement = self.get_object()
        docs = agreement.documents.filter(is_deleted=False).select_related("uploaded_by")
        serializer = LicenseDocumentSerializer(docs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        agreement = self.get_object()
        hist = agreement.history.all().select_related("actor")[:100]
        serializer = LicenseHistorySerializer(hist, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def utilization(self, request, pk=None):
        agreement = self.get_object()
        rec = reconcile_agreement_entitlements(agreement)
        payload = {
            "agreement_number": agreement.agreement_number,
            "product": agreement.software_product.name,
            "vendor": agreement.vendor.name if agreement.vendor else None,
            "license_model": agreement.license_model,
            "status": agreement.status,
            "expiry_date": str(agreement.expiry_date) if agreement.expiry_date else None,
            "is_unlimited": agreement.is_unlimited,
            "quantity_purchased": agreement.quantity_purchased,
            "quantity_allocated": agreement.quantity_allocated,
            "quantity_reserved": agreement.quantity_reserved,
            "quantity_available": agreement.quantity_available,
            "utilization_percent": agreement.utilization_percent,
            "open_findings": agreement.compliance_findings.filter(status__in=("open", "acknowledged")).count(),
        }
        payload.update({
            "purchased_entitlement_quantity": rec["purchased_entitlement_quantity"],
            "active_allocated_quantity": rec["active_allocated_quantity"],
            "consuming_quantity": rec["consuming_quantity"],
            "available_entitlement_quantity": rec["available_quantity"],
            "overallocated_quantity": rec["overallocated_quantity"],
            "suspended_allocation_quantity": rec["suspended_allocation_quantity"],
            "released_allocation_quantity": rec["released_allocation_quantity"],
            "expired_allocation_quantity": rec["expired_allocation_quantity"],
            "reconciled_utilization_percent": rec["utilization_percent"],
            "utilization_calculable": rec["utilization_calculable"],
            "utilization_note": rec["utilization_note"],
        })
        return Response(payload)


# ==============================================================================
# LICENSE SECRET VIEWSET
# ==============================================================================

class LicenseSecretViewSet(viewsets.ModelViewSet):
    """Protected License Secret ViewSet. Fails closed when encryption key missing."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseSecretPermission]
    serializer_class = LicenseSecretSerializer

    def get_queryset(self):
        # Employees cannot view any secret records
        if is_employee(self.request.user) or not is_it_manager(self.request.user):
            return LicenseSecret.objects.none()
        qs = LicenseSecret.objects.all()
        agr_id = self.request.query_params.get("agreement")
        if agr_id:
            qs = qs.filter(agreement_id=agr_id)
        return qs.select_related("agreement", "last_viewed_by", "rotated_by")

    @action(detail=True, methods=["post"])
    def reveal(self, request, pk=None):
        """Reveal secret plaintext. Strictly System Admin only. Enforces no-store caching."""
        secret = self.get_object()
        if not is_system_admin(request.user):
            return Response({"detail": "Only System Administrators can reveal plaintext secrets."}, status=status.HTTP_403_FORBIDDEN)

        if secret.status == "revoked":
            return Response({"detail": "Cannot reveal a revoked secret."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            plaintext = decrypt_secret(secret.encrypted_value)
        except Exception as exc:
            return Response(
                {"detail": f"Decryption failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Update last viewed tracking
        now = timezone.now()
        secret.last_viewed_at = now
        secret.last_viewed_by = request.user
        secret.save(update_fields=["last_viewed_at", "last_viewed_by"])

        # One reveal per account per window: stops a single account from
        # scanning the secret store and probing which labels/agreements exist.
        from common.throttling import account_action_cooldown
        if account_action_cooldown(
            f"secret_reveal:{secret.pk}", 60,
        ):
            return Response({"detail": "Too many reveal attempts. Try again later."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Audit and History (never include plaintext!)
        record_license_history(
            event_type="secret_revealed",
            actor=request.user,
            agreement=secret.agreement,
            detail={"secret_id": secret.pk, "secret_type": secret.secret_type, "label": secret.label},
        )

        log_action(
            actor=request.user,
            action="note",
            instance=secret,
            reason="Plaintext secret revealed by authorized System Admin.",
            details={"agreement_id": secret.agreement_id, "secret_id": secret.pk},
        )

        payload = {
            "id": secret.pk,
            "secret_type": secret.secret_type,
            "label": secret.label,
            "revealed_value": plaintext,
        }

        response = Response(payload, status=status.HTTP_200_OK)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response["Pragma"] = "no-cache"
        return response

    @action(detail=True, methods=["post"])
    def rotate(self, request, pk=None):
        """Rotate secret with new value."""
        secret = self.get_object()
        from common.throttling import account_action_cooldown
        if account_action_cooldown(
            f"secret_rotate:{secret.pk}", 60,
        ):
            return Response({"detail": "Too many rotation attempts. Try again later."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = LicenseSecretRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_val = serializer.validated_data["new_plaintext_value"]
        encrypted = encrypt_secret(new_val)
        fgp = compute_secret_fingerprint(new_val)
        last_four = extract_last_four(new_val)

        secret.encrypted_value = encrypted
        secret.value_fingerprint = fgp
        secret.last_four = last_four
        secret.status = "rotated"
        secret.rotated_at = timezone.now()
        secret.rotated_by = request.user
        if serializer.validated_data.get("new_label"):
            secret.label = serializer.validated_data["new_label"]
        secret.save()

        record_license_history(
            event_type="secret_rotated",
            actor=request.user,
            agreement=secret.agreement,
            detail={"secret_id": secret.pk, "label": secret.label},
        )

        log_action(
            actor=request.user,
            action="update",
            instance=secret,
            reason="Secret rotated.",
            details={"status": "rotated"},
        )

        return Response(LicenseSecretSerializer(secret, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        secret = self.get_object()
        secret.status = "revoked"
        secret.save(update_fields=["status", "updated_at"])

        record_license_history(
            event_type="secret_revoked",
            actor=request.user,
            agreement=secret.agreement,
            detail={"secret_id": secret.pk},
        )

        log_action(
            actor=request.user,
            action="update",
            instance=secret,
            reason="Secret revoked.",
            details={"status": "revoked"},
        )

        return Response(LicenseSecretSerializer(secret, context={"request": request}).data)


# ==============================================================================
# LICENSE ALLOCATION VIEWSET
# ==============================================================================

class LicenseAllocationViewSet(viewsets.ModelViewSet):
    """License Allocation ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseAllocationPermission]

    def get_serializer_class(self):
        if is_employee(self.request.user):
            return EmployeeLicenseAllocationSerializer
        return LicenseAllocationSerializer

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Create allocations through the agreement allocation endpoints so entitlement is enforced."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Allocation state changes must use the activate, suspend, release, revoke, or verify actions."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Allocations cannot be deleted; release or revoke them instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def get_queryset(self):
        user = self.request.user
        qs = LicenseAllocation.objects.all()

        if is_employee(user):
            # Strict object scoping: employee can ONLY see own user-allocations
            qs = qs.filter(assigned_user=user)
        else:
            params = self.request.query_params
            agr_id = params.get("agreement")
            if agr_id:
                qs = qs.filter(agreement_id=agr_id)
            user_id = params.get("user")
            if user_id:
                qs = qs.filter(assigned_user_id=user_id)
            asset_id = params.get("asset")
            if asset_id:
                qs = qs.filter(assigned_asset_id=asset_id)
            status_param = params.get("status")
            if status_param:
                qs = qs.filter(status=status_param)

            q = params.get("search") or params.get("q")
            if q:
                qs = qs.filter(
                    Q(allocation_reference__icontains=q)
                    | Q(agreement__agreement_number__icontains=q)
                    | Q(assigned_user__email__icontains=q)
                    | Q(assigned_user__employee_id__icontains=q)
                    | Q(assigned_asset__asset_tag__icontains=q)
                )

        return qs.select_related("agreement__software_product", "assigned_user", "assigned_asset", "department")

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        alloc = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        try:
            res = activate_allocation(alloc, request.user, reason=reason)
            return Response(LicenseAllocationSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        alloc = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        try:
            res = suspend_allocation(alloc, request.user, reason=reason)
            return Response(LicenseAllocationSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        alloc = self.get_object()
        reason = request.data.get("reason", "").strip()
        try:
            res = revoke_allocation(alloc, request.user, reason)
            return Response(LicenseAllocationSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        alloc = self.get_object()
        reason = request.data.get("reason", "").strip()
        try:
            res = release_allocation(alloc, request.user, reason=reason)
            return Response(LicenseAllocationSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        alloc = self.get_object()
        hist = alloc.history.all().select_related("actor")[:100]
        serializer = LicenseHistorySerializer(hist, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="offboarding-preview")
    def offboarding_preview(self, request):
        from accounts.models import User
        user_id = request.query_params.get("user")
        if not user_id:
            return Response({"detail": "user query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        preview = get_offboarding_allocation_preview(user)
        return Response({"user_id": user.pk, "allocations": preview, "count": len(preview)})

    @action(detail=False, methods=["post"], url_path="offboard")
    def offboard(self, request):
        from accounts.models import User
        user_id = request.data.get("user_id") or request.data.get("user")
        reason = (request.data.get("reason") or "").strip()
        if not user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if not reason:
            reason = f"Employee offboarding for {user.email}"
        result = revoke_allocations_for_offboarding(user=user, actor=request.user, reason=reason)
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        alloc = self.get_object()
        notes = request.data.get("notes", "").strip()
        res = verify_allocation(alloc, request.user, notes)
        return Response(LicenseAllocationSerializer(res, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="my-software")
    def my_software(self, request):
        allocs = LicenseAllocation.objects.filter(
            assigned_user=request.user,
            status__in=["assigned", "active"],
        ).select_related("agreement__software_product", "assigned_asset")
        serializer = EmployeeLicenseAllocationSerializer(allocs, many=True)
        return Response(serializer.data)


# ==============================================================================
# SOFTWARE INSTALLATION VIEWSET
# ==============================================================================

class SoftwareInstallationViewSet(viewsets.ModelViewSet):
    """Software Installation ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [SoftwareInstallationPermission]
    serializer_class = SoftwareInstallationSerializer

    def get_queryset(self):
        qs = SoftwareInstallation.objects.all()
        params = self.request.query_params
        prod_id = params.get("product")
        if prod_id:
            qs = qs.filter(software_product_id=prod_id)
        asset_id = params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        status_param = params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        comp = params.get("compliance_status")
        if comp:
            qs = qs.filter(compliance_status=comp)
        return qs.select_related("software_product", "asset", "installed_by")

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        inst = self.get_object()
        notes = request.data.get("notes", "").strip()
        res = remove_installation(inst, request.user, notes)
        return Response(SoftwareInstallationSerializer(res, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def evaluate(self, request, pk=None):
        inst = self.get_object()
        # Trigger evaluation for this installation's product & asset
        findings = evaluate_license_compliance(
            software_product=inst.software_product,
            asset=inst.asset,
            actor=request.user,
        )
        return Response({"findings_evaluated": len(findings)})


# ==============================================================================
# LICENSE RENEWAL VIEWSET
# ==============================================================================

class LicenseRenewalViewSet(viewsets.ModelViewSet):
    """License Renewal Workflow ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseRenewalPermission]
    serializer_class = LicenseRenewalSerializer

    def get_queryset(self):
        qs = LicenseRenewal.objects.all()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        agr_id = self.request.query_params.get("agreement")
        if agr_id:
            qs = qs.filter(agreement_id=agr_id)
        return qs.select_related("agreement__software_product", "requested_by", "reviewed_by")

    def perform_create(self, serializer):
        agreement = serializer.validated_data["agreement"]
        proposed_start = serializer.validated_data["proposed_start_date"]
        proposed_expiry = serializer.validated_data["proposed_expiry_date"]
        proposed_qty = serializer.validated_data["proposed_quantity"]
        proposed_unit = serializer.validated_data["proposed_unit_cost"]
        proposed_total = serializer.validated_data["proposed_total_cost"]
        currency = serializer.validated_data.get("currency") or agreement.currency
        reason = serializer.validated_data.get("reason", "")

        try:
            renewal = submit_renewal_request(
                agreement=agreement,
                proposed_start_date=proposed_start,
                proposed_expiry_date=proposed_expiry,
                proposed_quantity=proposed_qty,
                proposed_unit_cost=proposed_unit,
                proposed_total_cost=proposed_total,
                currency=currency,
                requested_by=self.request.user,
                reason=reason,
            )
            serializer.instance = renewal
        except (ValidationError, DjangoValidationError) as exc:
            raise ValidationError(str(exc))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        renewal = self.get_object()
        review_reason = request.data.get("review_reason", "").strip()
        try:
            res = review_renewal_request(renewal, request.user, decision="approved", review_reason=review_reason)
            return Response(LicenseRenewalSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        renewal = self.get_object()
        review_reason = request.data.get("review_reason", "").strip()
        try:
            res = review_renewal_request(renewal, request.user, decision="rejected", review_reason=review_reason)
            return Response(LicenseRenewalSerializer(res, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        renewal = self.get_object()
        try:
            agr = apply_approved_renewal(renewal, request.user)
            return Response(LicenseAgreementSerializer(agr, context={"request": request}).data)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        renewal = self.get_object()
        if renewal.status not in ("draft", "pending_review"):
            return Response({"detail": f"Cannot cancel renewal in '{renewal.status}' status."}, status=status.HTTP_400_BAD_REQUEST)
        renewal.status = "cancelled"
        renewal.save(update_fields=["status", "updated_at"])
        return Response(LicenseRenewalSerializer(renewal, context={"request": request}).data)


# ==============================================================================
# COMPLIANCE FINDINGS VIEWSET
# ==============================================================================

class LicenseComplianceFindingViewSet(viewsets.ReadOnlyModelViewSet):
    """Compliance Findings ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseCompliancePermission]
    serializer_class = LicenseComplianceFindingSerializer

    def get_queryset(self):
        qs = LicenseComplianceFinding.objects.all()
        params = self.request.query_params
        status_param = params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        sev = params.get("severity")
        if sev:
            qs = qs.filter(severity=sev)
        f_type = params.get("finding_type")
        if f_type:
            qs = qs.filter(finding_type=f_type)
        return qs.select_related("software_product", "agreement", "asset", "user", "resolved_by")

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        finding = self.get_object()
        finding.status = "acknowledged"
        finding.save(update_fields=["status", "updated_at"])
        log_action(actor=request.user, action="update", instance=finding, reason="Finding acknowledged.")
        return Response(LicenseComplianceFindingSerializer(finding, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        finding = self.get_object()
        serializer = ComplianceResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data["resolution_note"]
        try:
            res = resolve_compliance_finding(finding, request.user, resolution_note=note, is_false_positive=False)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LicenseComplianceFindingSerializer(res, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def remediate(self, request, pk=None):
        finding = self.get_object()
        note = (request.data.get("remediation_note") or request.data.get("resolution_note") or "").strip()
        reevaluate = bool(request.data.get("reevaluate", False))
        if not note:
            return Response({"detail": "A remediation note is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            res = remediate_compliance_finding(finding, request.user, remediation_note=note, reevaluate=reevaluate)
        except (ValidationError, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LicenseComplianceFindingSerializer(res, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="false-positive")
    def false_positive(self, request, pk=None):
        finding = self.get_object()
        serializer = ComplianceResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data["resolution_note"]
        res = resolve_compliance_finding(finding, request.user, resolution_note=note, is_false_positive=True)
        return Response(LicenseComplianceFindingSerializer(res, context={"request": request}).data)


# ==============================================================================
# LICENSE DOCUMENT VIEWSET
# ==============================================================================

class LicenseDocumentViewSet(viewsets.ModelViewSet):
    """Protected License Document Attachment ViewSet."""

    pagination_class = StandardResultsPagination
    permission_classes = [LicenseDocumentPermission]
    serializer_class = LicenseDocumentSerializer

    def get_queryset(self):
        qs = LicenseDocument.objects.filter(is_deleted=False)
        agr_id = self.request.query_params.get("agreement")
        if agr_id:
            qs = qs.filter(agreement_id=agr_id)
        return qs.select_related("agreement", "uploaded_by")

    def perform_create(self, serializer):
        uploaded_file = self.request.FILES.get("file")
        if not uploaded_file:
            raise ValidationError({"file": "No document file was provided."})

        # Security allowlist & size validation
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        blocked_exts = {".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".js", ".msi", ".dll", ".scr", ".com", ".hta", ".jar"}
        if ext in blocked_exts:
            raise ValidationError({"file": f"File type '{ext}' is blocked for security reasons."})

        max_size = 15 * 1024 * 1024
        if uploaded_file.size > max_size:
            raise ValidationError({"file": "Uploaded file exceeds maximum allowed size (15MB)."})

        serializer.save(
            uploaded_by=self.request.user,
            original_filename=uploaded_file.name,
            content_type=uploaded_file.content_type or "application/octet-stream",
            size=uploaded_file.size,
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = self.get_object()
        if not doc.file or not os.path.exists(doc.file.path):
            raise Http404("Document file not found on disk.")

        safe_name = safe_content_disposition_filename(doc.original_filename)
        response = FileResponse(open(doc.file.path, "rb"), content_type=doc.content_type)
        response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        add_download_security_headers(response)
        return response


# ==============================================================================
# LICENSE HISTORY VIEWSET
# ==============================================================================

class LicenseHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only immutable history viewset."""

    pagination_class = StandardResultsPagination
    permission_classes = [IsAuthenticated]
    serializer_class = LicenseHistorySerializer

    def get_queryset(self):
        if is_employee(self.request.user):
            return LicenseHistory.objects.none()
        qs = LicenseHistory.objects.all()
        agr_id = self.request.query_params.get("agreement")
        if agr_id:
            qs = qs.filter(agreement_id=agr_id)
        alloc_id = self.request.query_params.get("allocation")
        if alloc_id:
            qs = qs.filter(allocation_id=alloc_id)
        return qs.select_related("actor", "agreement").order_by("-created_at")


# ==============================================================================
# REPORTING & DASHBOARD ENDPOINTS
# ==============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def licensing_dashboard(request):
    """Licensing Management Dashboard endpoint."""
    user = request.user
    if is_employee(user):
        return Response({"detail": "Dashboard restricted to IT Staff."}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now().date()
    d30 = now + timezone.timedelta(days=30)
    d60 = now + timezone.timedelta(days=60)
    d90 = now + timezone.timedelta(days=90)

    # Filters (agreement status, vendor, license metric, expiry period)
    status_filter = (request.query_params.get("status") or "").strip()
    vendor_filter = (request.query_params.get("vendor") or "").strip()
    license_type_filter = (request.query_params.get("license_type") or request.query_params.get("license_model") or "").strip()
    expiry_filter = (request.query_params.get("expiry") or request.query_params.get("expiry_period") or "").strip()

    agr_qs = LicenseAgreement.objects.filter(is_deleted=False)
    if status_filter:
        agr_qs = agr_qs.filter(status=status_filter)
    if vendor_filter:
        if vendor_filter.isdigit():
            agr_qs = agr_qs.filter(vendor_id=int(vendor_filter))
        else:
            agr_qs = agr_qs.filter(vendor__name__icontains=vendor_filter)
    if license_type_filter:
        agr_qs = agr_qs.filter(license_model=license_type_filter)
    if expiry_filter == "expired":
        agr_qs = agr_qs.filter(expiry_date__lt=now).exclude(status__in=("terminated", "retired"))
    elif expiry_filter == "none":
        agr_qs = agr_qs.filter(expiry_date__isnull=True)
    elif expiry_filter.isdigit():
        days = int(expiry_filter)
        agr_qs = agr_qs.filter(expiry_date__gte=now, expiry_date__lte=now + timezone.timedelta(days=days))

    agr_qs = agr_qs.annotate(
        active_allocated_count=Count("allocations", filter=Q(allocations__status__in=("assigned", "active")), distinct=True),
        reserved_count=Count("allocations", filter=Q(allocations__status="reserved"), distinct=True),
        consuming_count=Count("allocations", filter=Q(allocations__status__in=CONSUMING_ALLOCATION_STATUSES), distinct=True),
        suspended_count=Count("allocations", filter=Q(allocations__status="suspended"), distinct=True),
        released_count=Count("allocations", filter=Q(allocations__status__in=("revoked", "released")), distinct=True),
        expired_allocation_count=Count("allocations", filter=Q(allocations__status="expired"), distinct=True),
        open_findings_count=Count(
            "compliance_findings",
            filter=Q(compliance_findings__status__in=("open", "acknowledged")),
            distinct=True,
        ),
    )
    agreements = list(
        agr_qs.select_related("software_product", "vendor").order_by("agreement_number")
    )

    prod_qs = SoftwareProduct.objects.filter(is_deleted=False)
    finding_qs = LicenseComplianceFinding.objects.filter(status__in=("open", "acknowledged"))
    filtered = bool(status_filter or vendor_filter or license_type_filter or expiry_filter)
    if filtered:
        finding_qs = finding_qs.filter(agreement_id__in=[a.pk for a in agreements])

    active_products = prod_qs.filter(is_active=True).count()
    total_agreements = len(agreements)
    active_agreements = sum(1 for a in agreements if a.status == "active")
    expired_agreements = sum(
        1 for a in agreements if a.status == "expired" or (a.expiry_date and a.expiry_date < now and a.status not in ("terminated", "retired"))
    )
    expiring_30 = sum(1 for a in agreements if a.expiry_date and now <= a.expiry_date <= d30)
    expiring_60 = sum(1 for a in agreements if a.expiry_date and d30 < a.expiry_date <= d60)
    expiring_90 = sum(1 for a in agreements if a.expiry_date and d60 < a.expiry_date <= d90)

    total_entitlement = 0
    active_usage = 0
    available_entitlement = 0
    overallocated_agreements = 0
    overallocated_quantity = 0
    attention_ids = set()
    for agr in agreements:
        limit = get_agreement_entitlement_limit(agr)
        active_usage += agr.consuming_count
        if not agr.is_unlimited and limit is not None and limit > 0:
            total_entitlement += limit
            available_entitlement += max(0, limit - agr.consuming_count)
            if agr.consuming_count > limit:
                overallocated_agreements += 1
                overallocated_quantity += agr.consuming_count - limit
                attention_ids.add(agr.pk)
        elif not agr.is_unlimited:
            attention_ids.add(agr.pk)
        if agr.status in ("expired", "terminated") or (agr.expiry_date and agr.expiry_date <= d90):
            attention_ids.add(agr.pk)
        if agr.open_findings_count:
            attention_ids.add(agr.pk)

    utilization_pct = round((active_usage / total_entitlement) * 100, 2) if total_entitlement > 0 else None

    renewals_qs = LicenseRenewal.objects.filter(status="pending_review")
    if filtered:
        renewals_qs = renewals_qs.filter(agreement_id__in=[a.pk for a in agreements])
    pending_renewals_count = renewals_qs.count()

    expiring_agreements_list = [
        {
            "id": a.pk,
            "agreement_number": a.agreement_number,
            "product_name": a.software_product.name,
            "expiry_date": str(a.expiry_date) if a.expiry_date else None,
            "days_remaining": (a.expiry_date - now).days if a.expiry_date else None,
        }
        for a in agreements
        if a.expiry_date and now <= a.expiry_date <= d90
    ][:20]
    pending_renewals_list = [
        {"id": r.pk, "agreement_number": r.agreement.agreement_number, "status": r.status}
        for r in renewals_qs.select_related("agreement")[:20]
    ]

    # Financial breakdown grouped by currency (NO fake cross-currency conversion)
    cost_by_currency = {}
    currencies = {a.currency for a in agreements if a.status == "active"}
    for c in currencies:
        total = sum((a.total_cost for a in agreements if a.status == "active" and a.currency == c), Decimal("0.00"))
        cost_by_currency[c] = str(total)

    # Compliance highlights
    unused_findings = finding_qs.filter(finding_type="unused_license").count()
    unlicensed_insts = finding_qs.filter(finding_type="unlicensed_installation").count()
    prohibited_sw = finding_qs.filter(finding_type="prohibited_software").count()
    inactive_user_allocs = finding_qs.filter(finding_type="allocation_to_inactive_user").count()

    recent_findings = LicenseComplianceFindingSerializer(
        finding_qs.select_related("agreement", "software_product").order_by("-detected_at")[:5],
        many=True,
    ).data

    return Response({
        "total_agreements": total_agreements,
        "active_agreements": active_agreements,
        "expired_agreements": expired_agreements,
        "expired": expired_agreements,
        "expiring_in_30_days": expiring_30,
        "expiring_in_60_days": expiring_60,
        "expiring_in_90_days": expiring_90,
        "expiring_30": expiring_30,
        "expiring_60": expiring_60,
        "expiring_90": expiring_90,
        "approaching_expiry_agreements": expiring_30 + expiring_60 + expiring_90,
        "total_entitlement_quantity": total_entitlement,
        "active_usage": active_usage,
        "available_entitlements": available_entitlement,
        "overallocated_agreements": overallocated_agreements,
        "overallocated_quantity": overallocated_quantity,
        "agreements_requiring_attention": len(attention_ids),
        "pending_renewals": pending_renewals_count,
        "open_compliance_findings": finding_qs.count(),
        "utilization_calculable": total_entitlement > 0,
        "total_purchased_seats": total_entitlement,
        "total_allocated_seats": active_usage,
        "purchased_seats": total_entitlement,
        "allocated_seats": active_usage,
        "available_seats": available_entitlement,
        "utilization_percent": utilization_pct,
        "active_products": active_products,
        "annual_cost_by_currency": cost_by_currency,
        "annual_recurring_cost_by_currency": cost_by_currency,
        "findings": {
            "unused_allocations": unused_findings,
            "unlicensed_installations": unlicensed_insts,
            "prohibited_software": prohibited_sw,
            "inactive_user_allocations": inactive_user_allocs,
        },
        "unused_findings": unused_findings,
        "unlicensed_installations": unlicensed_insts,
        "prohibited_findings": prohibited_sw,
        "recent_findings": recent_findings,
        "expiring_agreements": expiring_agreements_list,
        "pending_renewals_list": pending_renewals_list,
        "filters": {
            "status": status_filter or None,
            "vendor": vendor_filter or None,
            "license_type": license_type_filter or None,
            "expiry": expiry_filter or None,
        },
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def renewal_calendar(request):
    """Renewal Calendar API grouping agreements into deadline buckets."""
    user = request.user
    if is_employee(user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now().date()
    d30 = now + timezone.timedelta(days=30)
    d60 = now + timezone.timedelta(days=60)
    d90 = now + timezone.timedelta(days=90)

    agrs = LicenseAgreement.objects.filter(is_deleted=False).exclude(status__in=["terminated", "retired"]).select_related(
        "software_product", "vendor", "owner", "contract_manager"
    )

    overdue = []
    next_30 = []
    next_60 = []
    next_90 = []
    later = []

    for agr in agrs:
        target_date = agr.renewal_date or agr.expiry_date
        if not target_date:
            continue
        days_rem = (target_date - now).days
        item = {
            "id": agr.pk,
            "agreement_number": agr.agreement_number,
            "product_name": agr.software_product.name,
            "vendor_name": agr.vendor.name if agr.vendor else None,
            "expiry_date": str(agr.expiry_date) if agr.expiry_date else None,
            "renewal_date": str(agr.renewal_date) if agr.renewal_date else None,
            "owner": agr.owner.email if agr.owner else None,
            "status": agr.status,
            "total_cost": str(agr.total_cost),
            "currency": agr.currency,
            "days_remaining": days_rem,
        }
        if days_rem < 0:
            overdue.append(item)
        elif days_rem <= 30:
            next_30.append(item)
        elif days_rem <= 60:
            next_60.append(item)
        elif days_rem <= 90:
            next_90.append(item)
        else:
            later.append(item)

    return Response({
        "overdue": overdue,
        "next_30_days": next_30,
        "31_to_60_days": next_60,
        "61_to_90_days": next_90,
        "later": later,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def utilization_report(request):
    """Seat and Subscription Utilization Report."""
    user = request.user
    if is_employee(user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now().date()
    status_filter = (request.query_params.get("status") or "").strip()
    vendor_filter = (request.query_params.get("vendor") or "").strip()
    license_type_filter = (request.query_params.get("license_type") or request.query_params.get("license_model") or "").strip()
    expiry_filter = (request.query_params.get("expiry") or request.query_params.get("expiry_period") or "").strip()
    overallocated_only = (request.query_params.get("overallocated") or "").lower() in ("1", "true", "yes")

    agrs = LicenseAgreement.objects.filter(is_deleted=False)
    if status_filter:
        agrs = agrs.filter(status=status_filter)
    if vendor_filter:
        if vendor_filter.isdigit():
            agrs = agrs.filter(vendor_id=int(vendor_filter))
        else:
            agrs = agrs.filter(vendor__name__icontains=vendor_filter)
    if license_type_filter:
        agrs = agrs.filter(license_model=license_type_filter)
    if expiry_filter == "expired":
        agrs = agrs.filter(expiry_date__lt=now).exclude(status__in=("terminated", "retired"))
    elif expiry_filter == "none":
        agrs = agrs.filter(expiry_date__isnull=True)
    elif expiry_filter.isdigit():
        days = int(expiry_filter)
        agrs = agrs.filter(expiry_date__gte=now, expiry_date__lte=now + timezone.timedelta(days=days))

    agrs = agrs.select_related("software_product", "vendor").annotate(
        active_allocated_count=Count("allocations", filter=Q(allocations__status__in=("assigned", "active")), distinct=True),
        reserved_count=Count("allocations", filter=Q(allocations__status="reserved"), distinct=True),
        consuming_count=Count("allocations", filter=Q(allocations__status__in=CONSUMING_ALLOCATION_STATUSES), distinct=True),
        suspended_count=Count("allocations", filter=Q(allocations__status="suspended"), distinct=True),
        released_count=Count("allocations", filter=Q(allocations__status__in=("revoked", "released")), distinct=True),
        expired_allocation_count=Count("allocations", filter=Q(allocations__status="expired"), distinct=True),
        open_findings_count=Count(
            "compliance_findings",
            filter=Q(compliance_findings__status__in=("open", "acknowledged")),
            distinct=True,
        ),
    ).order_by("agreement_number")

    rows = []
    total_entitlement = 0
    total_usage = 0
    total_available = 0
    overallocated_agreements = 0

    for agr in agrs:
        limit = get_agreement_entitlement_limit(agr)
        is_unlimited = agr.is_unlimited or limit is None
        usage = agr.consuming_count
        available = None if is_unlimited else max(0, limit - usage)
        overallocated = 0 if is_unlimited else max(0, usage - limit)
        calculable = bool(not is_unlimited and limit and limit > 0)
        utilization = round((usage / limit) * 100, 2) if calculable else None
        if calculable:
            note = ""
        elif is_unlimited:
            note = "Unlimited or non-seat-based entitlement; utilization is not calculated."
        else:
            note = "Entitlement quantity is missing or zero; utilization cannot be calculated."

        if overallocated_only and not overallocated:
            continue

        if calculable:
            total_entitlement += limit
            total_usage += usage
            total_available += available
            if overallocated:
                overallocated_agreements += 1

        cost_per_seat = None
        if calculable and usage > 0 and agr.total_cost > 0:
            cost_per_seat = str(round(agr.total_cost / usage, 2))

        rows.append({
            "id": agr.pk,
            "agreement_name": agr.agreement_number,
            "agreement_number": agr.agreement_number,
            "product_name": agr.software_product.name,
            "vendor": agr.vendor.name if agr.vendor else None,
            "vendor_id": agr.vendor_id,
            "license_metric": agr.license_model,
            "license_model": agr.license_model,
            "agreement_type": agr.agreement_type,
            "is_unlimited": is_unlimited,
            "purchased_entitlement": None if is_unlimited else limit,
            "quantity_purchased": None if is_unlimited else limit,
            "current_usage": usage,
            "quantity_allocated": agr.active_allocated_count,
            "quantity_reserved": agr.reserved_count,
            "available_entitlement": available,
            "quantity_available": available,
            "overallocated_quantity": overallocated,
            "is_overallocated": overallocated > 0,
            "suspended_quantity": agr.suspended_count,
            "released_quantity": agr.released_count,
            "expired_allocation_quantity": agr.expired_allocation_count,
            "utilization_percent": utilization,
            "utilization_calculable": calculable,
            "utilization_note": note,
            "cost_per_allocated_seat": cost_per_seat,
            "currency": agr.currency,
            "status": agr.status,
            "expiry_date": str(agr.expiry_date) if agr.expiry_date else None,
            "renewal_date": str(agr.renewal_date) if agr.renewal_date else None,
            "open_findings": agr.open_findings_count,
        })

    return Response({
        "count": len(rows),
        "summary": {
            "total_entitlement_quantity": total_entitlement,
            "current_usage": total_usage,
            "available_entitlement": total_available,
            "overallocated_agreements": overallocated_agreements,
            "utilization_percent": round((total_usage / total_entitlement) * 100, 2) if total_entitlement else None,
        },
        "filters": {
            "status": status_filter or None,
            "vendor": vendor_filter or None,
            "license_type": license_type_filter or None,
            "expiry": expiry_filter or None,
            "overallocated": overallocated_only,
        },
        "results": rows,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def entitlement_reconciliation(request):
    """Agreement-level entitlement reconciliation summary."""
    user = request.user
    if is_employee(user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    agrs = LicenseAgreement.objects.filter(is_deleted=False)
    status_filter = (request.query_params.get("status") or "").strip()
    vendor_filter = (request.query_params.get("vendor") or "").strip()
    license_type_filter = (request.query_params.get("license_type") or request.query_params.get("license_model") or "").strip()
    if status_filter:
        agrs = agrs.filter(status=status_filter)
    if vendor_filter:
        if vendor_filter.isdigit():
            agrs = agrs.filter(vendor_id=int(vendor_filter))
        else:
            agrs = agrs.filter(vendor__name__icontains=vendor_filter)
    if license_type_filter:
        agrs = agrs.filter(license_model=license_type_filter)

    summary = reconcile_entitlements_summary(agrs)
    rows = [reconcile_agreement_entitlements(agr) for agr in agrs.select_related("software_product")]
    return Response({"summary": summary, "count": len(rows), "results": rows})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compliance_summary(request):
    """Compliance findings executive summary."""
    user = request.user
    if is_employee(user):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    findings = LicenseComplianceFinding.objects.filter(status="open")
    by_type = findings.values("finding_type").annotate(count=Count("id"))
    by_severity = findings.values("severity").annotate(count=Count("id"))

    return Response({
        "total_open_findings": findings.count(),
        "by_type": {item["finding_type"]: item["count"] for item in by_type},
        "by_severity": {item["severity"]: item["count"] for item in by_severity},
    })
