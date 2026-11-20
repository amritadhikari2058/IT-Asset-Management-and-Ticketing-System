"""CMDB API views.

Response-shape notes (frontend contract):
- List endpoints return plain (bounded) arrays by default; requesting an
  explicit `page` param switches to DRF pagination ({count, results}).
- `/items/{id}/dependencies` returns {nodes, edges, nodeCount,
  cycleIndicator, truncated, max_depth}.
- `/items/{id}/impact` returns top-level source-CI fields plus the impact
  result (affected_ci_ids, affected_services, ... risk_summary).
- Dashboard returns a flat metrics object; reports return
  {kind, rows, columns, summary, generated_at}.
"""

from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from common.audit import log_action

from . import baselines as baseline_service
from . import impact as impact_service
from . import services as domain_service
from .impact import (
    VERIFICATION_THRESHOLD_DAYS,
    analyze_ci_impact,
    build_dependency_graph,
    find_orphan_configuration_items,
    find_single_points_of_failure,
    find_unverified_configuration_items,
    get_service_dependency_graph,
    verification_status_for,
)
from .models import (
    CMDBServiceProfile,
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemChangeLink,
    ConfigurationItemHistory,
    ConfigurationItemRelationship,
    ConfigurationItemTicketLink,
    ConfigurationItemType,
    HIERARCHY_PARENT_DIRECTION,
    ServiceConfigurationItemLink,
)
from .permissions import (
    BaselinePermission,
    CITypePermission,
    CIPermission,
    CMDBPermission,
    DriftPermission,
    HistoryPermission,
    RelationshipPermission,
    get_user_role,
    is_it_manager,
    is_system_admin,
)
from .serializers import (
    CMDBServiceProfileSerializer,
    ConfigurationBaselineSerializer,
    ConfigurationDriftFindingSerializer,
    ConfigurationItemChangeLinkSerializer,
    ConfigurationItemHistorySerializer,
    ConfigurationItemRelationshipSerializer,
    ConfigurationItemSerializer,
    ConfigurationItemTicketLinkSerializer,
    ConfigurationItemTypeSerializer,
    DriftActionSerializer,
    RetireCISerializer,
    ServiceConfigurationItemLinkSerializer,
    StaleRecordError,
    VerifyCISerializer,
)

DEFAULT_LIST_CAP = 1000
DASHBOARD_RECENT_LIMIT = 10

CI_ORDERING = {
    "ci_number", "-ci_number", "name", "-name", "status", "-status",
    "criticality", "-criticality", "environment", "-environment",
    "created_at", "-created_at", "updated_at", "-updated_at",
    "last_verified_at", "-last_verified_at",
}


def _wants_page(request):
    page = request.query_params.get("page")
    return page is not None and page != ""


def list_response(request, queryset, serializer_class, cap=DEFAULT_LIST_CAP):
    """Plain bounded array by default; paginated envelope on ?page=N."""
    if _wants_page(request):
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = serializer_class(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)
    rows = list(queryset[:cap])
    serializer = serializer_class(rows, many=True, context={"request": request})
    return Response(serializer.data)


def _bool_param(value):
    return str(value or "").lower() in ("1", "true", "yes", "on")


def _parse_date(value):
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _apply_date_range(qset, param_value, field):
    """Apply from/to range from 'a,b' style params or from/to pairs."""
    if not param_value:
        return qset
    parts = [p for p in str(param_value).replace(":", ",").split(",") if p]
    if len(parts) >= 1:
        start = _parse_date(parts[0])
        if start:
            qset = qset.filter(**{f"{field}__date__gte": start.date()})
    if len(parts) >= 2:
        end = _parse_date(parts[1])
        if end:
            qset = qset.filter(**{f"{field}__date__lte": end.date()})
    return qset


# ---------------------------------------------------------------------------
# CI Types
# ---------------------------------------------------------------------------

class ConfigurationItemTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [CITypePermission]
    serializer_class = ConfigurationItemTypeSerializer

    def get_queryset(self):
        qs = ConfigurationItemType.objects.filter(is_deleted=False)
        params = self.request.query_params
        if params.get("is_active") not in (None, ""):
            qs = qs.filter(is_active=_bool_param(params.get("is_active")))
        if params.get("category"):
            qs = qs.filter(category=params["category"])
        q = params.get("search") or params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        return qs.annotate(
            annotated_ci_count=Count(
                "configuration_items",
                filter=Q(configuration_items__is_deleted=False),
            ),
        ).order_by("name")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemTypeSerializer, cap=500)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError({"code": "Duplicate CI Type code."}) from exc

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_system:
            return Response(
                {"detail": "System CI Types cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Configuration items
# ---------------------------------------------------------------------------

class ConfigurationItemViewSet(viewsets.ModelViewSet):
    permission_classes = [CIPermission]
    serializer_class = ConfigurationItemSerializer

    def get_queryset(self):
        qs = ConfigurationItem.objects.filter(
            is_deleted=False,
        ).select_related(
            "ci_type", "asset", "software_product", "department", "owner",
            "technical_owner", "vendor", "service_catalogue_item",
            "support_group",
        )
        params = self.request.query_params

        q = params.get("search") or params.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(ci_number__icontains=q)
                | Q(hostname__icontains=q)
                | Q(dns_name__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(description__icontains=q)
                | Q(location__icontains=q)
            )
        simple_filters = {
            "status": "status",
            "criticality": "criticality",
            "environment": "environment",
            "lifecycle_state": "lifecycle_state",
            "source": "source",
            "monitoring_state": "monitoring_state",
            "data_classification": "data_classification",
            "validated_system_impact": "validated_system_impact",
            "asset": "asset_id",
            "software_product": "software_product_id",
            "department": "department_id",
            "owner": "owner_id",
            "technical_owner": "technical_owner_id",
            "vendor": "vendor_id",
            "service_catalogue_item": "service_catalogue_item_id",
        }
        for param, field in simple_filters.items():
            value = params.get(param)
            if value:
                qs = qs.filter(**{field: value})
        # frontend aliases
        if params.get("type"):
            qs = qs.filter(ci_type_id=params["type"])
        if params.get("category"):
            qs = qs.filter(ci_type__category=params["category"])
        if params.get("location"):
            qs = qs.filter(location__icontains=params["location"])
        if params.get("verified") not in (None, ""):
            if _bool_param(params.get("verified")):
                qs = qs.filter(last_verified_at__isnull=False)
            else:
                qs = qs.filter(last_verified_at__isnull=True)
        qs = _apply_date_range(qs, params.get("created_date_range"),
                               "created_at")
        qs = _apply_date_range(qs, params.get("updated_date_range"),
                               "updated_at")
        qs = _apply_date_range(qs, params.get("date_from") and (
            f"{params.get('date_from')},{params.get('date_to') or ''}"
        ), "created_at")

        ordering = params.get("ordering")
        if ordering in CI_ORDERING:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by("ci_number")
        return qs

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemSerializer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == "retrieve":
            context["include_history"] = True
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if not data.get("history"):
            data["history"] = ConfigurationItemHistorySerializer(
                instance.history.all()[:20], many=True,
            ).data
        return Response(data)

    def perform_create(self, serializer):
        try:
            obj = serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError(
                {"asset": "An active CI already links this asset."},
            ) from exc
        domain_service.record_history(
            obj, self.request.user, "created", source=obj.source,
        )

    def perform_update(self, serializer):
        changed = sorted(serializer.validated_data.keys())
        obj = serializer.save()
        obj.record_version = (obj.record_version or 1) + 1
        obj.save(update_fields=["record_version", "updated_at"])
        domain_service.record_history(
            obj, self.request.user, "updated",
            changed_fields={k: str(getattr(obj, k, "")) for k in changed},
            detail=", ".join(changed[:20]),
            source="manual",
        )

    def perform_destroy(self, instance):
        if not is_it_manager(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only managers/admins may delete CIs.")
        with transaction.atomic():
            active_rels = ConfigurationItemRelationship.objects.filter(
                is_deleted=False, status="active",
            ).filter(
                Q(source_ci=instance) | Q(target_ci=instance),
            ).select_for_update()
            for rel in active_rels:
                previous = rel.status
                rel.status = "inactive"
                rel.save(update_fields=["status", "updated_at"])
                ConfigurationItemHistory.objects.create(
                    configuration_item=instance,
                    relationship=rel,
                    actor=self.request.user,
                    event_type="relationship_deactivated",
                    previous_status=previous,
                    new_status="inactive",
                    detail=(
                        f"Deactivated on deletion of {instance.ci_number}: "
                        f"{rel.relationship_type}"
                    ),
                    source="manual",
                )
            log_action(
                actor=self.request.user, action="soft_delete", instance=instance,
                reason="CI deleted",
                details={"ci_number": instance.ci_number},
            )
            super().perform_destroy(instance)

    # -- actions ---------------------------------------------------------

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        ci = self.get_object()
        serializer = VerifyCISerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            domain_service.verify_ci(
                ci,
                request.user,
                note=serializer.validated_data.get("verification_note", ""),
                expected_record_version=serializer.validated_data.get(
                    "expected_record_version",
                ),
            )
        except domain_service.StaleVersionError as exc:
            raise StaleRecordError(str(exc))
        return Response(
            ConfigurationItemSerializer(ci, context={"request": request}).data,
        )

    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may retire CIs."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ci = self.get_object()
        serializer = RetireCISerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            ci, impact = domain_service.retire_ci(
                ci,
                request.user,
                reason=data["reason"],
                expected_record_version=data.get("expected_record_version"),
                acknowledge_impact=data.get("acknowledge_impact", False),
                retirement_date=data.get("retirement_date"),
            )
        except domain_service.StaleVersionError as exc:
            raise StaleRecordError(str(exc))
        except domain_service.AssetAssignedError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        except domain_service.ImpactRequiredError as exc:
            payload = {"detail": "Impact acknowledgement required."}
            payload.update(exc.impact)
            return Response(payload, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )

        replacement_id = data.get("replacement_ci")
        if replacement_id:
            replacement = ConfigurationItem.objects.filter(
                pk=replacement_id, is_deleted=False,
            ).first()
            if replacement:
                domain_service.replace_ci(ci, replacement, request.user)

        response_data = ConfigurationItemSerializer(
            ci, context={"request": request},
        ).data
        response_data["impact"] = impact
        return Response(response_data)

    @action(detail=True, methods=["get"])
    def dependencies(self, request, pk=None):
        ci = self.get_object()
        graph = build_dependency_graph(
            ci,
            view=request.query_params.get("view", "combined"),
            max_depth=request.query_params.get("depth", 5),
        )
        return Response(graph)

    @action(detail=True, methods=["get"])
    def dependents(self, request, pk=None):
        ci = self.get_object()
        graph = build_dependency_graph(
            ci, view="downstream",
            max_depth=request.query_params.get("depth", 5),
        )
        return Response(graph)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        ci = self.get_object()
        rows = ci.history.all()[:100]
        return Response(
            ConfigurationItemHistorySerializer(rows, many=True).data,
        )

    @action(detail=True, methods=["get"])
    def relationships(self, request, pk=None):
        ci = self.get_object()
        direction = request.query_params.get("direction", "both")
        qs = ConfigurationItemRelationship.objects.filter(
            is_deleted=False,
        ).select_related("source_ci", "target_ci")
        if direction == "outgoing":
            qs = qs.filter(source_ci=ci)
        elif direction == "incoming":
            qs = qs.filter(target_ci=ci)
        else:
            qs = qs.filter(Q(source_ci=ci) | Q(target_ci=ci))
        return list_response(
            request, qs.order_by("-created_at"),
            ConfigurationItemRelationshipSerializer, cap=500,
        )

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        ci = self.get_object()
        qs = ConfigurationItemTicketLink.objects.filter(
            configuration_item=ci, is_deleted=False,
        ).select_related("ticket", "configuration_item")
        return list_response(
            request, qs, ConfigurationItemTicketLinkSerializer, cap=500,
        )

    @action(detail=True, methods=["get"])
    def changes(self, request, pk=None):
        ci = self.get_object()
        qs = ConfigurationItemChangeLink.objects.filter(
            configuration_item=ci, is_deleted=False,
        ).select_related("change", "configuration_item")
        return list_response(
            request, qs, ConfigurationItemChangeLinkSerializer, cap=500,
        )

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        ci = self.get_object()
        payload = analyze_ci_impact(
            ci,
            proposed_status=request.query_params.get("proposed_status") or None,
            max_depth=request.query_params.get("depth", 5),
            include_tickets=_bool_param(request.query_params.get(
                "include_tickets",
            )),
            include_changes=_bool_param(request.query_params.get(
                "include_changes",
            )),
        )
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="sync-asset")
    def sync_asset(self, request, pk=None):
        ci = self.get_object()
        if not ci.asset_id:
            return Response(
                {"detail": "CI has no linked asset."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from assets.models import Asset

        asset = Asset.objects.filter(pk=ci.asset_id).first()
        if asset is None:
            return Response(
                {"detail": "Linked asset no longer exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        updated, created = domain_service.sync_asset_to_ci(
            asset, actor=request.user,
        )
        return Response(
            ConfigurationItemSerializer(
                updated or ci, context={"request": request},
            ).data,
        )

    @action(detail=True, methods=["get"], url_path="compare-baseline")
    def compare_baseline(self, request, pk=None):
        ci = self.get_object()
        baseline = None
        baseline_id = request.query_params.get("baseline_id")
        if baseline_id:
            baseline = ConfigurationBaseline.objects.filter(
                pk=baseline_id, is_deleted=False,
            ).first()
        else:
            baseline = (
                ConfigurationBaseline.objects.filter(
                    configuration_items=ci, status="approved",
                    is_deleted=False,
                ).order_by("-approved_at").first()
            )
        if baseline is None:
            return Response(
                {"detail": "No approved baseline found for this CI."},
                status=status.HTTP_404_NOT_FOUND,
            )
        diffs = baseline_service.compare_ci_to_baseline(ci, baseline)
        return Response({
            "baseline_id": baseline.id,
            "baseline_code": baseline.code,
            "ci_number": ci.ci_number,
            "diffs": diffs,
            "drift": bool(diffs),
        })


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

class ConfigurationItemRelationshipViewSet(viewsets.ModelViewSet):
    permission_classes = [RelationshipPermission]
    serializer_class = ConfigurationItemRelationshipSerializer

    def get_queryset(self):
        qs = ConfigurationItemRelationship.objects.filter(
            is_deleted=False,
        ).select_related("source_ci", "target_ci", "created_by")
        params = self.request.query_params
        for param in ("source_ci", "target_ci", "relationship_type",
                      "status", "confidence", "source"):
            value = params.get(param)
            if value:
                qs = qs.filter(**{param: value})
        ci_value = params.get("ci") or params.get("target") or params.get("with_ci")
        if ci_value:
            qs = qs.filter(Q(source_ci=ci_value) | Q(target_ci=ci_value))
        q = params.get("search")
        if q:
            qs = qs.filter(
                Q(source_ci__name__icontains=q)
                | Q(target_ci__name__icontains=q)
                | Q(source_ci__ci_number__icontains=q)
                | Q(target_ci__ci_number__icontains=q)
            )
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemRelationshipSerializer, cap=500)

    def create(self, request, *args, **kwargs):
        relationship_type = (request.data or {}).get("relationship_type")
        if relationship_type in HIERARCHY_PARENT_DIRECTION:
            with transaction.atomic():
                domain_service._serialize_hierarchy_mutations()
                return super().create(request, *args, **kwargs)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        requested_type = (request.data or {}).get(
            "relationship_type", instance.relationship_type,
        )
        if (
            requested_type in HIERARCHY_PARENT_DIRECTION
            or instance.relationship_type in HIERARCHY_PARENT_DIRECTION
        ):
            with transaction.atomic():
                domain_service._serialize_hierarchy_mutations()
                return super().update(
                    request, *args, partial=partial, **kwargs,
                )
        return super().update(request, *args, partial=partial, **kwargs)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError("Duplicate relationship.") from exc

    def perform_update(self, serializer):
        obj = serializer.save()
        ConfigurationItemHistory.objects.create(
            configuration_item=obj.source_ci,
            relationship=obj,
            actor=self.request.user,
            event_type="relationship_updated",
            new_status=obj.status,
            detail=f"{obj.relationship_type} -> {obj.target_ci.ci_number}",
            source="manual",
        )

    def perform_destroy(self, instance):
        with transaction.atomic():
            ConfigurationItemHistory.objects.create(
                configuration_item=instance.source_ci,
                relationship=instance,
                actor=self.request.user,
                event_type="relationship_deleted",
                previous_status=instance.status or "",
                new_status="deleted",
                detail=f"{instance.relationship_type} -> {instance.target_ci.ci_number}",
                source="manual",
            )
            log_action(
                actor=self.request.user,
                action="soft_delete",
                instance=instance,
                reason="relationship deleted",
                details={
                    "source_ci": instance.source_ci_id,
                    "target_ci": instance.target_ci_id,
                    "relationship_type": instance.relationship_type,
                },
            )
            super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may activate relationships."},
                status=status.HTTP_403_FORBIDDEN,
            )
        rel = self.get_object()
        try:
            rel = domain_service.activate_relationship(rel, request.user)
        except Exception as exc:  # ValidationError from validation helpers
            from django.core.exceptions import ValidationError as DjangoVE

            if isinstance(exc, DjangoVE):
                raise DRFValidationError(exc.messages) from exc
            raise
        return Response(
            ConfigurationItemRelationshipSerializer(rel).data,
        )

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may deactivate relationships."},
                status=status.HTTP_403_FORBIDDEN,
            )
        rel = domain_service.deactivate_relationship(
            self.get_object(), request.user,
        )
        return Response(
            ConfigurationItemRelationshipSerializer(rel).data,
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may confirm relationships."},
                status=status.HTTP_403_FORBIDDEN,
            )
        rel = self.get_object()
        try:
            rel = domain_service.confirm_relationship(rel, request.user)
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjangoVE

            if isinstance(exc, DjangoVE):
                raise DRFValidationError(exc.messages) from exc
            raise
        return Response(
            ConfigurationItemRelationshipSerializer(rel).data,
        )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class ConfigurationItemHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HistoryPermission]
    serializer_class = ConfigurationItemHistorySerializer

    def get_queryset(self):
        qs = ConfigurationItemHistory.objects.all().select_related(
            "actor", "configuration_item", "relationship",
        )
        params = self.request.query_params
        if params.get("configuration_item"):
            qs = qs.filter(configuration_item_id=params["configuration_item"])
        if params.get("relationship"):
            qs = qs.filter(relationship_id=params["relationship"])
        if params.get("event_type"):
            qs = qs.filter(event_type=params["event_type"])
        if params.get("actor"):
            qs = qs.filter(actor_id=params["actor"])
        qs = _apply_date_range(qs, params.get("date_range"), "created_at")
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemHistorySerializer, cap=500)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

