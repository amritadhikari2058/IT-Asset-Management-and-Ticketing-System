from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.models import AuditLog
from .models import (
    ConfigurationItemType, ConfigurationItem, ConfigurationItemRelationship,
    ConfigurationItemHistory, ConfigurationBaseline, ConfigurationDriftFinding,
    CMDBServiceProfile, ServiceConfigurationItemLink,
    ConfigurationItemTicketLink, ConfigurationItemChangeLink,
)
from .serializers import (
    ConfigurationItemTypeSerializer, ConfigurationItemSerializer,
    ConfigurationItemRelationshipSerializer, ConfigurationItemHistorySerializer,
    ConfigurationBaselineSerializer, ConfigurationDriftFindingSerializer,
    CMDBServiceProfileSerializer, ServiceConfigurationItemLinkSerializer,
    ConfigurationItemTicketLinkSerializer, ConfigurationItemChangeLinkSerializer,
    VerifyCISerializer, RetireCISerializer,
)
from .permissions import is_staff, is_system_admin, is_it_manager, CMDBPermission

class ConfigurationItemTypeViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationItemType.objects.all()
    serializer_class = ConfigurationItemTypeSerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        qs = ConfigurationItemType.objects.filter(is_deleted=False)
        if self.request.query_params.get("is_active") is not None:
            qs = qs.filter(is_active=self.request.query_params.get("is_active").lower()=="true")
        return qs.order_by("name")

class ConfigurationItemViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationItem.objects.all()
    serializer_class = ConfigurationItemSerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        qs = ConfigurationItem.objects.filter(is_deleted=False).select_related("ci_type","asset","software_product","department","owner","technical_owner","vendor")
        q = self.request.query_params.get("search") or self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q)|Q(ci_number__icontains=q)|Q(hostname__icontains=q)|Q(dns_name__icontains=q)|Q(serial_number__icontains=q))
        for param, field in [("status","status"),("criticality","criticality"),("environment","environment"),("ci_type","ci_type"),("asset","asset"),("software_product","software_product"),("department","department")]:
            v = self.request.query_params.get(param)
            if v:
                qs = qs.filter(**{field: v})
        return qs.order_by("ci_number")
    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        ConfigurationItemHistory.objects.create(configuration_item=obj, actor=self.request.user, event_type="created", source="manual")
    def perform_update(self, serializer):
        obj = serializer.save()
        obj.record_version = (obj.record_version or 1) + 1
        obj.save(update_fields=["record_version","updated_at"])
        ConfigurationItemHistory.objects.create(configuration_item=obj, actor=self.request.user, event_type="updated", source="manual")

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        ci = self.get_object()
        ser = VerifyCISerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["expected_record_version"] != ci.record_version:
            return Response({"detail":"Stale version."}, status=status.HTTP_409_CONFLICT)
        ci.last_verified_at = timezone.now()
        ci.verified_by = request.user
        ci.save(update_fields=["last_verified_at","verified_by","updated_at"])
        ConfigurationItemHistory.objects.create(configuration_item=ci, actor=request.user, event_type="verified", source="manual", detail=ser.validated_data.get("verification_note",""))
        return Response(ConfigurationItemSerializer(ci).data)

    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        ci = self.get_object()
        ser = RetireCISerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["expected_record_version"] != ci.record_version:
            return Response({"detail":"Stale version."}, status=status.HTTP_409_CONFLICT)
        if not (is_system_admin(request.user) or is_it_manager(request.user)):
            return Response({"detail":"Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        ci.status = "retired"
        ci.lifecycle_state = "retired"
        ci.save(update_fields=["status","lifecycle_state","updated_at"])
        ConfigurationItemHistory.objects.create(configuration_item=ci, actor=request.user, event_type="retired", detail=ser.validated_data["reason"], source="manual")
        return Response(ConfigurationItemSerializer(ci).data)

    @action(detail=True, methods=["get"])
    def dependencies(self, request, pk=None):
        ci = self.get_object()
        rels = ConfigurationItemRelationship.objects.filter(source_ci=ci, status="active", is_deleted=False)
        return Response(ConfigurationItemRelationshipSerializer(rels, many=True).data)

    @action(detail=True, methods=["get"])
    def dependents(self, request, pk=None):
        ci = self.get_object()
        rels = ConfigurationItemRelationship.objects.filter(target_ci=ci, status="active", is_deleted=False)
        return Response(ConfigurationItemRelationshipSerializer(rels, many=True).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        ci = self.get_object()
        qs = ConfigurationItemHistory.objects.filter(configuration_item=ci).order_by("-created_at")[:100]
        return Response(ConfigurationItemHistorySerializer(qs, many=True).data)

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        ci = self.get_object()
        from .models import ConfigurationItemTicketLink
        links = ConfigurationItemTicketLink.objects.filter(configuration_item=ci, is_deleted=False)
        return Response(ConfigurationItemTicketLinkSerializer(links, many=True).data)

    @action(detail=True, methods=["get"])
    def changes(self, request, pk=None):
        ci = self.get_object()
        from .models import ConfigurationItemChangeLink
        links = ConfigurationItemChangeLink.objects.filter(configuration_item=ci, is_deleted=False)
        return Response(ConfigurationItemChangeLinkSerializer(links, many=True).data)

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        ci = self.get_object()
        depth = int(request.query_params.get("depth", 5))
        depth = min(depth, 5)
        downstream = set()
        visited = set()
        stack = [(ci.id, 0)]
        while stack:
            cid, d = stack.pop()
            if cid in visited or d > depth:
                continue
            visited.add(cid)
            if cid != ci.id:
                downstream.add(cid)
            if d < depth:
                for rel in ConfigurationItemRelationship.objects.filter(source_ci_id=cid, status="active", is_deleted=False).values_list("target_ci_id", flat=True):
                    if rel not in visited:
                        stack.append((rel, d+1))
        affected = ConfigurationItem.objects.filter(id__in=downstream, is_deleted=False)
        return Response({"affected_ci_ids": sorted(downstream), "affected_count": affected.count(), "max_depth": depth})

class ConfigurationItemRelationshipViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationItemRelationship.objects.all()
    serializer_class = ConfigurationItemRelationshipSerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        qs = ConfigurationItemRelationship.objects.filter(is_deleted=False).select_related("source_ci","target_ci")
        for p,f in [("source_ci","source_ci"),("target_ci","target_ci"),("relationship_type","relationship_type"),("status","status")]:
            v = self.request.query_params.get(p)
            if v:
                qs = qs.filter(**{f: v})
        return qs.order_by("-created_at")
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class ConfigurationItemHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConfigurationItemHistory.objects.all()
    serializer_class = ConfigurationItemHistorySerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        qs = ConfigurationItemHistory.objects.all().select_related("actor","configuration_item","relationship")
        ci = self.request.query_params.get("configuration_item")
        if ci:
            qs = qs.filter(configuration_item_id=ci)
        return qs.order_by("-created_at")[:200]

class ConfigurationBaselineViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationBaseline.objects.all()
    serializer_class = ConfigurationBaselineSerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        return ConfigurationBaseline.objects.filter(is_deleted=False).order_by("-created_at")
    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        import json, hashlib
        snapshot = {}
        for ci in obj.configuration_items.all():
            snapshot[str(ci.id)] = {"name": ci.name, "status": ci.status, "criticality": ci.criticality, "version": ci.version, "attributes": ci.attributes}
        obj.snapshot = snapshot
        obj.checksum = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        obj.save(update_fields=["snapshot","checksum","updated_at"])

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        b = self.get_object()
        if not (is_system_admin(request.user) or is_it_manager(request.user)):
            return Response({"detail":"Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if b.created_by_id == request.user.id:
            return Response({"detail":"Cannot approve own baseline."}, status=status.HTTP_403_FORBIDDEN)
        b.status = "approved"
        b.approved_by = request.user
        b.approved_at = timezone.now()
        b.save(update_fields=["status","approved_by","approved_at","updated_at"])
        return Response(ConfigurationBaselineSerializer(b).data)

class ConfigurationDriftFindingViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationDriftFinding.objects.all()
    serializer_class = ConfigurationDriftFindingSerializer
    permission_classes = [CMDBPermission]
    def get_queryset(self):
        qs = ConfigurationDriftFinding.objects.filter(is_deleted=False).select_related("configuration_item")
        for p,f in [("status","status"),("severity","severity"),("configuration_item","configuration_item")]:
            v = self.request.query_params.get(p)
            if v:
                qs = qs.filter(**{f: v})
        return qs.order_by("-detected_at")

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        f = self.get_object()
        f.status = "acknowledged"
        f.acknowledged_by = request.user
        f.acknowledged_at = timezone.now()
        f.save(update_fields=["status","acknowledged_by","acknowledged_at","updated_at"])
        return Response(ConfigurationDriftFindingSerializer(f).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        f = self.get_object()
        note = request.data.get("resolution_note","")
        if not note:
            return Response({"detail":"resolution_note required."}, status=status.HTTP_400_BAD_REQUEST)
        f.status = "resolved"
        f.resolved_by = request.user
        f.resolved_at = timezone.now()
        f.resolution_note = note
        f.save(update_fields=["status","resolved_by","resolved_at","resolution_note","updated_at"])
        return Response(ConfigurationDriftFindingSerializer(f).data)

class CMDBServiceProfileViewSet(viewsets.ModelViewSet):
    queryset = CMDBServiceProfile.objects.all()
    serializer_class = CMDBServiceProfileSerializer
    permission_classes = [CMDBPermission]

class ServiceConfigurationItemLinkViewSet(viewsets.ModelViewSet):
    queryset = ServiceConfigurationItemLink.objects.all()
    serializer_class = ServiceConfigurationItemLinkSerializer
    permission_classes = [CMDBPermission]
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class ConfigurationItemTicketLinkViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationItemTicketLink.objects.all()
    serializer_class = ConfigurationItemTicketLinkSerializer
    permission_classes = [CMDBPermission]
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class ConfigurationItemChangeLinkViewSet(viewsets.ModelViewSet):
    queryset = ConfigurationItemChangeLink.objects.all()
    serializer_class = ConfigurationItemChangeLinkSerializer
    permission_classes = [CMDBPermission]
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

from rest_framework.views import APIView

class DashboardView(APIView):
    permission_classes = [CMDBPermission]
    def get(self, request):
        total = ConfigurationItem.objects.filter(is_deleted=False).count()
        active = ConfigurationItem.objects.filter(is_deleted=False, status="active").count()
        critical = ConfigurationItem.objects.filter(is_deleted=False, criticality="critical").count()
        unverified = ConfigurationItem.objects.filter(is_deleted=False, last_verified_at__isnull=True).count()
        open_drift = ConfigurationDriftFinding.objects.filter(is_deleted=False, status="open").count()
        return Response({"total_cis": total, "active_cis": active, "critical_cis": critical, "unverified_cis": unverified, "open_drift_findings": open_drift})

class ReportsView(APIView):
    permission_classes = [CMDBPermission]
    def get(self, request):
        kind = request.query_params.get("kind","coverage")
        if kind == "orphans":
            rows = ConfigurationItem.objects.filter(is_deleted=False, outgoing_relationships__isnull=True, incoming_relationships__isnull=True).values("id","ci_number","name")[:100]
            return Response({"kind": kind, "rows": list(rows)})
        if kind == "unverified":
            rows = ConfigurationItem.objects.filter(is_deleted=False, last_verified_at__isnull=True).values("id","ci_number","name")[:100]
            return Response({"kind": kind, "rows": list(rows)})
        return Response({"kind": kind, "rows": []})
