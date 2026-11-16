import hashlib
import json
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from common.models import SoftDeleteModel

# ---------------------------------------------------------------------------
# Relationship semantics — explicit maps, never inferred from input.
# ---------------------------------------------------------------------------

# Inverse relationship types. Symmetric types map to themselves.
INVERSE_REL_TYPES = {
    "depends_on": "required_by",
    "required_by": "depends_on",
    "hosted_on": "hosts",
    "hosts": "hosted_on",
    "runs_on": "runs",
    "runs": "runs_on",
    "connects_to": "connected_from",
    "connected_from": "connects_to",
    "uses": "used_by",
    "used_by": "uses",
    "contains": "contained_by",
    "contained_by": "contains",
    "part_of": "has_part",
    "has_part": "part_of",
    "backs_up": "backed_up_by",
    "backed_up_by": "backs_up",
    "replicates_to": "replicated_from",
    "replicated_from": "replicates_to",
    "monitors": "monitored_by",
    "monitored_by": "monitors",
    "manages": "managed_by",
    "managed_by": "manages",
    "supports": "supported_by",
    "supported_by": "supports",
    "located_in": "located_in",  # no dedicated inverse type; treated as one-way
    "related_to": "related_to",  # symmetric
    "replaces": "replaced_by",
    "replaced_by": "replaces",
}

# Dependency orientation used by traversal/impact analysis:
#   "forward"   -> source_ci depends on target_ci
#   "reverse"   -> target_ci depends on source_ci
#   "symmetric" -> either direction is a weak dependency (related_to)
#   "neutral"   -> not a dependency edge (replaces / replaced_by)
RELATIONSHIP_ORIENTATION = {
    "depends_on": "forward",
    "required_by": "reverse",
    "hosted_on": "forward",
    "hosts": "reverse",
    "runs_on": "forward",
    "runs": "reverse",
    "connects_to": "forward",
    "connected_from": "reverse",
    "uses": "forward",
    "used_by": "reverse",
    "contains": "forward",
    "contained_by": "reverse",
    "part_of": "reverse",
    "has_part": "forward",
    "backs_up": "reverse",
    "backed_up_by": "forward",
    "replicates_to": "reverse",
    "replicated_from": "forward",
    "monitors": "forward",
    "monitored_by": "reverse",
    "manages": "forward",
    "managed_by": "reverse",
    "supports": "reverse",
    "supported_by": "forward",
    "located_in": "forward",
    "related_to": "symmetric",
    "replaces": "neutral",
    "replaced_by": "neutral",
}

# Hierarchy types where structural cycles are invalid. Value says which way
# the child -> parent edge runs for a relationship (source, target).
HIERARCHY_PARENT_DIRECTION = {
    "contains": "target_to_source",    # A contains B: A is parent of B
    "contained_by": "source_to_target",  # A contained_by B: B is parent of A
    "part_of": "source_to_target",     # A part_of B: B is parent of A
    "has_part": "target_to_source",    # A has_part B: A is parent of B
    "hosted_on": "source_to_target",   # A hosted_on B: B is parent of A
    "hosts": "target_to_source",       # A hosts B: A is parent of B
    "runs_on": "source_to_target",     # A runs_on B: B is parent of A
    "runs": "target_to_source",        # A runs B: A is parent of B
}

# ---------------------------------------------------------------------------
# Attribute / schema validation helpers (no secrets, bounded sizes).
# ---------------------------------------------------------------------------

SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|"
    r"passphrase|license[_-]?key|encryption|auth)",
    re.IGNORECASE,
)
ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")

MAX_SCHEMA_FIELDS = 50
MAX_SCHEMA_DEPTH = 4
MAX_ATTRIBUTE_JSON_BYTES = 50_000
MAX_ATTRIBUTE_VALUE_CHARS = 2_000
MAX_CHOICES = 100

ALLOWED_SCHEMA_TYPES = {
    "string", "text", "integer", "number", "boolean", "date", "datetime",
    "choice", "multichoice", "url", "email", "ip", "reference",
}
ALLOWED_SCHEMA_DESCRIPTOR_KEYS = {
    "type", "label", "choices", "required", "help_text", "max_length",
    "min", "max", "pattern", "default",
}


