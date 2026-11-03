from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import AutomationRuleViewSet, RuleExecutionViewSet, ApprovalRequestViewSet

router = DefaultRouter()
router.register(r"automation-rules", AutomationRuleViewSet, basename="automationrule")
router.register(r"rule-executions", RuleExecutionViewSet, basename="ruleexecution")
router.register(r"approval-requests", ApprovalRequestViewSet, basename="approvalrequest")

urlpatterns = [path("", include(router.urls))]
