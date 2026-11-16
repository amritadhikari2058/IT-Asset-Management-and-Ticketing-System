import hashlib
import json
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from common.models import SoftDeleteModel

class ConfigurationItemType(SoftDeleteModel):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40, unique=True)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=40, default="other")
    icon = models.CharField(max_length=60, blank=True, default="")
    color = models.CharField(max_length=20, blank=True, default="")
    schema = models.JSONField(default=dict, blank=True)
    required_attributes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_types_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["name"]
    def __str__(self):
        return self.name
    def clean(self):
        if not isinstance(self.schema, dict):
            raise ValidationError("schema must be an object")
        if not isinstance(self.required_attributes, list):
            raise ValidationError("required_attributes must be a list")

class ConfigurationItem(SoftDeleteModel):
    STATUS_CHOICES = [("planned","Planned"),("active","Active"),("inactive","Inactive"),("maintenance","Maintenance"),("degraded","Degraded"),("failed","Failed"),("retired","Retired"),("disposed","Disposed"),("unknown","Unknown")]
    LIFECYCLE_CHOICES = [("proposed","Proposed"),("ordered","Ordered"),("received","Received"),("installed","Installed"),("operational","Operational"),("under_change","Under Change"),("retired","Retired"),("disposed","Disposed")]
    CRITICALITY_CHOICES = [("low","Low"),("medium","Medium"),("high","High"),("critical","Critical")]
    ENV_CHOICES = [("development","Development"),("test","Test"),("staging","Staging"),("production","Production"),("disaster_recovery","Disaster Recovery"),("office","Office"),("other","Other")]
    SOURCE_CHOICES = [("manual","Manual"),("asset_sync","Asset Sync"),("licensing_sync","Licensing Sync"),("discovery","Discovery"),("import","Import"),("integration","Integration")]
    MONITORING_CHOICES = [("monitored","Monitored"),("not_monitored","Not Monitored"),("not_applicable","Not Applicable"),("unknown","Unknown")]
    DATA_CLASS_CHOICES = [("public","Public"),("internal","Internal"),("confidential","Confidential"),("restricted","Restricted"),("unknown","Unknown")]
    IMPACT_CHOICES = [("none","None"),("documentation_only","Documentation Only"),("configuration","Configuration"),("functional_change","Functional Change"),("data_integrity_impact","Data Integrity Impact")]
    ci_number = models.CharField(max_length=40, unique=True, blank=True)
    name = models.CharField(max_length=200)
    ci_type = models.ForeignKey(ConfigurationItemType, on_delete=models.PROTECT, related_name="configuration_items")
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="planned")
    lifecycle_state = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default="proposed")
    criticality = models.CharField(max_length=20, choices=CRITICALITY_CHOICES, default="medium")
    environment = models.CharField(max_length=30, choices=ENV_CHOICES, default="production")
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="configuration_items")
    software_product = models.ForeignKey("licensing.SoftwareProduct", null=True, blank=True, on_delete=models.SET_NULL, related_name="configuration_items")
    service_catalogue_item = models.ForeignKey("services.ServiceCatalogueItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="configuration_items")
    department = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="configuration_items")
    location = models.CharField(max_length=200, blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_configuration_items")
    technical_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="technical_configuration_items")
    support_group = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="supported_configuration_items")
    vendor = models.ForeignKey("assets.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="configuration_items")
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    serial_number = models.CharField(max_length=120, blank=True, default="")
    version = models.CharField(max_length=60, blank=True, default="")
    hostname = models.CharField(max_length=200, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    dns_name = models.CharField(max_length=200, blank=True, default="")
    external_reference = models.CharField(max_length=200, blank=True, default="")
    attributes = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default="manual")
    source_identifier = models.CharField(max_length=200, blank=True, default="")
    last_discovered_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_configuration_items")
    monitoring_state = models.CharField(max_length=20, choices=MONITORING_CHOICES, default="unknown")
    data_classification = models.CharField(max_length=20, choices=DATA_CLASS_CHOICES, default="internal")
    contains_personal_data = models.BooleanField(default=False)
    validated_system_impact = models.CharField(max_length=30, choices=IMPACT_CHOICES, default="none")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_configuration_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    record_version = models.PositiveIntegerField(default=1)
    class Meta:
        ordering = ["ci_number"]
        indexes = [models.Index(fields=["ci_number"]), models.Index(fields=["status"]), models.Index(fields=["criticality"]), models.Index(fields=["environment"])]
    def __str__(self):
        return f"{self.ci_number} {self.name}"
    def save(self, *args, **kwargs):
        if not self.ci_number:
            self.ci_number = self._generate_number()
        super().save(*args, **kwargs)
    @staticmethod
    def _generate_number():
        year = timezone.now().year
        last = ConfigurationItem.all_objects.filter(ci_number__startswith=f"CI-{year}-").order_by("-ci_number").first()
        n = 1
        if last and last.ci_number:
            try:
                n = int(last.ci_number.split("-")[-1]) + 1
            except ValueError:
                n = ConfigurationItem.all_objects.filter(ci_number__startswith=f"CI-{year}-").count() + 1
        return f"CI-{year}-{n:06d}"

class ConfigurationItemRelationship(SoftDeleteModel):
    REL_TYPES = [("depends_on","Depends On"),("required_by","Required By"),("hosted_on","Hosted On"),("hosts","Hosts"),("runs_on","Runs On"),("runs","Runs"),("connects_to","Connects To"),("connected_from","Connected From"),("uses","Uses"),("used_by","Used By"),("contains","Contains"),("contained_by","Contained By"),("part_of","Part Of"),("has_part","Has Part"),("backs_up","Backs Up"),("backed_up_by","Backed Up By"),("replicates_to","Replicates To"),("replicated_from","Replicated From"),("monitors","Monitors"),("monitored_by","Monitored By"),("managed_by","Managed By"),("manages","Manages"),("supports","Supports"),("supported_by","Supported By"),("located_in","Located In"),("related_to","Related To"),("replaces","Replaces"),("replaced_by","Replaced By")]
    STATUS_CHOICES = [("active","Active"),("inactive","Inactive"),("proposed","Proposed"),("rejected","Rejected")]
    SOURCE_CHOICES = [("manual","Manual"),("asset_sync","Asset Sync"),("discovery","Discovery"),("import","Import"),("integration","Integration")]
    CONF_CHOICES = [("confirmed","Confirmed"),("high","High"),("medium","Medium"),("low","Low"),("unknown","Unknown")]
    source_ci = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="outgoing_relationships")
    target_ci = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="incoming_relationships")
    relationship_type = models.CharField(max_length=30, choices=REL_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    description = models.TextField(blank=True, default="")
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    discovered = models.BooleanField(default=False)
    confidence = models.CharField(max_length=20, choices=CONF_CHOICES, default="confirmed")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_relationships_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = [("source_ci","target_ci","relationship_type")]
        indexes = [models.Index(fields=["source_ci","status"]), models.Index(fields=["target_ci","status"])]
    def clean(self):
        if self.source_ci_id == self.target_ci_id:
            raise ValidationError("Self-reference not allowed")

class ConfigurationItemHistory(models.Model):
    configuration_item = models.ForeignKey(ConfigurationItem, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    relationship = models.ForeignKey(ConfigurationItemRelationship, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=40)
    previous_status = models.CharField(max_length=40, blank=True, default="")
    new_status = models.CharField(max_length=40, blank=True, default="")
    changed_fields = models.JSONField(default=dict, blank=True)
    detail = models.TextField(blank=True, default="")
    source = models.CharField(max_length=30, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
        # immutable: no delete via API (enforced in views)

class ConfigurationBaseline(SoftDeleteModel):
    SCOPE_CHOICES = [("single_ci","Single CI"),("ci_group","CI Group"),("service","Service"),("environment","Environment"),("department","Department")]
    STATUS_CHOICES = [("draft","Draft"),("pending_approval","Pending Approval"),("approved","Approved"),("superseded","Superseded"),("retired","Retired")]
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="single_ci")
    service = models.ForeignKey("services.ServiceCatalogueItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_baselines")
    configuration_items = models.ManyToManyField(ConfigurationItem, blank=True, related_name="baselines")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    baseline_date = models.DateTimeField(default=timezone.now)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_baselines_created")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_baselines_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    checksum = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"BL-{timezone.now().year}-{ConfigurationBaseline.all_objects.count()+1:06d}"
        super().save(*args, **kwargs)

class ConfigurationDriftFinding(SoftDeleteModel):
    FINDING_TYPES = [("field_changed","Field Changed"),("relationship_added","Relationship Added"),("relationship_removed","Relationship Removed"),("relationship_changed","Relationship Changed"),("status_changed","Status Changed"),("owner_changed","Owner Changed"),("software_version_changed","Software Version Changed"),("unverified_ci","Unverified CI"),("orphan_ci","Orphan CI"),("duplicate_ci","Duplicate CI"),("missing_required_attribute","Missing Required Attribute"),("unexpected_attribute","Unexpected Attribute"),("other","Other")]
    SEVERITY_CHOICES = [("info","Info"),("low","Low"),("medium","Medium"),("high","High"),("critical","Critical")]
    STATUS_CHOICES = [("open","Open"),("acknowledged","Acknowledged"),("resolved","Resolved"),("accepted","Accepted"),("false_positive","False Positive")]
    configuration_item = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="drift_findings")
    baseline = models.ForeignKey(ConfigurationBaseline, null=True, blank=True, on_delete=models.SET_NULL, related_name="drift_findings")
    finding_type = models.CharField(max_length=40, choices=FINDING_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="low")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    field_name = models.CharField(max_length=120, blank=True, default="")
    expected_value = models.TextField(blank=True, default="")
    actual_value = models.TextField(blank=True, default="")
    detected_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_drift_ack")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cmdb_drift_res")
    resolution_note = models.TextField(blank=True, default="")
    fingerprint = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=30, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        indexes = [models.Index(fields=["fingerprint"]), models.Index(fields=["status","severity"])]

