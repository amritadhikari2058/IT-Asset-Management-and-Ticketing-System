from rest_framework import serializers
from .models import (
    ConfigurationItemType, ConfigurationItem, ConfigurationItemRelationship,
    ConfigurationItemHistory, ConfigurationBaseline, ConfigurationDriftFinding,
    CMDBServiceProfile, ServiceConfigurationItemLink,
    ConfigurationItemTicketLink, ConfigurationItemChangeLink,
)

class ConfigurationItemTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigurationItemType
        fields = ["id","name","code","description","category","icon","color","schema","required_attributes","is_active","is_system","created_by","created_at","updated_at"]
        read_only_fields = ["id","created_by","created_at","updated_at"]

class ConfigurationItemSerializer(serializers.ModelSerializer):
    ci_type_name = serializers.CharField(source="ci_type.name", read_only=True)
    class Meta:
        model = ConfigurationItem
        fields = ["id","ci_number","name","ci_type","ci_type_name","description","status","lifecycle_state","criticality","environment","asset","software_product","service_catalogue_item","department","location","owner","technical_owner","support_group","vendor","manufacturer","model","serial_number","version","hostname","ip_address","dns_name","external_reference","attributes","source","source_identifier","last_discovered_at","last_verified_at","verified_by","monitoring_state","data_classification","contains_personal_data","validated_system_impact","created_by","created_at","updated_at","record_version"]
        read_only_fields = ["id","ci_number","created_by","created_at","updated_at","record_version","last_verified_at","verified_by"]

class ConfigurationItemRelationshipSerializer(serializers.ModelSerializer):
    source_ci_number = serializers.CharField(source="source_ci.ci_number", read_only=True)
    target_ci_number = serializers.CharField(source="target_ci.ci_number", read_only=True)
    class Meta:
        model = ConfigurationItemRelationship
        fields = ["id","source_ci","source_ci_number","target_ci","target_ci_number","relationship_type","status","description","valid_from","valid_to","discovered","confidence","source","created_by","created_at","updated_at"]
        read_only_fields = ["id","created_by","created_at","updated_at"]
    def validate(self, attrs):
        src = attrs.get("source_ci")
        tgt = attrs.get("target_ci")
        if src and tgt and src.id == tgt.id:
            raise serializers.ValidationError("Self-reference not allowed.")
        rtype = attrs.get("relationship_type")
        if src and tgt and rtype:
            from .models import ConfigurationItemRelationship
            if ConfigurationItemRelationship.objects.filter(source_ci=src, target_ci=tgt, relationship_type=rtype, is_deleted=False).exists():
                raise serializers.ValidationError("Duplicate relationship.")
        return attrs

class ConfigurationItemHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True)
    class Meta:
        model = ConfigurationItemHistory
        fields = ["id","configuration_item","relationship","actor","actor_email","event_type","previous_status","new_status","changed_fields","detail","source","created_at"]
        read_only_fields = fields

class ConfigurationBaselineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigurationBaseline
        fields = ["id","name","code","description","scope_type","service","configuration_items","status","baseline_date","effective_from","effective_to","version","created_by","approved_by","approved_at","snapshot","checksum","created_at","updated_at"]
        read_only_fields = ["id","code","status","version","created_by","approved_by","approved_at","snapshot","checksum","created_at","updated_at"]

class ConfigurationDriftFindingSerializer(serializers.ModelSerializer):
    ci_number = serializers.CharField(source="configuration_item.ci_number", read_only=True)
    class Meta:
        model = ConfigurationDriftFinding
        fields = ["id","configuration_item","ci_number","baseline","finding_type","severity","status","field_name","expected_value","actual_value","detected_at","acknowledged_at","acknowledged_by","resolved_at","resolved_by","resolution_note","fingerprint","source","created_at","updated_at"]
        read_only_fields = ["id","configuration_item","baseline","finding_type","severity","field_name","expected_value","actual_value","detected_at","fingerprint","created_at","updated_at"]

class CMDBServiceProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CMDBServiceProfile
        fields = ["id","service","service_tier","service_owner","technical_owner","business_owner","support_group","criticality","availability_target","rto_minutes","rpo_minutes","business_hours","maintenance_window","is_customer_facing","is_regulated","created_at","updated_at"]
        read_only_fields = ["id","created_at","updated_at"]

class ServiceConfigurationItemLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceConfigurationItemLink
        fields = ["id","service","configuration_item","role","criticality","redundancy_group","is_required","notes","created_by","created_at","updated_at"]
        read_only_fields = ["id","created_by","created_at","updated_at"]

class ConfigurationItemTicketLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigurationItemTicketLink
        fields = ["id","configuration_item","ticket","relation_type","created_by","created_at"]
        read_only_fields = ["id","created_by","created_at"]

class ConfigurationItemChangeLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigurationItemChangeLink
        fields = ["id","configuration_item","change","impact_type","change_role","created_by","created_at"]
        read_only_fields = ["id","created_by","created_at"]

class VerifyCISerializer(serializers.Serializer):
    verification_note = serializers.CharField(required=False, allow_blank=True, default="")
    expected_record_version = serializers.IntegerField(required=True)

class RetireCISerializer(serializers.Serializer):
    reason = serializers.CharField(required=True)
    replacement_ci = serializers.IntegerField(required=False, allow_null=True)
    retirement_date = serializers.DateTimeField(required=False, allow_null=True)
    expected_record_version = serializers.IntegerField(required=True)