def _json_depth(value, depth=0):
    if depth > MAX_SCHEMA_DEPTH:
        return depth
    if isinstance(value, dict):
        return max([_json_depth(v, depth + 1) for v in value.values()] or [depth])
    if isinstance(value, list):
        return max([_json_depth(v, depth + 1) for v in value] or [depth])
    return depth


def validate_type_schema(schema, required_attributes):
    """Validate a CI Type schema: bounded, declarative, non-executable."""
    if not isinstance(schema, dict):
        raise ValidationError("schema must be an object")
    if not isinstance(required_attributes, list):
        raise ValidationError("required_attributes must be a list")
    if len(schema) > MAX_SCHEMA_FIELDS:
        raise ValidationError(f"schema may define at most {MAX_SCHEMA_FIELDS} fields")
    if _json_depth(schema) > MAX_SCHEMA_DEPTH:
        raise ValidationError(f"schema nesting may not exceed depth {MAX_SCHEMA_DEPTH}")
    for key, descriptor in schema.items():
        if not isinstance(key, str) or not ATTRIBUTE_KEY_RE.match(key):
            raise ValidationError(f"invalid schema field name: {key!r}")
        if SECRET_KEY_RE.search(key):
            raise ValidationError(f"schema must not define secret field: {key!r}")
        if not isinstance(descriptor, dict):
            raise ValidationError(f"schema field {key!r} must be an object descriptor")
        unknown = set(descriptor) - ALLOWED_SCHEMA_DESCRIPTOR_KEYS
        if unknown:
            raise ValidationError(
                f"schema field {key!r} has unsupported descriptor keys: {sorted(unknown)}"
            )
        field_type = descriptor.get("type")
        if field_type not in ALLOWED_SCHEMA_TYPES:
            raise ValidationError(
                f"schema field {key!r} has invalid type {field_type!r}"
            )
        choices = descriptor.get("choices")
        if choices is not None:
            if not isinstance(choices, list) or not choices:
                raise ValidationError(f"schema field {key!r} choices must be a non-empty list")
            if len(choices) > MAX_CHOICES:
                raise ValidationError(f"schema field {key!r} has too many choices")
            for choice in choices:
                if not isinstance(choice, (str, int, float, bool)) or isinstance(choice, (dict, list)):
                    raise ValidationError(f"schema field {key!r} has non-scalar choice")
        pattern = descriptor.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or len(pattern) > 200:
                raise ValidationError(f"schema field {key!r} pattern must be a short string")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValidationError(f"schema field {key!r} pattern is invalid: {exc}")
    for attr in required_attributes:
        if not isinstance(attr, str):
            raise ValidationError("required_attributes entries must be strings")
        if schema and attr not in schema:
            raise ValidationError(
                f"required attribute {attr!r} is not defined in schema"
            )
    if len(required_attributes) > MAX_SCHEMA_FIELDS:
        raise ValidationError("too many required_attributes")


