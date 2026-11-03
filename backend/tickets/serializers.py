from rest_framework import serializers

from tickets.models import (
    AutomationRule, Ticket, TicketApproval, TicketAttachment,
    TicketCategory, TicketHistory, TicketKbArticle, TicketNote, TicketSLA,
    WorkflowExecution,
)


class TicketCategorySerializer(serializers.ModelSerializer):
    ticket_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TicketCategory
        fields = ["id", "name", "description", "is_active",
                  "ticket_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class TicketSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    requester_email = serializers.CharField(source="requester.email", read_only=True)
    assignee_email = serializers.CharField(source="assignee.email", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True
    )
    sla_due_at = serializers.DateTimeField(read_only=True)
    sla_breached = serializers.BooleanField(read_only=True)
    is_overdue = serializers.SerializerMethodField(read_only=True)

    def get_is_overdue(self, obj):
        return obj.is_overdue

    class Meta:
        model = Ticket
        fields = ["id", "title", "description", "category", "category_name",
                  "priority", "status", "requester", "requester_email",
                  "assignee", "assignee_email", "department",
                  "department_name", "on_behalf_reason", "asset",
                  "resolution_notes", "resolved_at", "closed_at",
                  "sla_due_at", "sla_breached", "is_overdue",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "requester", "resolved_at", "closed_at",
                            "sla_due_at", "sla_breached", "is_overdue",
                            "created_at", "updated_at"]

    def validate(self, attrs):
        # Backend validates category ID exists + is active (unless staff
        # explicitly uses an inactive one — blocked here for consistency).
        category = attrs.get("category")
        if category and not category.is_active:
            raise serializers.ValidationError(
                {"category": "Selected category is deactivated."}
            )
        return attrs

    def validate_assignee(self, user):
        # Eligible assignees are existing, non-deleted, active users.
        # Applies to creation and single updates (field-level, so it runs
        # before anything is saved). None (unassign/omitted) stays valid.
        # Unknown or soft-deleted PKs never reach here: the FK field
        # itself rejects them against the soft-delete-filtered manager.
        if user is not None and not user.is_active:
            raise serializers.ValidationError(
                "Selected user is inactive and cannot be assigned tickets."
            )
        return user


class TicketSLASerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketSLA
        fields = ["id", "priority", "target_resolution_hours", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class TicketNoteSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(source="author.email", read_only=True)

    class Meta:
        model = TicketNote
        fields = ["id", "ticket", "author", "author_email", "body",
                  "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TicketHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True)

    class Meta:
        model = TicketHistory
        fields = ["id", "ticket", "actor", "actor_email", "action",
                  "timestamp", "old_values", "new_values", "note"]
        read_only_fields = fields


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = ["id", "ticket", "file", "original_filename",
                  "uploaded_by", "created_at"]
        read_only_fields = ["id", "uploaded_by", "created_at"]

    def validate_file(self, f):
        return validate_attachment_file(f)


def validate_attachment_file(f):
    """Shared upload policy for ticket AND asset attachments.

    Single implementation: extension whitelist, size cap, executable /
    script blocking. Raises serializers.ValidationError on violation.
    """
    from django.conf import settings
    import os

    ext = os.path.splitext(getattr(f, "name", "") or "")[1].lower().lstrip(".")
    allowed = [e.lower() for e in
               getattr(settings, "ATTACHMENT_ALLOWED_EXTENSIONS", [])]
    if ext not in allowed:
        raise serializers.ValidationError(
            f"Extension '.{ext}' not allowed. Allowed: {allowed}")
    max_bytes = (getattr(settings, "ATTACHMENT_MAX_SIZE_MB", 10)
                 * 1024 * 1024)
    if f.size and f.size > max_bytes:
        raise serializers.ValidationError(
            f"File too large ({f.size} bytes). "
            f"Limit: {max_bytes:.0f} bytes.")
    ctype = getattr(f, "content_type", "") or ""
    # Block executables / scripts regardless of extension claim.
    if ctype.startswith(("application/x-ms", "application/x-sh",
                          "application/x-executable")) or \
            ext in ("exe", "bat", "cmd", "sh", "ps1", "msi"):
        raise serializers.ValidationError("Executable files are blocked.")
    return f


class TicketKbArticleSerializer(serializers.ModelSerializer):
    """Links KB articles to tickets (staff curates, employee votes helpful)."""

    article_title = serializers.CharField(source="article.title",
                                          read_only=True)
    article_slug = serializers.CharField(source="article.slug",
                                         read_only=True)
    article_status = serializers.CharField(source="article.status",
                                           read_only=True)
    linked_by_email = serializers.CharField(
        source="linked_by.email", read_only=True)

    class Meta:
        model = TicketKbArticle
        fields = ["id", "ticket", "article", "article_title", "article_slug",
                  "article_status", "helpful", "linked_by", "linked_by_email",
                  "linked_at"]
        read_only_fields = ["id", "linked_by", "linked_at",
                            "article_title", "article_slug",
                            "article_status", "linked_by_email"]

    def validate(self, attrs):
        user = self.context["request"].user
        ticket = attrs.get("ticket") or getattr(self.instance, "ticket", None)
        article = attrs.get("article") or getattr(
            self.instance, "article", None)
        if self.instance is None and ticket and article:
            if TicketKbArticle.objects.filter(
                    ticket=ticket, article=article, is_deleted=False).exists():
                raise serializers.ValidationError(
                    {"article": "This KB article is already linked to the "
                                "ticket."})
        return attrs


CONDITION_FIELD_CHOICES = [
    "status", "priority", "category", "department", "assignee",
    "requester", "title"]
CONDITION_OPERATOR_CHOICES = ["equals", "not_equals", "in", "contains"]
ACTION_TYPE_CHOICES = ["add_note", "set_priority", "assign", "notify"]
INTEGER_CONDITION_FIELDS = {"category", "department", "assignee", "requester"}


class AutomationRuleSerializer(serializers.ModelSerializer):
    """Create/edit automation rules with deep condition/action validation.

    Conditions: [{"field": <known field>, "operator": <known operator>,
    "value": <matching shape>}]. Actions: [{"type": <known type>,
    "params": {...}}]. Unsupported fields/operators/types are rejected
    with per-item errors so the edit form can point at the row.
    """

    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True)
    trigger_display = serializers.CharField(
        source="get_trigger_display", read_only=True)

    class Meta:
        model = AutomationRule
        fields = ["id", "name", "description", "trigger", "trigger_display",
                  "conditions", "actions", "is_active", "created_by",
                  "created_by_email", "created_at", "updated_at"]
        read_only_fields = ["id", "trigger_display", "created_by",
                            "created_by_email", "created_at", "updated_at"]

    def validate_conditions(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "Conditions must be a list.")
        cleaned = []
        errors = []
        for idx, cond in enumerate(value):
            n = idx + 1
            if not isinstance(cond, dict):
                errors.append(f"Condition {n} must be an object.")
                continue
            field = cond.get("field")
            operator = cond.get("operator")
            val = cond.get("value")
            if field not in CONDITION_FIELD_CHOICES:
                if field:
                    errors.append(
                        f"Condition {n}: field '{field}' is not supported "
                        f"(use: {', '.join(CONDITION_FIELD_CHOICES)}).")
                else:
                    errors.append(f"Condition {n}: field is required.")
                continue
            if operator not in CONDITION_OPERATOR_CHOICES:
                if operator:
                    errors.append(
                        f"Condition {n}: operator '{operator}' is not "
                        f"supported (use: "
                        f"{', '.join(CONDITION_OPERATOR_CHOICES)}).")
                else:
                    errors.append(f"Condition {n}: operator is required.")
                continue
            if field == "title":
                if not isinstance(val, str) or not val.strip():
                    errors.append(
                        f"Condition {n}: value must be non-empty text "
                        "for title.")
                    continue
                cleaned.append({"field": field, "operator": operator,
                                "value": val.strip()})
                continue
            if field in INTEGER_CONDITION_FIELDS:
                if operator == "in":
                    if not isinstance(val, list) or len(val) == 0:
                        errors.append(
                            f"Condition {n}: 'in' needs a non-empty list "
                            "of ids.")
                        continue
                    ids = []
                    bad = False
                    for v in val:
                        try:
                            ids.append(int(v))
                        except (TypeError, ValueError):
                            bad = True
                            break
                    if bad:
                        errors.append(
                            f"Condition {n}: 'in' values must be ids.")
                        continue
                    cleaned.append({"field": field, "operator": operator,
                                    "value": ids})
                    continue
                try:
                    iid = int(val)
                except (TypeError, ValueError):
                    errors.append(f"Condition {n}: value must be an id.")
                    continue
                cleaned.append({"field": field, "operator": operator,
                                "value": iid})
                continue
            # status / priority
            choices = {c[0] for c in (
                Ticket.STATUS_CHOICES if field == "status"
                else Ticket.PRIORITY_CHOICES)}
            targets = val if operator == "in" and isinstance(val, list) \
                else [val]
            bad = [v for v in targets if v not in choices]
            if bad:
                errors.append(
                    f"Condition {n}: invalid {field} value(s): "
                    f"{', '.join(map(str, bad))}.")
                continue
            cleaned.append({"field": field, "operator": operator,
                            "value": val})
        if errors:
            raise serializers.ValidationError({"items": errors})
        return cleaned

    def validate_actions(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Actions must be a list.")
        cleaned = []
        errors = []
        for idx, act in enumerate(value):
            n = idx + 1
            if not isinstance(act, dict):
                errors.append(f"Action {n} must be an object.")
                continue
            atype = act.get("type")
            params = act.get("params") or {}
            if atype not in ACTION_TYPE_CHOICES:
                if atype:
                    errors.append(
                        f"Action {n}: type '{atype}' is not supported "
                        f"(use: {', '.join(ACTION_TYPE_CHOICES)}).")
                else:
                    errors.append(f"Action {n}: type is required.")
                continue
            if not isinstance(params, dict):
                errors.append(f"Action {n}: params must be an object.")
                continue
            if atype == "add_note":
                body = params.get("body")
                if not isinstance(body, str) or not body.strip():
                    errors.append(f"Action {n}: note body is required.")
                    continue
                cleaned.append({
                    "type": "add_note",
                    "params": {"body": body.strip(),
                               "is_internal": bool(
                                   params.get("is_internal", True))}})
            elif atype == "set_priority":
                pri = params.get("priority")
                if pri not in {c[0] for c in Ticket.PRIORITY_CHOICES}:
                    errors.append(f"Action {n}: invalid priority '{pri}'.")
                    continue
                cleaned.append({"type": "set_priority",
                                "params": {"priority": pri}})
            elif atype == "assign":
                uid = params.get("user_id")
                try:
                    uid = int(uid)
                except (TypeError, ValueError):
                    errors.append(f"Action {n}: user_id must be an id.")
                    continue
                from accounts.models import User
                if not User.objects.filter(pk=uid, is_active=True).exists():
                    errors.append(
                        f"Action {n}: user #{uid} not found or inactive.")
                    continue
                cleaned.append({"type": "assign", "params": {"user_id": uid}})
            elif atype == "notify":
                to = params.get("to")
                if to not in ("assignee", "requester"):
                    errors.append(
                        f"Action {n}: 'to' must be assignee or requester.")
                    continue
                message = params.get("message")
                if not isinstance(message, str) or not message.strip():
                    errors.append(f"Action {n}: message is required.")
                    continue
                cleaned.append({
                    "type": "notify",
                    "params": {"to": to, "message": message.strip()}})
        if errors:
            raise serializers.ValidationError({"items": errors})
        return cleaned

    def validate_name(self, value):
        name = (value or "").strip()
        if len(name) < 3:
            raise serializers.ValidationError(
                "Name must be at least 3 characters.")
        qs = AutomationRule.objects.filter(name__iexact=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A rule with this name already exists.")
        return name

    def validate_trigger(self, value):
        allowed = {c[0] for c in AutomationRule.TRIGGER_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported trigger '{value}'.")
        return value


class TicketApprovalSerializer(serializers.ModelSerializer):
    """Approval requests: created via the API, decided via actions only."""

    ticket_title = serializers.SerializerMethodField(read_only=True)
    requested_by_email = serializers.CharField(
        source="requested_by.email", read_only=True)
    approver_email = serializers.CharField(
        source="approver.email", read_only=True)
    operation_display = serializers.CharField(
        source="get_operation_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True)

    class Meta:
        model = TicketApproval
        fields = ["id", "ticket", "ticket_title", "requested_by",
                  "requested_by_email", "operation", "operation_display",
                  "context", "status", "status_display", "approver",
                  "approver_email", "decision_comment", "decided_at",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "ticket_title", "requested_by",
                            "requested_by_email", "status", "status_display",
                            "approver", "approver_email",
                            "decision_comment", "decided_at",
                            "created_at", "updated_at"]

    def get_ticket_title(self, obj):
        return obj.ticket.title if obj.ticket_id else ""

    def validate_ticket(self, ticket):
        if ticket is None:
            raise serializers.ValidationError("Ticket is required.")
        from tickets.views import _ticket_visible_qs
        visible = _ticket_visible_qs(self.context["request"].user)
        if not visible.filter(pk=ticket.pk).exists():
            raise serializers.ValidationError(
                "You do not have access to this ticket.")
        return ticket

    def validate_context(self, context):
        operation = (
            self.initial_data.get("operation")
            or getattr(self.instance, "operation", None))
        if not isinstance(context, dict):
            raise serializers.ValidationError(
                "Context must be an object.")
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
            if not User.objects.filter(
                    pk=uid, is_active=True).exists():
                raise serializers.ValidationError(
                    {"user_id": "User not found or inactive."})
            return {"user_id": uid}
        raise serializers.ValidationError(
            "Unknown or missing operation for context validation.")

    def validate_operation(self, value):
        allowed = {c[0] for c in TicketApproval.OPERATION_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported operation '{value}'.")
        return value


class WorkflowExecutionSerializer(serializers.ModelSerializer):
    """Read-only execution history rows."""

    rule_name = serializers.SerializerMethodField(read_only=True)
    ticket_title = serializers.SerializerMethodField(read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True)

    class Meta:
        model = WorkflowExecution
        fields = ["id", "rule", "rule_name", "ticket", "ticket_title",
                  "trigger", "status", "status_display",
                  "matched_conditions", "results", "error", "created_at"]
        read_only_fields = fields

    def get_rule_name(self, obj):
        return obj.rule.name if obj.rule_id else None

    def get_ticket_title(self, obj):
        return obj.ticket.title if obj.ticket_id else None
