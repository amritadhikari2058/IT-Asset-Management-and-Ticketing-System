from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import AutomationRule, RuleExecution, ApprovalRequest
from .serializers import AutomationRuleSerializer, RuleExecutionSerializer, ApprovalRequestSerializer


class AutomationRuleViewSet(viewsets.ModelViewSet):
    queryset = AutomationRule.objects.all()
    serializer_class = AutomationRuleSerializer


class RuleExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RuleExecution.objects.all()
    serializer_class = RuleExecutionSerializer


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    queryset = ApprovalRequest.objects.all()
    serializer_class = ApprovalRequestSerializer

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        obj = self.get_object()
        if obj.status != "pending":
            return Response({"detail": "Already decided"}, status=400)
        if request.user == obj.requested_by:
            return Response({"detail": "Self-approval not allowed"}, status=403)
        obj.status = "approved"
        obj.decided_by = request.user
        obj.decided_at = timezone.now()
        obj.decision_comment = request.data.get("comment", "")
        obj.save()
        return Response(ApprovalRequestSerializer(obj).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        obj = self.get_object()
        if obj.status != "pending":
            return Response({"detail": "Already decided"}, status=400)
        obj.status = "rejected"
        obj.decided_by = request.user
        obj.decided_at = timezone.now()
        obj.decision_comment = request.data.get("comment", "")
        obj.save()
        return Response(ApprovalRequestSerializer(obj).data)