def validate_ci_attributes(attributes, ci_type=None):
    """Validate CI attributes: no secrets, bounded size, schema-conformant."""
    if attributes is None:
        attributes = {}
    if not isinstance(attributes, dict):
        raise ValidationError("attributes must be an object")
    try:
        raw = json.dumps(attributes, default=str)
    except (TypeError, ValueError) as exc:
        raise ValidationError("attributes must be JSON-serializable") from exc
    if len(raw.encode("utf-8")) > MAX_ATTRIBUTE_JSON_BYTES:
        raise ValidationError("attributes payload is too large")
    if _json_depth(attributes) > MAX_SCHEMA_DEPTH:
        raise ValidationError("attributes nesting is too deep")
    for key, value in attributes.items():
        if not isinstance(key, str) or not ATTRIBUTE_KEY_RE.match(key):
            raise ValidationError(f"invalid attribute name: {key!r}")
        if SECRET_KEY_RE.search(key):
            raise ValidationError(f"secret attribute not allowed: {key!r}")
        if isinstance(value, str) and len(value) > MAX_ATTRIBUTE_VALUE_CHARS:
            raise ValidationError(f"attribute {key!r} value is too long")
        if isinstance(value, dict):
            raise ValidationError(f"attribute {key!r} must be a scalar or list of scalars")
        if isinstance(value, list):
            for item in value:
                if item is not None and not isinstance(item, (str, int, float, bool)):
                    raise ValidationError(f"attribute {key!r} has non-scalar entry")

    schema = {}
    required = []
    if ci_type is not None:
        schema = ci_type.schema or {}
        required = ci_type.required_attributes or []

    for key, descriptor in schema.items():
        if key not in attributes:
            if descriptor.get("required") or key in required:
                raise ValidationError(f"missing required attribute: {key!r}")
            continue
        value = attributes[key]
        expected = descriptor.get("type")
        ok = True
        if expected in ("string", "text", "url", "email", "ip"):
            ok = isinstance(value, str)
        elif expected == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected == "boolean":
            ok = isinstance(value, bool)
        elif expected in ("date", "datetime"):
            ok = isinstance(value, str)
        elif expected == "choice":
            ok = isinstance(value, str) and (
                not descriptor.get("choices") or value in descriptor["choices"]
            )
        elif expected == "multichoice":
            ok = isinstance(value, list) and (
                not descriptor.get("choices")
                or all(item in descriptor["choices"] for item in value)
            )
        elif expected == "reference":
            ok = isinstance(value, (str, int))
        if not ok:
            raise ValidationError(
                f"attribute {key!r} must match schema type {expected!r}"
            )

    for key in required:
        if key not in attributes or attributes[key] in ("", None):
            raise ValidationError(f"missing required attribute: {key!r}")


def normalize_hostname(value):
    """Lowercase and strip trailing dot from a hostname/DNS name."""
    if not value:
        return ""
    return value.strip().rstrip(".").lower()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_types_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().upper()
        if not self.code:
            raise ValidationError({"code": "code is required"})
        validate_type_schema(self.schema or {}, self.required_attributes or [])

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)


