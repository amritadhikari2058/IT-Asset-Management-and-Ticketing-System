"""Workflow serializers with deep validation (Phase 19)."""
from rest_framework import serializers

from tickets.models import Ticket
from .models import AutomationRule, ApprovalRequest, RuleExecution


class AutomationRuleSerializer(serializers.ModelSerializer):
    """Rule create/edit. Validates every trigger/condition/action field the
    engine supports; unsupported keys/types are rejected with field errors
    so the edit form can surface them."""

    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True)
    updated_by_email = serializers.CharField(
        source="updated_by.email", read_only=True)
    trigger_display = serializers.CharField(
        source="get_trigger_display", read_only=True)

    class Meta:
        model = AutomationRule
        fields = ["id", "name", "description", "is_enabled", "trigger",
                  "trigger_display", "conditions", "actions", "created_by",
                  "created_by_email", "updated_by", "updated_by_email",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "trigger_display", "created_by",
                            "created_by_email", "updated_by",
                            "updated_by_email", "created_at", "updated_at"]

    CONDITION_KEYS = ("category_id", "department_id", "priority", "status")
    ACTION_TYPES = ("assign", "priority", "status", "note", "notify")

    def validate_trigger(self, value):
        allowed = {c[0] for c in AutomationRule.TRIGGER_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported trigger '{value}'.")
        return value

    def validate_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Name is required.")
        name = str(value).strip()
        qs = AutomationRule.objects.filter(name__iexact=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A rule with this name already exists.")
        return name

    def validate_conditions(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                {"non_field": "Conditions must be an object with keys: "
                              + ", ".join(self.CONDITION_KEYS) + "."})
        errors = {}
        cleaned = {}
        for key, val in value.items():
            if key not in self.CONDITION_KEYS:
                errors[key] = (
                    f"Unsupported condition key (use: "
                    f"{', '.join(self.CONDITION_KEYS)}).")
                continue
            if key in ("category_id", "department_id"):
                try:
                    cleaned[key] = int(val)
                except (TypeError, ValueError):
                    errors[key] = "Value must be an id."
                continue
            choices = {c[0] for c in (
                Ticket.PRIORITY_CHOICES if key == "priority"
                else Ticket.STATUS_CHOICES)}
            if val not in choices:
                errors[key] = (
                    f"Value must be one of: {', '.join(sorted(choices))}.")
                continue
            cleaned[key] = val
        if errors:
            raise serializers.ValidationError(errors)
        return cleaned

    def validate_actions(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(
                {"non_field": "Actions must be a list."})
        errors = {}
        cleaned = []
        for idx, act in enumerate(value):
            n = idx + 1
            if not isinstance(act, dict):
                errors[str(n)] = "Each action must be an object."
                continue
            atype = act.get("type")
            if atype not in self.ACTION_TYPES:
                if atype:
                    errors[str(n)] = (
                        f"Unsupported action type '{atype}' (use: "
                        f"{', '.join(self.ACTION_TYPES)}).")
                else:
                    errors[str(n)] = "Action type is required."
                continue
            if atype == "assign":
                uid = act.get("user_id")
                try:
                    uid = int(uid)
                except (TypeError, ValueError):
                    errors[str(n)] = "user_id must be an id."
                    continue
                from accounts.models import User
                if not User.objects.filter(pk=uid, is_active=True).exists():
                    errors[str(n)] = "User not found or inactive."
                    continue
                cleaned.append({"type": "assign", "user_id": uid})
            elif atype == "priority":
                pri = act.get("value")
                if pri not in {c[0] for c in Ticket.PRIORITY_CHOICES}:
                    errors[str(n)] = (
                        "value must be one of: "
                        + ", ".join(c[0] for c in Ticket.PRIORITY_CHOICES))
                    continue
                cleaned.append({"type": "priority", "value": pri})
            elif atype == "status":
                val = act.get("value")
                if val not in {c[0] for c in Ticket.STATUS_CHOICES}:
                    errors[str(n)] = (
                        "value must be one of: "
                        + ", ".join(c[0] for c in Ticket.STATUS_CHOICES))
                    continue
                cleaned.append({"type": "status", "value": val})
            elif atype == "note":
                text = act.get("text")
                if not isinstance(text, str) or not text.strip():
                    errors[str(n)] = "note text is required."
                    continue
                cleaned.append({"type": "note", "text": text.strip()})
            elif atype == "notify":
                uid = act.get("user_id")
                if uid in (None, ""):
                    cleaned.append({"type": "notify", "user_id": None})
                    continue
                try:
                    uid = int(uid)
                except (TypeError, ValueError):
                    errors[str(n)] = "user_id must be an id."
                    continue
                from accounts.models import User
                if not User.objects.filter(pk=uid, is_active=True).exists():
                    errors[str(n)] = "User not found or inactive."
                    continue
                cleaned.append({"type": "notify", "user_id": uid})
        if errors:
            raise serializers.ValidationError(errors)
        return cleaned


class RuleExecutionSerializer(serializers.ModelSerializer):
    """Read-only execution history rows."""

    rule_name = serializers.SerializerMethodField(read_only=True)
    ticket_title = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RuleExecution
        fields = ["id", "rule", "rule_name", "ticket", "ticket_title",
                  "success", "detail", "created_at"]
        read_only_fields = fields

    def get_rule_name(self, obj):
        return obj.rule.name if obj.rule else None

    def get_ticket_title(self, obj):
        return obj.ticket.title if obj.ticket_id else None


class ApprovalRequestSerializer(serializers.ModelSerializer):
    """Approval requests: created via POST, decided only via the
    approve/reject actions (status/decision fields are read-only)."""

    ticket_title = serializers.SerializerMethodField(read_only=True)
    requested_by_email = serializers.CharField(
        source="requested_by.email", read_only=True)
    approver_email = serializers.CharField(
        source="approver.email", read_only=True)
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True)
    operation_display = serializers.CharField(
        source="get_operation_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = ["id", "ticket", "ticket_title", "requested_by",
                  "requested_by_email", "operation", "operation_display",
                  "context", "reason", "status", "status_display",
                  "approver", "approver_email", "decision_comment",
                  "decided_by", "decided_by_email", "decided_at",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "ticket_title", "requested_by",
                            "requested_by_email", "status", "status_display",
                            "approver", "approver_email",
                            "decision_comment", "decided_by",
                            "decided_by_email", "decided_at",
                            "created_at", "updated_at"]

    def get_ticket_title(self, obj):
        return obj.ticket.title if obj.ticket else ""

    def validate_ticket(self, ticket):
        user = self.context.get("request").user if self.context.get(
            "request") else None
        if user is None:
            return ticket
        from .services import ticket_visible_qs
        if ticket and not ticket_visible_qs(user).filter(pk=ticket.pk).exists():
            raise serializers.ValidationError(
                {"ticket": "You do not have access to this ticket."})
        return ticket

    def validate_operation(self, value):
        allowed = {c[0] for c in ApprovalRequest.OPERATION_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported operation '{value}'.")
        return value

    def validate_context(self, context):
        operation = (
            self.initial_data.get("operation")
            or getattr(self.instance, "operation", "other"))
        if context in (None, ""):
            context = {}
        if not isinstance(context, dict):
            raise serializers.ValidationError("Context must be an object.")
        if operation == "change_priority":
            pri = context.get("priority")
            if pri not in {c[0] for c in Ticket.PRIORITY_CHOICES}:
                raise serializers.ValidationError(
                    {"priority": f"Invalid priority '{pri}'."})
            return {"priority": pri}
        if operation == "change_status":
            val = context.get("status")
            if val not in {c[0] for c in Ticket.STATUS_CHOICES}:
                raise serializers.ValidationError(
                    {"status": f"Invalid status '{val}'."})
            return {"status": val}
        if operation == "reassign":
            uid = context.get("user_id")
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"user_id": "user_id must be an id."})
            from accounts.models import User
            if not User.objects.filter(pk=uid, is_active=True).exists():
                raise serializers.ValidationError(
                    {"user_id": "User not found or inactive."})
            return {"user_id": uid}
        return context
