from rest_framework import serializers
from .models import AutomationRule, RuleExecution, ApprovalRequest

class AutomationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationRule
        fields = "__all__"

class RuleExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleExecution
        fields = "__all__"

class ApprovalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRequest
        fields = "__all__"