class ConfigurationItem(SoftDeleteModel):
    STATUS_CHOICES = [
        ("planned", "Planned"), ("active", "Active"), ("inactive", "Inactive"),
        ("maintenance", "Maintenance"), ("degraded", "Degraded"),
        ("failed", "Failed"), ("retired", "Retired"), ("disposed", "Disposed"),
        ("unknown", "Unknown"),
    ]
    LIFECYCLE_CHOICES = [
        ("proposed", "Proposed"), ("ordered", "Ordered"), ("received", "Received"),
        ("installed", "Installed"), ("operational", "Operational"),
        ("under_change", "Under Change"), ("retired", "Retired"),
        ("disposed", "Disposed"),
    ]
    CRITICALITY_CHOICES = [
        ("low", "Low"), ("medium", "Medium"), ("high", "High"),
        ("critical", "Critical"),
    ]
    ENV_CHOICES = [
        ("development", "Development"), ("test", "Test"),
        ("staging", "Staging"), ("production", "Production"),
        ("disaster_recovery", "Disaster Recovery"), ("office", "Office"),
        ("other", "Other"),
    ]
    SOURCE_CHOICES = [
        ("manual", "Manual"), ("asset_sync", "Asset Sync"),
        ("licensing_sync", "Licensing Sync"), ("discovery", "Discovery"),
        ("import", "Import"), ("integration", "Integration"),
    ]
    MONITORING_CHOICES = [
        ("monitored", "Monitored"), ("not_monitored", "Not Monitored"),
        ("not_applicable", "Not Applicable"), ("unknown", "Unknown"),
    ]
    DATA_CLASS_CHOICES = [
        ("public", "Public"), ("internal", "Internal"),
        ("confidential", "Confidential"), ("restricted", "Restricted"),
        ("unknown", "Unknown"),
    ]
    IMPACT_CHOICES = [
        ("none", "None"), ("documentation_only", "Documentation Only"),
        ("configuration", "Configuration"),
        ("functional_change", "Functional Change"),
        ("data_integrity_impact", "Data Integrity Impact"),
    ]

    RETIRED_STATUSES = ("retired", "disposed")

    ci_number = models.CharField(max_length=40, unique=True, blank=True)
    name = models.CharField(max_length=200)
    ci_type = models.ForeignKey(
        ConfigurationItemType, on_delete=models.PROTECT,
        related_name="configuration_items",
    )
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="planned")
    lifecycle_state = models.CharField(
        max_length=20, choices=LIFECYCLE_CHOICES, default="proposed",
    )
    criticality = models.CharField(
        max_length=20, choices=CRITICALITY_CHOICES, default="medium",
    )
    environment = models.CharField(
        max_length=30, choices=ENV_CHOICES, default="production",
    )
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="configuration_items",
    )
    software_product = models.ForeignKey(
        "licensing.SoftwareProduct", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="configuration_items",
    )
    service_catalogue_item = models.ForeignKey(
        "services.ServiceCatalogueItem", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="configuration_items",
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="configuration_items",
    )
    location = models.CharField(max_length=200, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_configuration_items",
    )
    technical_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="technical_configuration_items",
    )
    support_group = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="supported_configuration_items",
    )
    vendor = models.ForeignKey(
        "assets.Vendor", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="configuration_items",
    )
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
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="verified_configuration_items",
    )
    monitoring_state = models.CharField(
        max_length=20, choices=MONITORING_CHOICES, default="unknown",
    )
    data_classification = models.CharField(
        max_length=20, choices=DATA_CLASS_CHOICES, default="internal",
    )
    contains_personal_data = models.BooleanField(default=False)
    validated_system_impact = models.CharField(
        max_length=30, choices=IMPACT_CHOICES, default="none",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_configuration_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    record_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["ci_number"]
        indexes = [
            models.Index(fields=["ci_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["criticality"]),
            models.Index(fields=["environment"]),
            models.Index(fields=["last_verified_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset"],
                condition=(
                    models.Q(is_deleted=False)
                    & ~models.Q(asset=None)
                    & ~models.Q(status__in=("retired", "disposed"))
                ),
                name="uniq_active_ci_per_asset",
            ),
        ]

    def __str__(self):
        return f"{self.ci_number} {self.name}"

    def clean(self):
        super().clean()
        self.hostname = normalize_hostname(self.hostname)
        self.dns_name = normalize_hostname(self.dns_name)
        validate_ci_attributes(self.attributes or {}, self.ci_type)

    @staticmethod
    def _generate_number():
        year = timezone.now().year
        prefix = f"CI-{year}-"
        last = (
            ConfigurationItem.all_objects
            .filter(ci_number__startswith=prefix)
            .order_by("-ci_number")
            .values_list("ci_number", flat=True)
            .first()
        )
        n = 1
        if last:
            try:
                n = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                n = (
                    ConfigurationItem.all_objects
                    .filter(ci_number__startswith=prefix)
                    .count()
                    + 1
                )
        return f"{prefix}{n:06d}"

    def save(self, *args, **kwargs):
        if not self.ci_number:
            # Concurrency-safe allocation: bounded retries on unique collision.
            last_exc = None
            for _ in range(50):
                self.ci_number = self._generate_number()
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError as exc:
                    last_exc = exc
                    if "ci_number" not in str(exc):
                        raise
                    continue
            raise ValidationError(
                "Could not allocate a unique CI number; please retry."
            ) from last_exc
        return super().save(*args, **kwargs)


class ConfigurationItemRelationship(SoftDeleteModel):
    REL_TYPES = [
        ("depends_on", "Depends On"), ("required_by", "Required By"),
        ("hosted_on", "Hosted On"), ("hosts", "Hosts"),
        ("runs_on", "Runs On"), ("runs", "Runs"),
        ("connects_to", "Connects To"), ("connected_from", "Connected From"),
        ("uses", "Uses"), ("used_by", "Used By"),
        ("contains", "Contains"), ("contained_by", "Contained By"),
        ("part_of", "Part Of"), ("has_part", "Has Part"),
        ("backs_up", "Backs Up"), ("backed_up_by", "Backed Up By"),
        ("replicates_to", "Replicates To"), ("replicated_from", "Replicated From"),
        ("monitors", "Monitors"), ("monitored_by", "Monitored By"),
        ("managed_by", "Managed By"), ("manages", "Manages"),
        ("supports", "Supports"), ("supported_by", "Supported By"),
        ("located_in", "Located In"), ("related_to", "Related To"),
        ("replaces", "Replaces"), ("replaced_by", "Replaced By"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"), ("inactive", "Inactive"),
        ("proposed", "Proposed"), ("rejected", "Rejected"),
    ]
    SOURCE_CHOICES = [
        ("manual", "Manual"), ("asset_sync", "Asset Sync"),
        ("discovery", "Discovery"), ("import", "Import"),
        ("integration", "Integration"),
    ]
    CONF_CHOICES = [
        ("confirmed", "Confirmed"), ("high", "High"), ("medium", "Medium"),
        ("low", "Low"), ("unknown", "Unknown"),
    ]

    source_ci = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE,
        related_name="outgoing_relationships",
    )
    target_ci = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE,
        related_name="incoming_relationships",
    )
    relationship_type = models.CharField(max_length=30, choices=REL_TYPES)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active",
    )
    description = models.TextField(blank=True, default="")
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    discovered = models.BooleanField(default=False)
    confidence = models.CharField(
        max_length=20, choices=CONF_CHOICES, default="confirmed",
    )
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default="manual",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_relationships_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_ci", "status"]),
            models.Index(fields=["target_ci", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_ci", "target_ci", "relationship_type"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_cmdb_relationship",
            ),
        ]

    def clean(self):
        super().clean()
        if self.source_ci_id and (
            self.source_ci_id == self.target_ci_id
        ):
            raise ValidationError("Self-reference not allowed")
        if not self.relationship_type:
            raise ValidationError({"relationship_type": "relationship_type is required"})


class ConfigurationItemHistory(models.Model):
    """Append-only audit trail. Records are immutable after creation."""

    configuration_item = models.ForeignKey(
        ConfigurationItem, null=True, blank=True, on_delete=models.CASCADE,
        related_name="history",
    )
    relationship = models.ForeignKey(
        ConfigurationItemRelationship, null=True, blank=True,
        on_delete=models.CASCADE, related_name="history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    event_type = models.CharField(max_length=40)
    previous_status = models.CharField(max_length=40, blank=True, default="")
    new_status = models.CharField(max_length=40, blank=True, default="")
    changed_fields = models.JSONField(default=dict, blank=True)
    detail = models.TextField(blank=True, default="")
    source = models.CharField(max_length=30, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("History records are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("History records cannot be deleted.")

    def __str__(self):
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"


class ConfigurationBaseline(SoftDeleteModel):
    SCOPE_CHOICES = [
        ("single_ci", "Single CI"), ("ci_group", "CI Group"),
        ("service", "Service"), ("environment", "Environment"),
        ("department", "Department"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"), ("pending_approval", "Pending Approval"),
        ("approved", "Approved"), ("superseded", "Superseded"),
        ("retired", "Retired"),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    scope_type = models.CharField(
        max_length=20, choices=SCOPE_CHOICES, default="single_ci",
    )
    service = models.ForeignKey(
        "services.ServiceCatalogueItem", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_baselines",
    )
    configuration_items = models.ManyToManyField(
        ConfigurationItem, blank=True, related_name="baselines",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft",
    )
    baseline_date = models.DateTimeField(default=timezone.now)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_baselines_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_baselines_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    checksum = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def _generate_code():
        year = timezone.now().year
        prefix = f"BL-{year}-"
        last = (
            ConfigurationBaseline.all_objects
            .filter(code__startswith=prefix)
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )
        n = 1
        if last:
            try:
                n = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                n = (
                    ConfigurationBaseline.all_objects
                    .filter(code__startswith=prefix).count() + 1
                )
        return f"{prefix}{n:06d}"

    def save(self, *args, **kwargs):
        if not self.code:
            last_exc = None
            for _ in range(50):
                self.code = self._generate_code()
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError as exc:
                    last_exc = exc
                    if "code" not in str(exc):
                        raise
                    continue
            raise ValidationError(
                "Could not allocate a unique baseline code; please retry."
            ) from last_exc
        return super().save(*args, **kwargs)


class ConfigurationDriftFinding(SoftDeleteModel):
    FINDING_TYPES = [
        ("field_changed", "Field Changed"),
        ("relationship_added", "Relationship Added"),
        ("relationship_removed", "Relationship Removed"),
        ("relationship_changed", "Relationship Changed"),
        ("status_changed", "Status Changed"),
        ("owner_changed", "Owner Changed"),
        ("software_version_changed", "Software Version Changed"),
        ("unverified_ci", "Unverified CI"),
        ("orphan_ci", "Orphan CI"),
        ("duplicate_ci", "Duplicate CI"),
        ("missing_required_attribute", "Missing Required Attribute"),
        ("unexpected_attribute", "Unexpected Attribute"),
        ("other", "Other"),
    ]
    SEVERITY_CHOICES = [
        ("info", "Info"), ("low", "Low"), ("medium", "Medium"),
        ("high", "High"), ("critical", "Critical"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"), ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"), ("accepted", "Accepted"),
        ("false_positive", "False Positive"),
    ]

    configuration_item = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE, related_name="drift_findings",
    )
    baseline = models.ForeignKey(
        ConfigurationBaseline, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="drift_findings",
    )
    finding_type = models.CharField(max_length=40, choices=FINDING_TYPES)
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default="low",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="open",
    )
    field_name = models.CharField(max_length=120, blank=True, default="")
    expected_value = models.TextField(blank=True, default="")
    actual_value = models.TextField(blank=True, default="")
    detected_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_drift_ack",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cmdb_drift_res",
    )
    resolution_note = models.TextField(blank=True, default="")
    fingerprint = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=30, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["fingerprint"]),
            models.Index(fields=["status", "severity"]),
        ]


class CMDBServiceProfile(SoftDeleteModel):
    TIER_CHOICES = [
        ("tier_1", "Tier 1"), ("tier_2", "Tier 2"), ("tier_3", "Tier 3"),
        ("tier_4", "Tier 4"),
    ]

    service = models.OneToOneField(
        "services.ServiceCatalogueItem", on_delete=models.CASCADE,
        related_name="cmdb_profile",
    )
    service_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default="tier_3")
    service_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_cmdb_services",
    )
    technical_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="technical_cmdb_services",
    )
    business_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="business_cmdb_services",
    )
    support_group = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="supported_cmdb_services",
    )
    criticality = models.CharField(
        max_length=20, choices=ConfigurationItem.CRITICALITY_CHOICES,
        default="medium",
    )
    availability_target = models.DecimalField(
        max_digits=5, decimal_places=2, default=99.00,
    )
    rto_minutes = models.PositiveIntegerField(default=0)
    rpo_minutes = models.PositiveIntegerField(default=0)
    business_hours = models.CharField(max_length=120, blank=True, default="")
    maintenance_window = models.CharField(max_length=120, blank=True, default="")
    is_customer_facing = models.BooleanField(default=False)
    is_regulated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ServiceConfigurationItemLink(SoftDeleteModel):
    ROLE_CHOICES = [
        ("primary", "Primary"), ("secondary", "Secondary"),
        ("dependency", "Dependency"), ("database", "Database"),
        ("integration", "Integration"), ("other", "Other"),
    ]

    service = models.ForeignKey(
        "services.ServiceCatalogueItem", on_delete=models.CASCADE,
        related_name="cmdb_ci_links",
    )
    configuration_item = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE, related_name="service_links",
    )
    role = models.CharField(
        max_length=30, choices=ROLE_CHOICES, default="dependency",
    )
    criticality = models.CharField(
        max_length=20, choices=ConfigurationItem.CRITICALITY_CHOICES,
        default="medium",
    )
    redundancy_group = models.CharField(max_length=60, blank=True, default="")
    is_required = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service", "configuration_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "configuration_item"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_service_ci_link",
            ),
        ]


