"""CMDB serializers with schema validation, secret blocking, hostname
normalization, one-active-link constraints and role-aware field limits.

Concurrency: write payloads may carry `expected_record_version`; a mismatch
raises StaleRecordError (HTTP 409).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import APIException

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
    ServiceConfigurationItemLink,
    normalize_hostname,
    validate_ci_attributes,
    validate_relationship,
    validate_type_schema,
)
from .permissions import (
    SUPPORT_FORBIDDEN_STATUSES,
    SUPPORT_READONLY_FIELDS,
    get_user_role,
)

MAX_HISTORY_IN_DETAIL = 20


class StaleRecordError(APIException):
    status_code = 409
    default_detail = "Record has been modified by someone else."
    default_code = "stale_record"


def _request(serializer):
    return serializer.context.get("request")


def _role(serializer):
    request = _request(serializer)
    if request is None:
        return ""
    return get_user_role(request.user)


class ConfigurationItemTypeSerializer(serializers.ModelSerializer):
    ci_count = serializers.SerializerMethodField()

    class Meta:
        model = ConfigurationItemType
        fields = [
            "id", "name", "code", "description", "category", "icon", "color",
            "schema", "required_attributes", "is_active", "is_system",
            "ci_count", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "is_system", "ci_count", "created_by", "created_at",
            "updated_at",
        ]

    def get_ci_count(self, obj):
        annotated = getattr(obj, "annotated_ci_count", None)
        if annotated is not None:
            return annotated
        return obj.configuration_items.filter(is_deleted=False).count()

    def validate(self, attrs):
        schema = attrs.get("schema", getattr(self.instance, "schema", {})) or {}
        required = attrs.get(
            "required_attributes",
            getattr(self.instance, "required_attributes", []),
        ) or []
        try:
            validate_type_schema(schema, required)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages,
            )
        code = attrs.get("code", getattr(self.instance, "code", ""))
        if code:
            normalized = str(code).strip().upper()
            clash = (
                ConfigurationItemType.objects.filter(code=normalized)
                .exclude(pk=getattr(self.instance, "pk", None))
            )
            if clash.exists():
                raise serializers.ValidationError(
                    {"code": "A CI Type with this code already exists."},
                )
            attrs["code"] = normalized
        return attrs


class ConfigurationItemSerializer(serializers.ModelSerializer):
    ci_type_name = serializers.CharField(source="ci_type.name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default="",
    )
    owner_username = serializers.CharField(
        source="owner.username", read_only=True, default="",
    )
    asset_tag = serializers.CharField(
        source="asset.asset_tag", read_only=True, default="",
    )
    service = serializers.PrimaryKeyRelatedField(
        source="service_catalogue_item", read_only=True,
    )
    service_name = serializers.CharField(
        source="service_catalogue_item.name", read_only=True, default="",
    )
    verification_status = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    expected_record_version = serializers.IntegerField(
        required=False, allow_null=True, write_only=True,
    )

    class Meta:
        model = ConfigurationItem
        fields = [
            "id", "ci_number", "name", "ci_type", "ci_type_name",
            "description", "status", "lifecycle_state", "criticality",
            "environment", "asset", "asset_tag", "software_product",
            "service_catalogue_item", "service", "service_name", "department",
            "department_name", "location", "owner", "owner_username",
            "technical_owner", "support_group", "vendor", "manufacturer",
            "model", "serial_number", "version", "hostname", "ip_address",
            "dns_name", "external_reference", "attributes", "source",
            "source_identifier", "last_discovered_at", "last_verified_at",
            "verified_by", "monitoring_state", "data_classification",
            "contains_personal_data", "validated_system_impact",
            "verification_status", "history", "created_by", "created_at",
            "updated_at", "record_version", "expected_record_version",
        ]
        read_only_fields = [
            "id", "ci_number", "verified_by", "last_verified_at",
            "last_discovered_at", "created_by", "created_at", "updated_at",
            "record_version", "verification_status", "history",
            "ci_type_name", "department_name",
            "owner_username", "asset_tag", "service", "service_name",
        ]

    def get_verification_status(self, obj):
        from .impact import verification_status_for

        return verification_status_for(obj)

    def get_history(self, obj):
        if not self.context.get("include_history"):
            return []
        if not obj or not obj.pk:
            return []
        return ConfigurationItemHistorySerializer(
            obj.history.all()[:MAX_HISTORY_IN_DETAIL], many=True,
        ).data

    # -- validation ------------------------------------------------------

    def _check_expected_version(self, attrs):
        expected = attrs.pop("expected_record_version", None)
        if expected is None or self.instance is None:
            return
        if int(expected) != self.instance.record_version:
            raise StaleRecordError(
                f"expected record_version {expected}, "
                f"found {self.instance.record_version}"
            )

    def _enforce_support_limits(self, attrs, creating):
        role = _role(self)
        if role != "it_support":
            return
        if creating:
            source = attrs.get("source", "manual")
            if source != "manual":
                raise serializers.ValidationError(
                    {"source": "IT Support may only create manual CIs."},
                )
            attrs["source"] = "manual"
            attrs.pop("source_identifier", None)
            status = attrs.get("status", "planned")
            if status in SUPPORT_FORBIDDEN_STATUSES:
                raise serializers.ValidationError(
                    {"status": "IT Support may not create retired/disposed CIs."},
                )
        else:
            forbidden = set(attrs) & SUPPORT_READONLY_FIELDS
            if forbidden:
                raise serializers.ValidationError(
                    {f: "IT Support may not modify this field."
                     for f in sorted(forbidden)},
                )
            for field in ("status", "lifecycle_state"):
                if field in attrs and attrs[field] in SUPPORT_FORBIDDEN_STATUSES:
                    raise serializers.ValidationError(
                        {field: "IT Support may not retire configuration items."},
                    )

    def _validate_unique_links(self, attrs):
        instance = self.instance
        asset = attrs.get("asset", getattr(instance, "asset", None)
                          if instance else None)
        if asset is not None:
            clash = ConfigurationItem.objects.filter(
                asset=asset,
            ).exclude(
                status__in=("retired", "disposed"),
            ).exclude(pk=getattr(instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError(
                    {"asset": "An active CI already links this asset."},
                )
        product = attrs.get(
            "software_product",
            getattr(instance, "software_product", None) if instance else None,
        )
        if product is not None:
            clash = ConfigurationItem.objects.filter(
                software_product=product,
            ).exclude(
                status__in=("retired", "disposed"),
            ).exclude(pk=getattr(instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError(
                    {"software_product":
                     "An active CI already links this software product."},
                )

    def validate(self, attrs):
        creating = self.instance is None
        self._check_expected_version(attrs)
        self._enforce_support_limits(attrs, creating)
        if not creating:
            for field in ("status", "lifecycle_state"):
                if field in attrs and attrs[field] in ("retired", "disposed"):
                    raise serializers.ValidationError({
                        field: "Use the retire action to retire configuration items.",
                    })
        self._validate_unique_links(attrs)

        ci_type = attrs.get(
            "ci_type", getattr(self.instance, "ci_type", None),
        )
        if "hostname" in attrs:
            attrs["hostname"] = normalize_hostname(attrs["hostname"])
        if "dns_name" in attrs:
            attrs["dns_name"] = normalize_hostname(attrs["dns_name"])
        if "attributes" in attrs:
            try:
                validate_ci_attributes(attrs["attributes"], ci_type)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    {"attributes": exc.messages},
                )
        elif creating and ci_type is not None:
            try:
                validate_ci_attributes({}, ci_type)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    {"attributes": exc.messages},
                )
        elif not creating and (
            "ci_type" in attrs or "attributes" in attrs
        ):
            attributes = attrs.get(
                "attributes", getattr(self.instance, "attributes", {}),
            )
            try:
                validate_ci_attributes(attributes or {}, ci_type)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    {"attributes": exc.messages},
                )
        if "external_reference" in attrs and len(
            attrs["external_reference"] or "",
        ) > 200:
            raise serializers.ValidationError(
                {"external_reference": "max length 200"},
            )
        return attrs


class ConfigurationItemRelationshipSerializer(serializers.ModelSerializer):
    source_ci_number = serializers.CharField(
        source="source_ci.ci_number", read_only=True,
    )
    target_ci_number = serializers.CharField(
        source="target_ci.ci_number", read_only=True,
    )
    inverse_type = serializers.SerializerMethodField()

    class Meta:
        model = ConfigurationItemRelationship
        fields = [
            "id", "source_ci", "source_ci_number", "target_ci",
            "target_ci_number", "relationship_type", "inverse_type",
            "status", "description", "valid_from", "valid_to", "discovered",
            "confidence", "source", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "inverse_type", "created_by", "created_at", "updated_at",
        ]

    def get_inverse_type(self, obj):
        from .models import INVERSE_REL_TYPES

        return INVERSE_REL_TYPES.get(obj.relationship_type, "")

    def validate(self, attrs):
        role = _role(self)
        creating = self.instance is None
        source_ci = attrs.get(
            "source_ci", getattr(self.instance, "source_ci", None),
        )
        target_ci = attrs.get(
            "target_ci", getattr(self.instance, "target_ci", None),
        )
        rtype = attrs.get(
            "relationship_type",
            getattr(self.instance, "relationship_type", None),
        )
        status = attrs.get(
            "status", getattr(self.instance, "status", "active"),
        )

        if creating:
            if role == "it_support":
                if "status" in attrs and attrs["status"] != "proposed":
                    raise serializers.ValidationError(
                        {"status":
                         "IT Support may only create proposed relationships."},
                    )
                attrs["status"] = "proposed"
                status = "proposed"
            if source_ci and target_ci and rtype:
                try:
                    validate_relationship(
                        source_ci, target_ci, rtype, status=status,
                    )
                except DjangoValidationError as exc:
                    raise serializers.ValidationError(exc.messages)
        else:
            if role == "it_support":
                editable = set(attrs) - {
                    "description", "confidence", "valid_from", "valid_to",
                }
                if editable:
                    raise serializers.ValidationError(
                        {f: "IT Support may only edit notes on proposed "
                            "relationships."
                         for f in sorted(editable)},
                    )
            # elevated re-validation when structural fields change
            structural_changed = any(
                key in attrs
                for key in ("source_ci", "target_ci", "relationship_type",
                            "status")
            )
            if structural_changed and source_ci and target_ci and rtype:
                if attrs.get("status", "active") == "active":
                    try:
                        validate_relationship(
                            source_ci, target_ci, rtype, status="active",
                        )
                    except DjangoValidationError as exc:
                        raise serializers.ValidationError(exc.messages)
        return attrs


class ConfigurationItemHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(
        source="actor.email", read_only=True, default="",
    )
    actor_username = serializers.CharField(
        source="actor.username", read_only=True, default="",
    )

    class Meta:
        model = ConfigurationItemHistory
        fields = [
            "id", "configuration_item", "relationship", "actor",
            "actor_email", "actor_username", "event_type", "previous_status",
            "new_status", "changed_fields", "detail", "source", "created_at",
        ]
        read_only_fields = fields


class ConfigurationBaselineSerializer(serializers.ModelSerializer):
    ci_count = serializers.SerializerMethodField()

    class Meta:
        model = ConfigurationBaseline
        fields = [
            "id", "name", "code", "description", "scope_type", "service",
            "configuration_items", "ci_count", "status", "baseline_date",
            "effective_from", "effective_to", "version", "created_by",
            "approved_by", "approved_at", "snapshot", "checksum",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "code", "ci_count", "status", "version", "created_by",
            "approved_by", "approved_at", "snapshot", "checksum",
            "created_at", "updated_at",
        ]

    def get_ci_count(self, obj):
        if not obj.pk:
            return 0
        return obj.configuration_items.count()

    def validate_configuration_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "Select at least one configuration item.",
            )
        if len(value) > 200:
            raise serializers.ValidationError(
                "Baseline scope may not exceed 200 CIs.",
            )
        return value

    def create(self, validated_data):
        cis = validated_data.pop("configuration_items", [])
        from .baselines import create_baseline

        return create_baseline(
            name=validated_data["name"],
            scope_type=validated_data.get("scope_type", "single_ci"),
            cis=cis,
            actor=validated_data.get("created_by"),
            service=validated_data.get("service"),
            description=validated_data.get("description", ""),
            effective_from=validated_data.get("effective_from"),
            effective_to=validated_data.get("effective_to"),
        )

    def update(self, instance, validated_data):
        cis = validated_data.pop("configuration_items", None)
        validated_data.pop("code", None)
        validated_data.pop("status", None)
        if instance.status not in ("draft", "pending_approval"):
            raise serializers.ValidationError(
                "Only draft/pending baselines can be edited.",
            )
        if cis is not None and instance.status != "draft":
            raise serializers.ValidationError(
                {"configuration_items":
                 "Baseline scope can only be changed while the baseline is a draft."},
            )
        instance = super().update(instance, validated_data)
        if cis is not None:
            instance.configuration_items.set(cis)
            from .baselines import refresh_snapshot
            refresh_snapshot(instance)
            instance.refresh_from_db()
        return instance


class ConfigurationDriftFindingSerializer(serializers.ModelSerializer):
    ci_number = serializers.CharField(
        source="configuration_item.ci_number", read_only=True,
    )
    ci_name = serializers.CharField(
        source="configuration_item.name", read_only=True,
    )
    baseline_code = serializers.CharField(
        source="baseline.code", read_only=True, default="",
    )

    class Meta:
        model = ConfigurationDriftFinding
        fields = [
            "id", "configuration_item", "ci_number", "ci_name", "baseline",
            "baseline_code", "finding_type", "severity", "status",
            "field_name", "expected_value", "actual_value", "detected_at",
            "acknowledged_at", "acknowledged_by", "resolved_at",
            "resolved_by", "resolution_note", "fingerprint", "source",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "configuration_item", "ci_number", "ci_name", "baseline",
            "baseline_code", "finding_type", "severity", "field_name",
            "expected_value", "actual_value", "detected_at",
            "acknowledged_at", "acknowledged_by", "resolved_at",
            "resolved_by", "resolution_note", "fingerprint", "source",
            "created_at", "updated_at",
        ]


class CMDBServiceProfileSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(
        source="service.name", read_only=True, default="",
    )

    class Meta:
        model = CMDBServiceProfile
        fields = [
            "id", "service", "service_name", "service_tier", "service_owner",
            "technical_owner", "business_owner", "support_group",
            "criticality", "availability_target", "rto_minutes",
            "rpo_minutes", "business_hours", "maintenance_window",
            "is_customer_facing", "is_regulated", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "service_name", "created_at", "updated_at"]


class ServiceConfigurationItemLinkSerializer(serializers.ModelSerializer):
    ci_number = serializers.CharField(
        source="configuration_item.ci_number", read_only=True,
    )
    ci_name = serializers.CharField(
        source="configuration_item.name", read_only=True,
    )
    service_name = serializers.CharField(
        source="service.name", read_only=True,
    )

    class Meta:
        model = ServiceConfigurationItemLink
        fields = [
            "id", "service", "service_name", "configuration_item",
            "ci_number", "ci_name", "role", "criticality",
            "redundancy_group", "is_required", "notes", "created_by",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "service_name", "ci_number", "ci_name", "created_by",
            "created_at", "updated_at",
        ]


class ConfigurationItemTicketLinkSerializer(serializers.ModelSerializer):
    ticket_title = serializers.CharField(
        source="ticket.title", read_only=True, default="",
    )
    ci_number = serializers.CharField(
        source="configuration_item.ci_number", read_only=True,
    )

    class Meta:
        model = ConfigurationItemTicketLink
        fields = [
            "id", "configuration_item", "ci_number", "ticket", "ticket_title",
            "relation_type", "created_by", "created_at",
        ]
        read_only_fields = [
            "id", "ci_number", "ticket_title", "created_by", "created_at",
        ]


class ConfigurationItemChangeLinkSerializer(serializers.ModelSerializer):
    change_number = serializers.CharField(
        source="change.change_number", read_only=True, default="",
    )
    ci_number = serializers.CharField(
        source="configuration_item.ci_number", read_only=True,
    )

    class Meta:
        model = ConfigurationItemChangeLink
        fields = [
            "id", "configuration_item", "ci_number", "change",
            "change_number", "impact_type", "change_role", "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id", "ci_number", "change_number", "created_by", "created_at",
        ]


class VerifyCISerializer(serializers.Serializer):
    verification_note = serializers.CharField(
        required=False, allow_blank=True, default="",
    )
    expected_record_version = serializers.IntegerField(
        required=False, allow_null=True, default=None,
    )


class RetireCISerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)
    replacement_ci = serializers.IntegerField(required=False, allow_null=True,
                                              default=None)
    retirement_date = serializers.DateTimeField(required=False, allow_null=True,
                                                default=None)
    acknowledge_impact = serializers.BooleanField(required=False, default=False)
    expected_record_version = serializers.IntegerField(
        required=False, allow_null=True, default=None,
    )


class DriftActionSerializer(serializers.Serializer):
    note = serializers.CharField(
        required=False, allow_blank=True, default="", allow_null=True,
    )
    resolution_note = serializers.CharField(
        required=False, allow_blank=True, default="", allow_null=True,
    )

    def get_note(self):
        return self.validated_data.get("resolution_note") or \
            self.validated_data.get("note") or ""
