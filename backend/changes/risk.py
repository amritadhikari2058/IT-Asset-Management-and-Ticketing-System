"""Deterministic risk scoring service for Change Risk Assessment.

Each factor is scored 1 to 5 and summed to a total score (10 to 50).

Levels:
    10-19: low
    20-29: medium
    30-39: high
    40-50: critical

Factor meanings (higher = riskier):
    service_impact:     1 = minimal service impact, 5 = widespread outage
    user_impact:        1 = few users affected, 5 = org-wide impact
    complexity:         1 = simple/standard, 5 = highly complex/novel
    reversibility:      1 = straightforward rollback, 5 = difficult/impossible
    test_coverage:      1 = comprehensive testing, 5 = untested/unclear
    implementation_experience: 1 = repeated proven procedure, 5 = first-time
    timing_risk:        1 = low-risk window, 5 = peak/business-critical window
    dependency_risk:    1 = no dependencies, 5 = many blocking dependencies
    security_risk:      1 = no security change, 5 = security config change
    data_integrity_risk:1 = no data change, 5 = data migration/loss risk

Validated-system impact (operational classification only, not a compliance claim):
    none / documentation_only / configuration / functional_change /
    data_integrity_impact
"""

from django.conf import settings

FACTOR_MIN = 1
FACTOR_MAX = 5

LEVEL_THRESHOLDS = [
    (19, "low"),
    (29, "medium"),
    (39, "high"),
    (50, "critical"),
]

VALIDATED_SYSTEM_IMPACT_CHOICES = [
    ("none", "None"),
    ("documentation_only", "Documentation Only"),
    ("configuration", "Configuration"),
    ("functional_change", "Functional Change"),
    ("data_integrity_impact", "Data Integrity Impact"),
]

# Factor weightings - all factors weighted equally by default.
FACTOR_WEIGHTS = {
    "service_impact_score": 1,
    "user_impact_score": 1,
    "complexity_score": 1,
    "reversibility_score": 1,
    "test_coverage_score": 1,
    "implementation_experience_score": 1,
    "timing_risk_score": 1,
    "dependency_risk_score": 1,
    "security_risk_score": 1,
    "data_integrity_risk_score": 1,
}

VALIDATED_SYSTEM_RISK_BOOST = {
    "none": 0,
    "documentation_only": 0,
    "configuration": 1,
    "functional_change": 2,
    "data_integrity_impact": 3,
}

# CHANGE_STANDARD_FAILURE_THRESHOLD: consecutive failures within the window
# before a template is suspended.
CHANGE_STANDARD_FAILURE_THRESHOLD = getattr(
    settings, "CHANGE_STANDARD_FAILURE_THRESHOLD", 2
)
CHANGE_STANDARD_FAILURE_WINDOW_DAYS = getattr(
    settings, "CHANGE_STANDARD_FAILURE_WINDOW_DAYS", 90
)


def level_for_score(total_score):
    """Return the risk level label for a total score."""
    if total_score <= LEVEL_THRESHOLDS[0][0]:
        return "low"
    if total_score <= LEVEL_THRESHOLDS[1][0]:
        return "medium"
    if total_score <= LEVEL_THRESHOLDS[2][0]:
        return "high"
    return "critical"


def validate_factor(value, field_name):
    """Validate a single risk factor is an int in [1, 5]."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer between 1 and 5.")
    if value < FACTOR_MIN or value > FACTOR_MAX:
        raise ValueError(f"{field_name} must be between {FACTOR_MIN} and {FACTOR_MAX}.")
    return value


def compute_total_score(factors):
    """Compute the total risk score from a dict of factor scores."""
    total = 0
    for field, weight in FACTOR_WEIGHTS.items():
        total += factors.get(field, 0) * weight
    return total


def compute_level(total_score):
    """Return the calculated risk level for a total score."""
    return level_for_score(total_score)


def assess_risk(factors, override_level=None, override_reason=""):
    """Assess risk from factor scores.

    Returns a dict with factor scores, total_score, calculated_level,
    override_level, override_reason.
    """
    validated = {}
    for field in FACTOR_WEIGHTS:
        validated[field] = validate_factor(factors.get(field, 1), field)

    total_score = compute_total_score(validated)
    calculated_level = compute_level(total_score)

    return {
        "scores": validated,
        "total_score": total_score,
        "calculated_level": calculated_level,
        "override_level": override_level or "",
        "override_reason": override_reason or "",
    }


def validated_system_impact_boost(value):
    """Return the risk boost for a validated-system impact classification."""
    return VALIDATED_SYSTEM_RISK_BOOST.get(value, 0)


def should_suspend_template(failure_count, window_failures):
    """Return True if a template should be suspended given failure counts."""
    return (
        failure_count >= CHANGE_STANDARD_FAILURE_THRESHOLD
        or window_failures >= CHANGE_STANDARD_FAILURE_THRESHOLD
    )