class ConfigurationItemTicketLink(SoftDeleteModel):
    RELATION_CHOICES = [
        ("affected", "Affected"), ("caused_by", "Caused By"),
        ("blocks", "Blocks"), ("resolved_by", "Resolved By"),
        ("relates_to", "Relates To"),
    ]

    configuration_item = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE, related_name="ticket_links",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="cmdb_links",
    )
    relation_type = models.CharField(
        max_length=30, choices=RELATION_CHOICES, default="affected",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["configuration_item", "ticket", "relation_type"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_cmdb_ticket_link",
            ),
        ]


class ConfigurationItemChangeLink(SoftDeleteModel):
    IMPACT_CHOICES = [
        ("direct", "Direct"), ("indirect", "Indirect"), ("none", "None"),
    ]
    ROLE_CHOICES = [
        ("affected", "Affected"), ("implements", "Implements"),
        ("validates", "Validates"), ("backout", "Backout"),
    ]

    configuration_item = models.ForeignKey(
        ConfigurationItem, on_delete=models.CASCADE, related_name="change_links",
    )
    change = models.ForeignKey(
        "changes.ChangeRequest", on_delete=models.CASCADE,
        related_name="cmdb_links",
    )
    impact_type = models.CharField(
        max_length=20, choices=IMPACT_CHOICES, default="direct",
    )
    change_role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="affected",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["configuration_item", "change"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_cmdb_change_link",
            ),
        ]