class ConfigurationBaselineViewSet(viewsets.ModelViewSet):
    permission_classes = [BaselinePermission]
    serializer_class = ConfigurationBaselineSerializer

    def get_queryset(self):
        qs = ConfigurationBaseline.objects.filter(
            is_deleted=False,
        ).select_related("created_by", "approved_by", "service")
        params = self.request.query_params
        for param in ("status", "scope_type", "service"):
            if params.get(param):
                qs = qs.filter(**{param: params[param]})
        if params.get("configuration_items"):
            qs = qs.filter(
                configuration_items=params["configuration_items"],
            )
        q = params.get("search")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationBaselineSerializer, cap=500)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post", "patch"])
    def approve(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may approve baselines."},
                status=status.HTTP_403_FORBIDDEN,
            )
        baseline = self.get_object()
        try:
            baseline_service.approve_baseline(baseline, request.user)
        except PermissionError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ConfigurationBaselineSerializer(
                baseline, context={"request": request},
            ).data,
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        baseline = self.get_object()
        try:
            baseline_service.submit_baseline(baseline, request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ConfigurationBaselineSerializer(baseline).data,
        )

    @action(detail=True, methods=["post"])
    def supersede(self, request, pk=None):
        baseline = self.get_object()
        try:
            baseline_service.supersede_baseline(baseline, request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ConfigurationBaselineSerializer(baseline).data,
        )

    @action(detail=True, methods=["get"])
    def compare(self, request, pk=None):
        baseline = self.get_object()
        if not baseline.snapshot:
            return Response(
                {"detail": "Baseline has no snapshot."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        results = []
        cis = baseline.configuration_items.select_related("ci_type").prefetch_related(
            Prefetch(
                "outgoing_relationships",
                queryset=ConfigurationItemRelationship.objects.filter(
                    status="active", is_deleted=False,
                ).select_related("target_ci"),
                to_attr="active_outgoing_relationships",
            ),
        )[:200]
        for ci in cis:
            for diff in baseline_service.compare_ci_to_baseline(ci, baseline):
                entry = dict(diff)
                entry["ci_id"] = ci.id
                entry["ci_number"] = ci.ci_number
                results.append(entry)
        return Response({
            "baseline_id": baseline.id,
            "baseline_code": baseline.code,
            "diffs": results,
            "drift": bool(results),
        })


# ---------------------------------------------------------------------------
# Drift findings
# ---------------------------------------------------------------------------

class ConfigurationDriftFindingViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [DriftPermission]
    serializer_class = ConfigurationDriftFindingSerializer

    def get_queryset(self):
        qs = ConfigurationDriftFinding.objects.filter(
            is_deleted=False,
        ).select_related(
            "configuration_item", "baseline", "acknowledged_by",
            "resolved_by",
        )
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("severity"):
            qs = qs.filter(severity=params["severity"])
        if params.get("finding_type") or params.get("type"):
            qs = qs.filter(
                finding_type=params.get("finding_type") or params.get("type"),
            )
        ci_id = params.get("configuration_item") or params.get("ci")
        if ci_id:
            qs = qs.filter(configuration_item_id=ci_id)
        if params.get("baseline"):
            qs = qs.filter(baseline_id=params["baseline"])
        qs = _apply_date_range(qs, params.get("detected_date"),
                               "detected_at")
        qs = _apply_date_range(qs, params.get("date_from") and (
            f"{params.get('date_from')},{params.get('date_to') or ''}"
        ), "detected_at")
        q = params.get("search")
        if q:
            qs = qs.filter(
                Q(field_name__icontains=q)
                | Q(configuration_item__name__icontains=q)
                | Q(configuration_item__ci_number__icontains=q)
            )
        return qs.order_by("-detected_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationDriftFindingSerializer, cap=500)

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Drift findings are system-generated."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Drift findings are immutable; use workflow actions."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Drift findings cannot be deleted."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        finding = self.get_object()
        try:
            finding = baseline_service.acknowledge_finding(finding,
                                                           request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ConfigurationDriftFindingSerializer(finding).data,
        )

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may resolve findings."},
                status=status.HTTP_403_FORBIDDEN,
            )
        finding = self.get_object()
        ser = DriftActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        note = ser.get_note()
        try:
            finding = baseline_service.resolve_finding(
                finding, request.user, note,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ConfigurationDriftFindingSerializer(finding).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        finding = self.get_object()
        if finding.severity == "critical" and not is_system_admin(request.user):
            return Response(
                {"detail":
                 "Only system admins may accept critical drift findings."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not is_it_manager(request.user):
            return Response(
                {"detail": "Only managers/admins may accept findings."},
                status=status.HTTP_403_FORBIDDEN,
            )
        finding = baseline_service.accept_finding(finding, request.user)
        return Response(ConfigurationDriftFindingSerializer(finding).data)

    @action(detail=True, methods=["post"], url_path="false-positive")
    def false_positive(self, request, pk=None):
        if not is_it_manager(request.user):
            return Response(
                {"detail":
                 "Only managers/admins may mark findings as false positive."},
                status=status.HTTP_403_FORBIDDEN,
            )
        finding = self.get_object()
        ser = DriftActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        note = ser.get_note()
        try:
            finding = baseline_service.mark_false_positive(
                finding, request.user, note,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ConfigurationDriftFindingSerializer(finding).data)


# ---------------------------------------------------------------------------
# Service mapping
# ---------------------------------------------------------------------------

class CMDBServiceProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [CMDBPermission]
    serializer_class = CMDBServiceProfileSerializer

    def get_queryset(self):
        qs = CMDBServiceProfile.objects.filter(
            is_deleted=False,
        ).select_related(
            "service", "service_owner", "technical_owner", "support_group",
        )
        params = self.request.query_params
        if params.get("criticality"):
            qs = qs.filter(criticality=params["criticality"])
        if params.get("service_tier"):
            qs = qs.filter(service_tier=params["service_tier"])
        return qs.order_by("service__name")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             CMDBServiceProfileSerializer, cap=500)

    def perform_create(self, serializer):
        if not is_it_manager(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "Only managers/admins may manage service profiles.",
            )
        try:
            serializer.save()
        except IntegrityError as exc:
            raise DRFValidationError(
                {"detail": "A service profile for this service already exists."},
            ) from exc

    def perform_update(self, serializer):
        if not is_it_manager(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "Only managers/admins may manage service profiles.",
            )
        try:
            serializer.save()
        except IntegrityError as exc:
            raise DRFValidationError(
                {"detail": "A service profile for this service already exists."},
            ) from exc


class ServiceConfigurationItemLinkViewSet(viewsets.ModelViewSet):
    permission_classes = [CMDBPermission]
    serializer_class = ServiceConfigurationItemLinkSerializer

    def get_queryset(self):
        qs = ServiceConfigurationItemLink.objects.filter(
            is_deleted=False,
        ).select_related("service", "configuration_item")
        params = self.request.query_params
        if params.get("service"):
            qs = qs.filter(service_id=params["service"])
        if params.get("configuration_item") or params.get("ci"):
            qs = qs.filter(
                configuration_item_id=(
                    params.get("configuration_item") or params.get("ci")
                ),
            )
        if params.get("role"):
            qs = qs.filter(role=params["role"])
        return qs.order_by("service__name", "configuration_item__ci_number")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ServiceConfigurationItemLinkSerializer, cap=500)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError(
                {"detail": "A matching service-CI link already exists."},
            ) from exc


class ConfigurationItemTicketLinkViewSet(viewsets.ModelViewSet):
    permission_classes = [CMDBPermission]
    serializer_class = ConfigurationItemTicketLinkSerializer

    def get_queryset(self):
        qs = ConfigurationItemTicketLink.objects.filter(
            is_deleted=False,
        ).select_related("ticket", "configuration_item")
        params = self.request.query_params
        if params.get("configuration_item"):
            qs = qs.filter(configuration_item_id=params["configuration_item"])
        if params.get("ticket"):
            qs = qs.filter(ticket_id=params["ticket"])
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemTicketLinkSerializer, cap=500)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError(
                {"detail": "A matching ticket-CI link already exists."},
            ) from exc


class ConfigurationItemChangeLinkViewSet(viewsets.ModelViewSet):
    permission_classes = [CMDBPermission]
    serializer_class = ConfigurationItemChangeLinkSerializer

    def get_queryset(self):
        qs = ConfigurationItemChangeLink.objects.filter(
            is_deleted=False,
        ).select_related("change", "configuration_item")
        params = self.request.query_params
        if params.get("configuration_item"):
            qs = qs.filter(configuration_item_id=params["configuration_item"])
        if params.get("change"):
            qs = qs.filter(change_id=params["change"])
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return list_response(request, self.get_queryset(),
                             ConfigurationItemChangeLinkSerializer, cap=500)

    def perform_create(self, serializer):
        try:
            serializer.save(created_by=self.request.user)
        except IntegrityError as exc:
            raise DRFValidationError(
                {"detail": "A matching change-CI link already exists."},
            ) from exc


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _dashboard_payload(params):
    base = ConfigurationItem.objects.filter(is_deleted=False)
    if params.get("department"):
        base = base.filter(department_id=params["department"])
    if params.get("ci_type") or params.get("type"):
        base = base.filter(
            ci_type_id=params.get("ci_type") or params.get("type"),
        )
    if params.get("environment"):
        base = base.filter(environment=params["environment"])
    if params.get("criticality"):
        base = base.filter(criticality=params["criticality"])
    if params.get("status"):
        base = base.filter(status=params["status"])
    qs = _apply_date_range(base, params.get("date_from") and (
        f"{params.get('date_from')},{params.get('date_to') or ''}"
    ), "created_at")

    total = qs.count()
    active = qs.filter(status="active").count()
    critical = qs.filter(criticality="critical").count()
    unverified_qs = impact_service.find_unverified_configuration_items(
        VERIFICATION_THRESHOLD_DAYS,
    )
    if params.get("department"):
        unverified_qs = unverified_qs.filter(department_id=params["department"])
    if params.get("environment"):
        unverified_qs = unverified_qs.filter(environment=params["environment"])
    unverified_count = unverified_qs.count()

    most_recent_unverified = None
    latest = unverified_qs.order_by("-updated_at").first()
    if latest is not None:
        most_recent_unverified = {
            "id": latest.id,
            "ci_number": latest.ci_number,
            "name": latest.name,
            "updated_at": latest.updated_at.isoformat(),
            "last_verified_at": None,
        }

    open_drift = ConfigurationDriftFinding.objects.filter(
        is_deleted=False, status="open",
    )
    open_drift_count = open_drift.count()
    critical_open_drift = open_drift.filter(severity="critical").count()
    high_open_drift = open_drift.filter(severity="high").count()

    by_status = {
        row["status"]: row["c"]
        for row in qs.values("status").annotate(c=Count("id")).order_by()
    }
    by_criticality = {
        row["criticality"]: row["c"]
        for row in qs.values("criticality").annotate(c=Count("id")).order_by()
    }
    by_environment = {
        row["environment"]: row["c"]
        for row in qs.values("environment").annotate(c=Count("id")).order_by()
    }
    by_type = {
        row["ci_type__name"]: row["c"]
        for row in qs.values("ci_type__name").annotate(
            c=Count("id"),
        ).order_by()[:20]
    }

    orphans = find_orphan_configuration_items().count()
    unowned = qs.filter(owner__isnull=True, technical_owner__isnull=True).count()
    failed = qs.filter(status="failed").count()
    degraded = qs.filter(status="degraded").count()
    production = qs.filter(environment="production").count()
    monitored = qs.filter(monitoring_state="monitored").count()
    not_monitored = qs.filter(monitoring_state="not_monitored").count()

    from services.models import ServiceCatalogueItem

    services_total = ServiceCatalogueItem.objects.filter(
        is_deleted=False,
    ).count()
    mapped_service_ids = set(
        ServiceConfigurationItemLink.objects.filter(
            is_deleted=False,
        ).values_list("service_id", flat=True)
    ) | set(
        CMDBServiceProfile.objects.filter(
            is_deleted=False,
        ).values_list("service_id", flat=True)
    )
    spof = find_single_points_of_failure()
    spof_service_ids = {s["service_id"] for s in spof}

    from assets.models import Asset
    from licensing.models import SoftwareProduct

    assets_total = Asset.objects.filter(is_deleted=False).count()
    assets_with_ci = Asset.objects.filter(
        is_deleted=False, configuration_items__is_deleted=False,
    ).distinct().count()
    products_total = SoftwareProduct.objects.filter(is_deleted=False).count()
    products_with_ci = SoftwareProduct.objects.filter(
        is_deleted=False, configuration_items__is_deleted=False,
    ).distinct().count()

    recent_history = [
        {
            "event_type": row["event_type"],
            "detail": (row["detail"] or "")[:200],
            "created_at": row["created_at"].isoformat(),
            "ci_number": (
                row["configuration_item__ci_number"]
                if row["configuration_item__ci_number"] else ""
            ),
            "actor": row["actor__username"] or "",
        }
        for row in ConfigurationItemHistory.objects.filter(
            configuration_item__isnull=False,
        ).values(
            "event_type", "detail", "created_at",
            "configuration_item__ci_number", "actor__username",
        ).order_by("-created_at")[:DASHBOARD_RECENT_LIMIT]
    ]
    recent_verifications = [
        {
            "id": row["id"],
            "ci_number": row["ci_number"],
            "name": row["name"],
            "last_verified_at": row["last_verified_at"].isoformat(),
        }
        for row in qs.filter(
            last_verified_at__isnull=False,
        ).order_by("-last_verified_at").values(
            "id", "ci_number", "name", "last_verified_at",
        )[:DASHBOARD_RECENT_LIMIT]
    ]
    recent_drift = [
        {
            "id": row["id"],
            "finding_type": row["finding_type"],
            "severity": row["severity"],
            "status": row["status"],
            "ci_number": row["configuration_item__ci_number"],
            "detected_at": row["detected_at"].isoformat(),
        }
        for row in ConfigurationDriftFinding.objects.filter(
            is_deleted=False,
        ).values(
            "id", "finding_type", "severity", "status",
            "configuration_item__ci_number", "detected_at",
        ).order_by("-detected_at")[:DASHBOARD_RECENT_LIMIT]
    ]

    return {
        # frontend contract keys
        "total_cis": total,
        "active_cis": active,
        "critical_cis": critical,
        "unverified_cis": unverified_count,
        "open_drift_findings": open_drift_count,
        "generated_at": timezone.now().isoformat(),
        "most_recent_unverified": most_recent_unverified,
        # extended metrics
        "by_status": by_status,
        "by_criticality": by_criticality,
        "by_environment": by_environment,
        "by_ci_type": by_type,
        "orphan_cis": orphans,
        "unowned_cis": unowned,
        "failed_cis": failed,
        "degraded_cis": degraded,
        "production_cis": production,
        "monitored_cis": monitored,
        "not_monitored_cis": not_monitored,
        "critical_open_drift": critical_open_drift,
        "high_open_drift": high_open_drift,
        "verification_threshold_days": VERIFICATION_THRESHOLD_DAYS,
        "services_total": services_total,
        "services_mapped": len(mapped_service_ids),
        "services_with_spof": len(spof_service_ids),
        "assets_total": assets_total,
        "assets_without_ci": max(assets_total - assets_with_ci, 0),
        "software_products_total": products_total,
        "software_products_without_ci": max(
            products_total - products_with_ci, 0,
        ),
        "recent_history": recent_history,
        "recent_verifications": recent_verifications,
        "recent_drift": recent_drift,
    }


class DashboardView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request):
        return Response(_dashboard_payload(request.query_params))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

REPORT_KINDS = (
    "coverage", "verification_age", "orphans", "ownership_gaps",
    "relationship_coverage", "drift", "critical_deps", "asset_sync",
    "software_sync", "unverified",
)

_LABEL_COL = {"key": "label", "label": "CI"}
_VALUE_COL = {"key": "value", "label": "Value"}
_COUNT_COL = {"key": "count", "label": "Count"}


def _report_filters(params, qs):
    if params.get("department"):
        qs = qs.filter(department_id=params["department"])
    if params.get("ci_type") or params.get("type"):
        qs = qs.filter(ci_type_id=params.get("ci_type") or params.get("type"))
    if params.get("environment"):
        qs = qs.filter(environment=params["environment"])
    if params.get("criticality"):
        qs = qs.filter(criticality=params["criticality"])
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    return qs


def _report_base(params):
    qs = ConfigurationItem.objects.filter(is_deleted=False).select_related(
        "ci_type", "department", "owner", "technical_owner",
    )
    return _report_filters(params, qs)


def build_report(kind, params):
    """Return {kind, rows, columns, summary, generated_at}."""
    if kind not in REPORT_KINDS:
        kind = "coverage"
    if kind == "unverified":
        kind = "verification_age"

    generated_at = timezone.now().isoformat()

    if kind == "coverage":
        base = _report_base(params)
        rows = [{"label": "Total CIs", "value": "", "count": base.count()}]
        for row in base.values("status").annotate(
            c=Count("id"),
        ).order_by("status"):
            rows.append({
                "label": f"Status: {row['status']}", "value": row["status"],
                "count": row["c"],
            })
        for row in base.values("criticality").annotate(
            c=Count("id"),
        ).order_by("criticality"):
            rows.append({
                "label": f"Criticality: {row['criticality']}",
                "value": row["criticality"], "count": row["c"],
            })
        for row in base.values("ci_type__name").annotate(
            c=Count("id"),
        ).order_by("ci_type__name"):
            rows.append({
                "label": f"Type: {row['ci_type__name'] or '-'}",
                "value": row["ci_type__name"] or "-", "count": row["c"],
            })
        summary = {
            "total": base.count(),
            "active": base.filter(status="active").count(),
            "critical": base.filter(criticality="critical").count(),
            "production": base.filter(environment="production").count(),
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "verification_age":
        base = _report_base(params)
        threshold = VERIFICATION_THRESHOLD_DAYS
        cutoff = timezone.now() - timezone.timedelta(days=threshold)
        never = base.filter(
            last_verified_at__isnull=True,
        ).exclude(status__in=("retired", "disposed"))
        overdue = base.filter(
            last_verified_at__lt=cutoff,
        ).exclude(status__in=("retired", "disposed"))
        rows = []
        for ci in list(never.order_by("ci_number")[:200]):
            rows.append({
                "label": f"{ci.ci_number} {ci.name}",
                "value": "never verified",
                "count": 0,
            })
        for ci in list(overdue.order_by("last_verified_at")[:200]):
            age = (timezone.now() - ci.last_verified_at).days
            rows.append({
                "label": f"{ci.ci_number} {ci.name}",
                "value": f"{age} days",
                "count": age,
            })
        summary = {
            "never_verified": never.count(),
            "overdue": overdue.count(),
            "threshold_days": threshold,
            "verified": base.filter(
                last_verified_at__gte=cutoff,
            ).count(),
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "orphans":
        base = _report_base(params)
        orphans = find_orphan_configuration_items()
        ids = set(base.values_list("id", flat=True))
        rows = []
        for ci in [c for c in orphans if c.id in ids][:500]:
            rows.append({
                "label": f"{ci.ci_number} {ci.name}",
                "value": ci.status,
                "count": ci.outgoing_relationships.filter(
                    is_deleted=False, status="active",
                ).count() + ci.incoming_relationships.filter(
                    is_deleted=False, status="active",
                ).count(),
            })
        summary = {
            "orphan_cis": len([c for c in orphans if c.id in ids]),
            "total_cis": base.count(),
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "ownership_gaps":
        base = _report_base(params)
        missing_owner = base.filter(
            owner__isnull=True, technical_owner__isnull=True,
        )
        rows = []
        for ci in missing_owner[:500]:
            rows.append({
                "label": f"{ci.ci_number} {ci.name}",
                "value": ci.department.name if ci.department_id else "-",
                "count": 1 if ci.support_group_id else 0,
            })
        summary = {
            "missing_owner_and_technical": missing_owner.count(),
            "missing_owner": base.filter(owner__isnull=True).count(),
            "missing_technical_owner": base.filter(
                technical_owner__isnull=True,
            ).count(),
            "missing_support_group": base.filter(
                support_group__isnull=True,
            ).count(),
        }
        columns = [_LABEL_COL,
                   {"key": "value", "label": "Department"},
                   {"key": "count", "label": "Has Support Group"}]

    elif kind == "relationship_coverage":
        base = _report_base(params)
        rel_count = ConfigurationItemRelationship.objects.filter(
            is_deleted=False, status="active",
        ).count()
        rows = [
            {
                "label": "Active relationships",
                "value": "", "count": rel_count,
            },
        ]
        for row in ConfigurationItemRelationship.objects.filter(
            is_deleted=False, status="active",
        ).values("relationship_type").annotate(c=Count("id")).order_by():
            rows.append({
                "label": f"Type: {row['relationship_type']}",
                "value": row["relationship_type"], "count": row["c"],
            })
        total = base.count()
        orphan_count = find_orphan_configuration_items().count()
        covered = max(total - orphan_count, 0)
        pct = round((covered / total) * 100, 1) if total else 0.0
        rows.insert(0, {
            "label": "CIs with at least one link",
            "value": f"{pct}%", "count": covered,
        })
        summary = {
            "total_cis": total,
            "covered_cis": covered,
            "orphan_cis": orphan_count,
            "coverage_pct": pct,
            "total_relationships": rel_count,
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "drift":
        findings = ConfigurationDriftFinding.objects.filter(is_deleted=False)
        rows = []
        for row in findings.filter(status="open").values(
            "severity",
        ).annotate(c=Count("id")).order_by("severity"):
            rows.append({
                "label": f"Open / {row['severity']}",
                "value": row["severity"], "count": row["c"],
            })
        for row in findings.values("finding_type").annotate(
            c=Count("id"),
        ).order_by("finding_type"):
            rows.append({
                "label": f"Type: {row['finding_type']}",
                "value": row["finding_type"], "count": row["c"],
            })
        summary = {
            "open": findings.filter(status="open").count(),
            "acknowledged": findings.filter(status="acknowledged").count(),
            "resolved": findings.filter(status="resolved").count(),
            "accepted": findings.filter(status="accepted").count(),
            "false_positive": findings.filter(
                status="false_positive",
            ).count(),
            "critical_open": findings.filter(
                status="open", severity="critical",
            ).count(),
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "critical_deps":
        rows = []
        rels = ConfigurationItemRelationship.objects.filter(
            is_deleted=False, status="active",
        ).filter(
            Q(source_ci__criticality__in=("critical", "high"))
            | Q(target_ci__criticality__in=("critical", "high")),
        ).select_related("source_ci", "target_ci")
        seen = 0
        for rel in rels:
            if seen >= 500:
                break
            rows.append({
                "label": (
                    f"{rel.source_ci.ci_number} -{rel.relationship_type}-> "
                    f"{rel.target_ci.ci_number}"
                ),
                "value": (
                    rel.source_ci.criticality
                    if rel.source_ci.criticality in ("critical", "high")
                    else rel.target_ci.criticality
                ),
                "count": 1,
            })
            seen += 1
        summary = {
            "critical_cis": ConfigurationItem.objects.filter(
                is_deleted=False, criticality="critical",
            ).count(),
            "high_cis": ConfigurationItem.objects.filter(
                is_deleted=False, criticality="high",
            ).count(),
            "critical_relationships": rels.count(),
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "asset_sync":
        from assets.models import Asset

        assets = Asset.objects.filter(is_deleted=False).select_related(
            "category", "department",
        )
        if params.get("department"):
            assets = assets.filter(department_id=params["department"])
        total_assets = assets.count()
        assets_with_ci = assets.filter(
            configuration_items__is_deleted=False,
        ).distinct().count()
        assets_without_ci = max(total_assets - assets_with_ci, 0)
        manual_cis = ConfigurationItem.objects.filter(
            asset__in=assets, source="manual", is_deleted=False,
        ).values("asset_id").distinct().count()

        sample = list(assets.order_by("asset_tag")[:500])
        asset_ids = [a.id for a in sample]
        ci_map = {}
        for ci in ConfigurationItem.objects.filter(
            asset_id__in=asset_ids, is_deleted=False,
        ).order_by("id"):
            ci_map.setdefault(ci.asset_id, ci)

        rows = []
        for asset in sample:
            ci = ci_map.get(asset.id)
            if ci:
                rows.append({
                    "label": f"{asset.asset_tag} {asset.name}",
                    "value": f"{ci.ci_number} ({ci.source})",
                    "count": 1,
                })
            else:
                rows.append({
                    "label": f"{asset.asset_tag} {asset.name}",
                    "value": "missing CI", "count": 0,
                })
        summary = {
            "assets_total": total_assets,
            "assets_with_ci": assets_with_ci,
            "assets_without_ci": assets_without_ci,
            "manual_cis": manual_cis,
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    elif kind == "software_sync":
        from licensing.models import SoftwareProduct

        products = SoftwareProduct.objects.filter(is_deleted=False)
        total_products = products.count()
        products_with_ci = products.filter(
            configuration_items__is_deleted=False,
        ).distinct().count()
        products_without_ci = max(total_products - products_with_ci, 0)
        manual_cis = ConfigurationItem.objects.filter(
            software_product__in=products, source="manual", is_deleted=False,
        ).values("software_product_id").distinct().count()

        sample = list(products.order_by("name")[:500])
        product_ids = [p.id for p in sample]
        ci_map = {}
        for ci in ConfigurationItem.objects.filter(
            software_product_id__in=product_ids, is_deleted=False,
        ).order_by("id"):
            ci_map.setdefault(ci.software_product_id, ci)

        rows = []
        for product in sample:
            ci = ci_map.get(product.id)
            if ci:
                rows.append({
                    "label": product.name,
                    "value": f"{ci.ci_number} ({ci.source})",
                    "count": 1,
                })
            else:
                rows.append({
                    "label": product.name,
                    "value": "missing CI", "count": 0,
                })
        summary = {
            "products_total": total_products,
            "products_with_ci": products_with_ci,
            "products_without_ci": products_without_ci,
            "manual_cis": manual_cis,
        }
        columns = [_LABEL_COL, _VALUE_COL, _COUNT_COL]

    else:  # pragma: no cover - guarded by REPORT_KINDS
        rows, columns, summary = [], [_LABEL_COL], {}

    return {
        "kind": kind,
        "rows": rows,
        "columns": columns,
        "summary": summary,
        "generated_at": generated_at,
    }


class ReportsView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request, kind=None):
        kind = kind or request.query_params.get("kind") or "coverage"
        payload = build_report(kind, request.query_params)
        return Response(payload)


# ---------------------------------------------------------------------------
# Verification queue
# ---------------------------------------------------------------------------

def _verification_rows(params):
    qs = find_unverified_configuration_items(VERIFICATION_THRESHOLD_DAYS)
    qs = qs.select_related(
        "asset", "service_catalogue_item", "vendor", "support_group",
    )
    if params.get("ci_type") or params.get("type"):
        qs = qs.filter(ci_type_id=params.get("ci_type") or params.get("type"))
    if params.get("department"):
        qs = qs.filter(department_id=params["department"])
    if params.get("environment"):
        qs = qs.filter(environment=params["environment"])
    rows = []
    for ci in qs[:500]:
        entry = ConfigurationItemSerializer(
            ci, context={"request": None},
        ).data
        entry["verification_status"] = verification_status_for(ci)
        entry["ci_id"] = ci.id
        entry["verified_at"] = (
            ci.last_verified_at.isoformat() if ci.last_verified_at else None
        )
        entry["age_days"] = (
            (timezone.now() - ci.last_verified_at).days
            if ci.last_verified_at else None
        )
        rows.append(entry)
    return rows


class VerificationQueueView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request):
        return Response(_verification_rows(request.query_params))


class VerificationVerifyView(APIView):
    permission_classes = [CMDBPermission]

    def post(self, request, pk):
        ci = ConfigurationItem.objects.filter(pk=pk, is_deleted=False).first()
        if ci is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND,
            )
        serializer = VerifyCISerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            domain_service.verify_ci(
                ci,
                request.user,
                note=serializer.validated_data.get("verification_note", ""),
                expected_record_version=serializer.validated_data.get(
                    "expected_record_version",
                ),
            )
        except domain_service.StaleVersionError as exc:
            raise StaleRecordError(str(exc))
        return Response(
            ConfigurationItemSerializer(ci, context={"request": request}).data,
        )


# ---------------------------------------------------------------------------
# Service graph / impact / SPOF
# ---------------------------------------------------------------------------

class ServiceGraphView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request, pk):
        from services.models import ServiceCatalogueItem

        service = ServiceCatalogueItem.objects.filter(
            pk=pk, is_deleted=False,
        ).first()
        if service is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND,
            )
        graph = get_service_dependency_graph(
            service,
            max_depth=request.query_params.get("depth", 5),
        )
        return Response(graph)


class ServiceImpactView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request, pk):
        from services.models import ServiceCatalogueItem

        service = ServiceCatalogueItem.objects.filter(
            pk=pk, is_deleted=False,
        ).first()
        if service is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND,
            )
        link_ids = list(
            ServiceConfigurationItemLink.objects.filter(
                service=service, is_deleted=False,
            ).values_list("configuration_item_id", flat=True)
        )
        cis = ConfigurationItem.objects.filter(
            id__in=link_ids, is_deleted=False,
        ).select_related("ci_type")
        affected = set()
        truncated = False
        for ci in cis:
            ids, trunc = impact_service.get_downstream_dependents(ci)
            affected |= ids
            truncated = truncated or trunc
        affected -= set(link_ids)
        affected_rows = [
            {
                "id": row.id,
                "ci_number": row.ci_number,
                "name": row.name,
                "status": row.status,
                "criticality": row.criticality,
            }
            for row in ConfigurationItem.objects.filter(
                id__in=affected,
            ).order_by("ci_number")[:500]
        ]
        spof = [
            s for s in find_single_points_of_failure(service=service)
        ]
        return Response({
            "service_id": service.id,
            "service_name": service.name,
            "linked_cis": link_ids,
            "affected_cis": affected_rows,
            "affected_count": len(affected_rows),
            "single_points_of_failure": spof,
            "truncated": truncated,
        })


class ServiceSPOFView(APIView):
    permission_classes = [CMDBPermission]

    def get(self, request, pk):
        from services.models import ServiceCatalogueItem

        service = ServiceCatalogueItem.objects.filter(
            pk=pk, is_deleted=False,
        ).first()
        if service is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND,
            )
        spof = find_single_points_of_failure(service=service)
        return Response({
            "service_id": service.id,
            "service_name": service.name,
            "single_points_of_failure": spof,
            "count": len(spof),
        })
