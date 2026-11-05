"""Advisory duplicate-ticket detection using deterministic signals.

No AI/embeddings. Deterministic, explainable, bounded.
"""
import re
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from tickets.models import Ticket

# Score weights (configurable via settings).
WEIGHT_SAME_ASSET = 35
WEIGHT_SAME_REQUESTER = 20
WEIGHT_SAME_CATEGORY = 15
WEIGHT_TITLE_OVERLAP_MAX = 20
WEIGHT_SAME_DEPARTMENT = 5
WEIGHT_RECENT_48H = 5

DEFAULT_THRESHOLD = 50
DEFAULT_WINDOW_DAYS = 30
MAX_CANDIDATES = 20


def _tokens(text):
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if len(t) >= 3}


def find_duplicates(validated_data, actor):
    title = validated_data.get("title", "") or ""
    description = validated_data.get("description", "") or ""
    category = validated_data.get("category")
    department = validated_data.get("department")
    requester = validated_data.get("requester")
    related_asset = validated_data.get("asset")

    threshold = int(getattr(settings, "TICKET_DUPLICATE_SCORE_THRESHOLD",
                            DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
    window_days = int(getattr(settings, "TICKET_DUPLICATE_WINDOW_DAYS",
                              DEFAULT_WINDOW_DAYS) or DEFAULT_WINDOW_DAYS)
    max_candidates = min(
        int(getattr(settings, "TICKET_DUPLICATE_MAX_CANDIDATES", MAX_CANDIDATES)
            or MAX_CANDIDATES), 100)

    now = timezone.now()
    window_start = now - timedelta(days=window_days)

    title_tokens = _tokens(title)
    desc_tokens = _tokens(description)

    qs = Ticket.objects.filter(is_deleted=False)
    # Bounded recent search window.
    qs = qs.filter(created_at__gte=window_start)
    # Exclude tickets the actor cannot see (no hidden ticket leakage).
    from tickets.views import _ticket_visible_qs
    qs = _ticket_visible_qs(actor).filter(pk__in=qs.values("pk"))

    candidates = []
    for t in qs.select_related("category", "department", "asset", "requester")[:500]:
        score = 0
        reasons = []
        if related_asset and t.asset_id and t.asset_id == related_asset.pk:
            score += WEIGHT_SAME_ASSET
            reasons.append("same_asset")
        if requester and t.requester_id and t.requester_id == requester.pk:
            score += WEIGHT_SAME_REQUESTER
            reasons.append("same_requester")
        if category and t.category_id and t.category_id == category.pk:
            score += WEIGHT_SAME_CATEGORY
            reasons.append("same_category")
        if department and t.department_id and t.department_id == department.pk:
            score += WEIGHT_SAME_DEPARTMENT
            reasons.append("same_department")
        if title_tokens:
            overlap = len(title_tokens & _tokens(t.title or ""))
            overlap_score = min(WEIGHT_TITLE_OVERLAP_MAX,
                                overlap * (WEIGHT_TITLE_OVERLAP_MAX // 4))
            if overlap_score:
                score += overlap_score
                reasons.append("title_overlap")
        if t.created_at >= window_start - timedelta(hours=48):
            score += WEIGHT_RECENT_48H
            reasons.append("recent_48h")
        if score >= threshold:
            candidates.append({
                "ticket_id": t.pk,
                "ticket_number": str(t.pk),
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at,
                "score": score,
                "reason_summary": ", ".join(reasons),
                "may_view": True,
            })
    candidates.sort(key=lambda c: (-c["score"], c["created_at"]))
    return candidates[:max_candidates]