# ---------------------------------------------------------------------------
# Relationship validation helpers (used by serializers and services)
# ---------------------------------------------------------------------------

def inverse_exists(source_ci, target_ci, relationship_type, status="active"):
    """True when the inverse relationship already exists (active, non-deleted)."""
    inverse = INVERSE_REL_TYPES.get(relationship_type)
    if not inverse or inverse == relationship_type:
        if relationship_type == "related_to":
            return ConfigurationItemRelationship.objects.filter(
                source_ci=target_ci, target_ci=source_ci,
                relationship_type="related_to", status=status, is_deleted=False,
            ).exists()
        return False
    return ConfigurationItemRelationship.objects.filter(
        source_ci=target_ci, target_ci=source_ci,
        relationship_type=inverse, status=status, is_deleted=False,
    ).exists()


def would_create_hierarchy_cycle(source_ci, target_ci, relationship_type):
    """Detect structural cycles for hierarchy-invalid relationship types.

    Walks the child -> parent direction through all active hierarchy
    relationships; a cycle exists when walking up from the candidate child
    reaches that child again.
    """
    direction = HIERARCHY_PARENT_DIRECTION.get(relationship_type)
    if not direction:
        return False
    if direction == "target_to_source":
        child, parent = target_ci, source_ci
    else:
        child, parent = source_ci, target_ci
    if child.id == parent.id:
        return True

    hierarchy_types = tuple(HIERARCHY_PARENT_DIRECTION)
    visited = set()
    current = parent.id
    steps = 0
    while current is not None and steps < 500:
        if current == child.id:
            return True
        if current in visited:
            return False
        visited.add(current)
        rels = ConfigurationItemRelationship.objects.filter(
            status="active", is_deleted=False,
            relationship_type__in=hierarchy_types,
        ).filter(
            models.Q(source_ci_id=current) | models.Q(target_ci_id=current),
        ).values_list("source_ci_id", "target_ci_id", "relationship_type")
        nxt = None
        for src_id, tgt_id, rtype in rels:
            if HIERARCHY_PARENT_DIRECTION.get(rtype) == "target_to_source":
                # child=tgt, parent=src: if current is child (tgt), parent is src
                if tgt_id == current:
                    nxt = src_id
                    break
            else:
                # child=src, parent=tgt: if current is child (src), parent is tgt
                if src_id == current:
                    nxt = tgt_id
                    break
        current = nxt
        steps += 1
    return False


def validate_relationship(source_ci, target_ci, relationship_type, status="active"):
    """Full server-side validation for a relationship candidate."""
    if not source_ci or not target_ci:
        raise ValidationError("source_ci and target_ci are required")
    if source_ci.id == target_ci.id:
        raise ValidationError("Self-reference not allowed")
    if relationship_type not in INVERSE_REL_TYPES:
        raise ValidationError("Unknown relationship type")
    if status == "active":
        if inverse_exists(source_ci, target_ci, relationship_type):
            raise ValidationError("Duplicate relationship (inverse already exists)")
        if would_create_hierarchy_cycle(source_ci, target_ci, relationship_type):
            raise ValidationError(
                "Relationship would create a structural cycle"
            )
