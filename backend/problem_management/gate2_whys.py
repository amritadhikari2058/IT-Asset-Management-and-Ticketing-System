"""Gate 2 Five Whys and root-cause factor viewsets (service-backed edits)."""
from rest_framework.response import Response

from . import services
from .gate2_common import guarded
from .gate2_serializers import RootCauseFactorSerializer, RootCauseWhySerializer
from .gate2_views import Gate2ModelViewSet
from .models import RootCauseFactor, RootCauseWhy

WHY_METHODS = ["get", "post", "patch", "delete", "head", "options"]


class WhyViewSet(Gate2ModelViewSet):
    model = RootCauseWhy
    serializer_class = RootCauseWhySerializer
    create_service = staticmethod(services.create_root_cause_why)
    parent_field = "analysis"
    http_method_names = WHY_METHODS

    def partial_update(self, request, *args, **kwargs):
        why = self.get_object()
        data = dict(request.data)
        data.pop("expected_record_version", None)
        fields = {key: data[key] for key in ("question_text", "answer") if key in data}
        updated = guarded(services.update_root_cause_why, actor=request.user,
                          why=why, **fields)
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        why = self.get_object()
        guarded(services.delete_root_cause_why, actor=request.user, why=why)
        return Response(status=204)


class FactorViewSet(Gate2ModelViewSet):
    model = RootCauseFactor
    serializer_class = RootCauseFactorSerializer
    create_service = staticmethod(services.create_root_cause_factor)
    parent_field = "analysis"
    http_method_names = WHY_METHODS

    def partial_update(self, request, *args, **kwargs):
        factor = self.get_object()
        data = dict(request.data)
        data.pop("expected_record_version", None)
        fields = {}
        if "category" in data:
            fields["category"] = data["category"]
        if "factor" in data:
            fields["factor_text"] = data["factor"]
        updated = guarded(services.update_root_cause_factor, actor=request.user,
                          factor=factor, **fields)
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        factor = self.get_object()
        guarded(services.delete_root_cause_factor, actor=request.user, factor=factor)
        return Response(status=204)