class CMDBServiceProfile(SoftDeleteModel):
    service = models.OneToOneField("services.ServiceCatalogueItem", on_delete=models.CASCADE, related_name="cmdb_profile")
    service_tier = models.CharField(max_length=10, default="tier_3")
    service_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_cmdb_services")
    technical_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="technical_cmdb_services")
    business_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="business_cmdb_services")
    support_group = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="supported_cmdb_services")
    criticality = models.CharField(max_length=20, choices=ConfigurationItem.CRITICALITY_CHOICES, default="medium")
    availability_target = models.DecimalField(max_digits=5, decimal_places=2, default=99.00)
    rto_minutes = models.PositiveIntegerField(default=0)
    rpo_minutes = models.PositiveIntegerField(default=0)
    business_hours = models.CharField(max_length=120, blank=True, default="")
    maintenance_window = models.CharField(max_length=120, blank=True, default="")
    is_customer_facing = models.BooleanField(default=False)
    is_regulated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ServiceConfigurationItemLink(SoftDeleteModel):
    service = models.ForeignKey("services.ServiceCatalogueItem", on_delete=models.CASCADE, related_name="cmdb_ci_links")
    configuration_item = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="service_links")
    role = models.CharField(max_length=30, default="dependency")
    criticality = models.CharField(max_length=20, choices=ConfigurationItem.CRITICALITY_CHOICES, default="medium")
    redundancy_group = models.CharField(max_length=60, blank=True, default="")
    is_required = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = [("service","configuration_item")]

class ConfigurationItemTicketLink(SoftDeleteModel):
    configuration_item = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="ticket_links")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="cmdb_links")
    relation_type = models.CharField(max_length=30, default="affected")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("configuration_item","ticket","relation_type")]

class ConfigurationItemChangeLink(SoftDeleteModel):
    configuration_item = models.ForeignKey(ConfigurationItem, on_delete=models.CASCADE, related_name="change_links")
    change = models.ForeignKey("changes.ChangeRequest", on_delete=models.CASCADE, related_name="cmdb_links")
    impact_type = models.CharField(max_length=20, default="direct")
    change_role = models.CharField(max_length=20, default="affected")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("configuration_item","change")]
