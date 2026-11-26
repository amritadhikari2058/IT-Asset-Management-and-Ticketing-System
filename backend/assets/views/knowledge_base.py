"""Asset APIs: categories, assets, assignment, history, bulk.

- Ordinary asset updates pop 'assigned_to' (no silent overwrite).
- Assignment changes are explicit + write Assignment + AssetHistory rows.
- Bulk delete = soft delete only, blocked when history exists.
"""
import csv
import io
import logging
from zipfile import BadZipFile

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from openpyxl import load_workbook
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from common.permissions import IsActiveAuthenticated
from rest_framework.response import Response

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance, Vendor,
)
from common.attachment_security import safe_original_filename
from assets import reports
from assets import reports
from assets.serializers import (
    AssetAssignSerializer, AssetAttachmentSerializer,
    AssetCategorySerializer, AssetHistorySerializer, AssetSerializer,
    AssignmentSerializer, DisposalSerializer, MaintenanceSerializer,
    KnowledgeBaseArticleSerializer,
    KnowledgeBaseArticleCreateUpdateSerializer,
    KnowledgeBaseArticleRevisionSerializer,
    KnowledgeBaseCategorySerializer,
    KnowledgeBaseCategoryCreateUpdateSerializer,
    KnowledgeBaseFeedbackSerializer,
    KnowledgeBaseRejectSerializer,
    KnowledgeBaseRestoreSerializer,
    KnowledgeBaseReviewDecisionSerializer,
    KnowledgeBaseSubmitReviewSerializer,
    KnowledgeBaseTagSerializer,
    KnowledgeBaseTagCreateUpdateSerializer,
    VendorSerializer,
)
from assets import kb_services
from assets.models import (KnowledgeBaseArticle, KnowledgeBaseArticleRevision,
                           KnowledgeBaseCategory, KnowledgeBaseTag,
                           KnowledgeBaseFeedback)
from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.serializers import validate_attachment_file

logger = logging.getLogger(__name__)



from .shared import *
from .shared import _can_manage

class KnowledgeBaseConflict(APIException):
    """HTTP 409 for stale article edits / restoration conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This article changed since you loaded it."

    def __init__(self, message=None, article=None):
        detail = {"detail": message or self.default_detail}
        if article is not None:
            detail["current_version"] = article.version
            detail["current_revision_number"] = article.revision_number
        super().__init__(detail=detail)



class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    """CRUD, versioning and review workflow for knowledge-base articles.

    Permissions (backend-enforced):
    - Employees can list/retrieve only PUBLISHED articles. Drafts, pending
      reviews, archived articles and all revision/review endpoints are
      IT-staff only.
    - IT staff (IsITStaff: admin / IT manager / IT support) can create,
      edit, submit for review, approve/reject, publish, archive, inspect
      revision history, compare and restore.
    """
    queryset = KnowledgeBaseArticle.objects.filter(status="published")
    serializer_class = KnowledgeBaseArticleSerializer
    permission_classes = [IsActiveAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsActiveAuthenticated()]
        return [IsITStaff()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return KnowledgeBaseArticleCreateUpdateSerializer
        return KnowledgeBaseArticleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        article = KnowledgeBaseArticle.objects.get(pk=serializer.instance.pk)
        return Response(
            KnowledgeBaseArticleSerializer(article).data,
            status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        article = KnowledgeBaseArticle.objects.get(pk=serializer.instance.pk)
        return Response(KnowledgeBaseArticleSerializer(article).data)

    # ---- queryset / filters ----

    def get_queryset(self):
        user = self.request.user
        if user.is_employee_or_similar():
            qs = KnowledgeBaseArticle.objects.filter(status="published")
        elif _can_manage(user) or user.has_perm("assets.manage_knowledge_base"):
            qs = KnowledgeBaseArticle.objects.all()
        else:
            return KnowledgeBaseArticle.objects.none()

        params = self.request.query_params
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q)
                           | Q(content__icontains=q))
        status_value = params.get("status")
        if status_value:
            qs = qs.filter(status=status_value)
        category = params.get("category")
        if category:
            qs = qs.filter(Q(category_id=category)
                           if str(category).isdigit()
                           else Q(category__code=category))
        tag = params.get("tag")
        if tag:
            qs = qs.filter(tags__slug=tag)

        ordering = params.get("ordering") or "-created_at"
        allowed = {
            "created_at": "created_at", "-created_at": "-created_at",
            "updated_at": "updated_at", "-updated_at": "-updated_at",
            "title": "title", "-title": "-title",
            "status": "status", "-status": "-status",
            "view_count": "view_count", "-view_count": "-view_count",
            "revision_number": "revision_number",
            "-revision_number": "-revision_number",
        }
        qs = qs.order_by(allowed.get(ordering, "-created_at"), "-id")
        return qs.distinct()

    # ---- helpers ----

    def _check_version(self, article, submitted_version):
        """Reject stale writes. Missing version keeps legacy clients working."""
        if submitted_version in (None, ""):
            return
        try:
            submitted = int(submitted_version)
        except (TypeError, ValueError):
            raise ValidationError({"version": "Version must be an integer."})
        if submitted != article.version:
            raise KnowledgeBaseConflict(
                "Another user modified this article after you loaded it. "
                "Reload the latest version before saving.", article=article)

    def _check_status_transition(self, article, new_status):
        old = article.status
        if new_status == old:
            return
        if new_status == "published" and old not in (
                "approved", "published", "archived"):
            raise ValidationError({
                "status": "This article must be reviewed and approved before "
                          "it can be published. Submit it for review first."})
        if new_status == "approved":
            raise ValidationError({
                "status": "Use the approve action so the reviewer, decision "
                          "and comment are recorded."})
        if old == "pending_review" and new_status == "draft":
            raise ValidationError({
                "status": "Use the reject action to return a pending article "
                          "to draft with a review comment."})

    def perform_create(self, serializer):
        with transaction.atomic():
            article = serializer.save(author=self.request.user)
            article.version = 1
            article.revision_number = 0
            article.save(update_fields=["version", "revision_number",
                                        "updated_at"])
            revision = kb_services.create_revision(
                article, self.request.user,
                change_note=(self.request.data.get("change_note")
                             or "Initial version"))
            log_action(actor=self.request.user, action="create",
                       instance=article,
                       details={"revision_number": revision.revision_number,
                                "status": article.status})

    def perform_update(self, serializer):
        with transaction.atomic():
            article = (KnowledgeBaseArticle.objects
                       .select_for_update(of=("self",))
                       .get(pk=serializer.instance.pk))
            self._check_version(article, self.request.data.get("version"))
            before = kb_services.article_snapshot(article)
            old_status = article.status
            new_status = serializer.validated_data.get("status")
            if new_status and new_status != old_status:
                self._check_status_transition(article, new_status)
                if new_status == "pending_review":
                    article.submitted_at = timezone.now()
                    article.review_decision = "pending"
                    article.reviewed_by = None
                    article.reviewed_at = None
                    article.review_comment = ""

            serializer.instance = article
            article = serializer.save()
            changed = kb_services.changed_fields(before, article)
            if changed or article.status != old_status:
                # Content edits and accepted workflow transitions advance the
                # optimistic-concurrency token exactly once.
                article.version += 1
                article.save(update_fields=["version", "updated_at"])
            revision = None
            if changed:
                revision, changed = kb_services.create_revision_if_content_changed(
                    article, self.request.user, before,
                    change_note=self.request.data.get("change_note") or "")
            log_action(
                actor=self.request.user, action="update", instance=article,
                details={
                    "changed_fields": changed,
                    "revision_number": (revision.revision_number
                                        if revision else article.revision_number),
                    "status": article.status,
                    "previous_status": old_status,
                    "version": article.version,
                })

    # ---- revision history ----

    @action(detail=True, methods=["get"])
    def revisions(self, request, pk=None):
        article = self.get_object()
        revisions = article.revisions.select_related("editor", "author").all()
        return Response(
            KnowledgeBaseArticleRevisionSerializer(revisions, many=True).data)

    @action(detail=True, methods=["get"],
            url_path=r"revisions/(?P<revision_number>[0-9]+)")
    def revision_detail(self, request, pk=None, revision_number=None):
        article = self.get_object()
        revision = article.revisions.select_related(
            "editor", "author", "category").filter(
                revision_number=revision_number).first()
        if revision is None:
            raise NotFound("Revision not found for this article.")
        return Response(
            KnowledgeBaseArticleRevisionSerializer(revision).data)

    @action(detail=True, methods=["get"])
    def compare(self, request, pk=None):
        article = self.get_object()
        from_raw = (request.query_params.get("from_revision")
                    or request.query_params.get("from")
                    or request.query_params.get("older"))
        to_raw = (request.query_params.get("to_revision")
                  or request.query_params.get("to")
                  or request.query_params.get("newer"))
        if not from_raw or not to_raw:
            raise ValidationError({
                "detail": "Provide from_revision and to_revision."})
        try:
            from_number, to_number = int(from_raw), int(to_raw)
        except (TypeError, ValueError):
            raise ValidationError({
                "detail": "Revision numbers must be integers."})
        revisions = {
            rev.revision_number: rev
            for rev in article.revisions.filter(
                revision_number__in={from_number, to_number})
        }
        missing = [n for n in (from_number, to_number) if n not in revisions]
        if missing:
            raise NotFound(
                f"Revision(s) not found for this article: {missing}.")
        older_number, newer_number = sorted((from_number, to_number))
        older, newer = revisions[older_number], revisions[newer_number]
        serializer = KnowledgeBaseArticleRevisionSerializer
        return Response({
            "article": {
                "id": article.id,
                "title": article.title,
                "status": article.status,
                "version": article.version,
                "revision_number": article.revision_number,
            },
            "from_revision": from_number,
            "to_revision": to_number,
            "older": serializer(older).data,
            "newer": serializer(newer).data,
            "from": serializer(older).data,
            "to": serializer(newer).data,
            "fields": kb_services.revision_changes(older, newer),
        })

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        input_serializer = KnowledgeBaseRestoreSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article,
                                input_serializer.validated_data.get("version"))
            revision = article.revisions.filter(
                revision_number=input_serializer.validated_data[
                    "revision_number"]).first()
            if revision is None:
                raise NotFound("Revision not found for this article.")
            try:
                new_revision = kb_services.apply_revision(
                    article, revision, request.user)
            except IntegrityError:
                raise KnowledgeBaseConflict(
                    "The restored slug is already used by another article. "
                    "Rename the current article or choose another revision.",
                    article=article)
        article.refresh_from_db()
        return Response({
            "article": KnowledgeBaseArticleSerializer(article).data,
            "revision": KnowledgeBaseArticleRevisionSerializer(
                new_revision).data,
        })

    # ---- review workflow ----

    @action(detail=True, methods=["post"])
    def submit_review(self, request, pk=None):
        input_serializer = KnowledgeBaseSubmitReviewSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article,
                                input_serializer.validated_data.get("version"))
            if article.status not in ("draft", "archived", "pending_review"):
                raise ValidationError({
                    "detail": f"A {article.status} article cannot be submitted "
                              "for review."})
            previous = article.status
            article.status = "pending_review"
            article.submitted_at = timezone.now()
            article.review_decision = "pending"
            article.reviewed_by = None
            article.reviewed_at = None
            article.review_comment = ""
            article.version += 1
            article.save(update_fields=[
                "status", "submitted_at", "review_decision", "reviewed_by",
                "reviewed_at", "review_comment", "version", "updated_at"])
            log_action(actor=request.user, action="status_change",
                       instance=article,
                       details={"action": "submit_review",
                                "from": previous, "to": article.status,
                                "note": input_serializer.validated_data.get(
                                    "note", "")})
            # Notify IT staff only on a real transition into pending_review
            # (not on a repeated/idempotent re-submission), after commit so a
            # rollback never produces a notification.
            note = input_serializer.validated_data.get("note", "")
            if previous != "pending_review":
                transaction.on_commit(
                    lambda a=article, u=request.user, n=note:
                    kb_services.notify_submitted_for_review(a, u, n))
        article.refresh_from_db()
        return Response(KnowledgeBaseArticleSerializer(article).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        input_serializer = KnowledgeBaseReviewDecisionSerializer(
            data=request.data)
        input_serializer.is_valid(raise_exception=True)
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article,
                                input_serializer.validated_data.get("version"))
            if article.status != "pending_review":
                raise ValidationError({
                    "detail": "Only articles pending review can be approved."})
            if article.author_id == request.user.pk:
                raise PermissionDenied(
                    "Authors cannot approve their own articles.")
            article.status = "approved"
            article.review_decision = "approved"
            article.reviewed_by = request.user
            article.reviewed_at = timezone.now()
            article.review_comment = input_serializer.validated_data.get(
                "comment", "") or ""
            article.version += 1
            article.save(update_fields=[
                "status", "review_decision", "reviewed_by", "reviewed_at",
                "review_comment", "version", "updated_at"])
            log_action(actor=request.user, action="status_change",
                       instance=article,
                       details={"action": "approve",
                                "to": article.status,
                                "comment": article.review_comment})
            # Notify the author: in-app + outbox. The outbox event is
            # registered inside this atomic block, so it commits or rolls
            # back with the business change.  The on_commit wake-up is
            # kept only as a best-effort low-latency hint; correctness
            # does not depend on it (the periodic scanner re-discovers).
            kb_services.notify_article_approved(
                article, request.user, request.user,
                article.review_comment)
        article.refresh_from_db()
        return Response(KnowledgeBaseArticleSerializer(article).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        input_serializer = KnowledgeBaseRejectSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article,
                                input_serializer.validated_data.get("version"))
            if article.status != "pending_review":
                raise ValidationError({
                    "detail": "Only articles pending review can be rejected."})
            if article.author_id == request.user.pk:
                raise PermissionDenied(
                    "Authors cannot review their own articles.")
            article.status = "draft"
            article.review_decision = "rejected"
            article.reviewed_by = request.user
            article.reviewed_at = timezone.now()
            article.review_comment = input_serializer.validated_data["comment"]
            article.version += 1
            article.save(update_fields=[
                "status", "review_decision", "reviewed_by", "reviewed_at",
                "review_comment", "version", "updated_at"])
            log_action(actor=request.user, action="status_change",
                       instance=article,
                       details={"action": "reject",
                                "to": article.status,
                                "comment": article.review_comment})
            # Notify the author (with the rejection reason): in-app + outbox.
            # The outbox event is registered inside this atomic block, so it
            # commits or rolls back with the business change.
            kb_services.notify_article_rejected(
                article, request.user, request.user,
                article.review_comment)
        article.refresh_from_db()
        return Response(KnowledgeBaseArticleSerializer(article).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article, request.data.get("version"))
            if article.status not in ("approved", "archived", "published"):
                raise ValidationError({
                    "detail": "This article must be approved before it can be "
                              "published."})
            previous = article.status
            article.status = "published"
            article.version += 1
            article.save(update_fields=["status", "version", "updated_at"])
            log_action(actor=request.user, action="status_change",
                       instance=article,
                       details={"action": "publish", "from": previous,
                                "to": article.status})
            # Notify the author on a real transition to published (not on the
            # idempotent already-published case): in-app + outbox.
            # The outbox event is registered inside this atomic block, so it
            # commits or rolls back with the business change.
            if previous != "published":
                kb_services.notify_article_published(article, request.user)
        article.refresh_from_db()
        return Response(KnowledgeBaseArticleSerializer(article).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        article = self.get_object()
        with transaction.atomic():
            article = KnowledgeBaseArticle.objects.select_for_update().get(
                pk=article.pk)
            self._check_version(article, request.data.get("version"))
            if article.status == "archived":
                return Response(
                    KnowledgeBaseArticleSerializer(article).data)
            previous = article.status
            article.status = "archived"
            article.version += 1
            article.save(update_fields=["status", "version", "updated_at"])
            log_action(actor=request.user, action="status_change",
                       instance=article,
                       details={"action": "archive", "from": previous,
                                "to": article.status})
        article.refresh_from_db()
        return Response(KnowledgeBaseArticleSerializer(article).data)

    @action(detail=False, methods=["get"])
    def pending_review(self, request):
        articles = KnowledgeBaseArticle.objects.filter(
            status="pending_review").select_related(
                "category", "author", "reviewed_by").order_by(
                    "submitted_at", "created_at")
        return Response(
            KnowledgeBaseArticleSerializer(articles, many=True).data)



class KnowledgeBaseCategoryViewSet(viewsets.ModelViewSet):
    """Managed KB category dropdown source (IT staff write, auth read)."""

    queryset = KnowledgeBaseCategory.objects.all()
    serializer_class = KnowledgeBaseCategorySerializer
    permission_classes = [IsActiveAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsActiveAuthenticated()]
        return [IsITStaff()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return KnowledgeBaseCategoryCreateUpdateSerializer
        return KnowledgeBaseCategorySerializer

    def perform_create(self, serializer):
        category = serializer.save(created_by=self.request.user)
        log_action(actor=self.request.user, action="create", instance=category)

    def perform_update(self, serializer):
        category = serializer.save()
        log_action(actor=self.request.user, action="update", instance=category)



class KnowledgeBaseTagViewSet(viewsets.ModelViewSet):
    """Managed KB tag list (IT staff write, authenticated read)."""

    queryset = KnowledgeBaseTag.objects.all()
    serializer_class = KnowledgeBaseTagSerializer
    permission_classes = [IsActiveAuthenticated]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsActiveAuthenticated()]
        return [IsITStaff()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return KnowledgeBaseTagCreateUpdateSerializer
        return KnowledgeBaseTagSerializer

    @action(detail=False, methods=["get"])
    def usefulness(self, request):
        """Knowledge Base usefulness dashboard (IT staff only).

        Returns aggregate stats plus per-article feedback rates so IT staff
        can identify articles that need improvement.
        """
        from rest_framework.exceptions import PermissionDenied

        if not (request.user.is_staff
                or request.user.has_perm("assets.manage_knowledge_base")
                or getattr(request.user, "role", "") == "system_admin"):
            raise PermissionDenied("IT staff only.")

        from django.db.models import Avg, Count, F, Q
        from django.utils import timezone

        articles = KnowledgeBaseArticle.objects.filter(
            status="published").select_related("category")
        q = request.query_params.get("q", "").strip()
        if q:
            articles = articles.filter(
                Q(title__icontains=q) | Q(content__icontains=q))
        category = request.query_params.get("category")
        if category:
            articles = articles.filter(category_id=category)
        date_from = request.query_params.get("date_from")
        if date_from:
            articles = articles.filter(created_at__date__gte=date_from)

        total_articles = articles.count()
        total_feedback = KnowledgeBaseFeedback.objects.filter(
            is_deleted=False, article__status="published").count()
        helpful_votes = KnowledgeBaseFeedback.objects.filter(
            is_deleted=False, article__status="published", helpful=True).count()
        not_helpful_votes = total_feedback - helpful_votes

        # Per-article stats.
        article_stats = []
        for a in articles.prefetch_related("feedback").order_by("-created_at"):
            fb = [f for f in a.feedback.all() if not f.is_deleted]
            n_helpful = sum(1 for f in fb if f.helpful)
            n_not_helpful = len(fb) - n_helpful
            n_total = len(fb)
            rate = round(n_helpful / n_total * 100, 1) if n_total else None
            article_stats.append({
                "id": a.id,
                "title": a.title,
                "slug": a.slug,
                "category": a.category.name if a.category_id else None,
                "views": a.view_count,
                "feedback_count": n_total,
                "helpful": n_helpful,
                "not_helpful": n_not_helpful,
                "helpful_rate": rate,
            })

        # Sort: articles with low feedback rate first (ineffective), then no
        # feedback, then by most feedback.
        def _sort_key(s):
            rate = s["helpful_rate"]
            if rate is None:
                return (2, 0)  # no feedback
            return (0, rate)  # low rate first

        article_stats.sort(key=_sort_key)

        return Response({
            "total_articles": total_articles,
            "total_feedback": total_feedback,
            "helpful_votes": helpful_votes,
            "not_helpful_votes": not_helpful_votes,
            "overall_helpful_rate": (
                round(helpful_votes / total_feedback * 100, 1)
                if total_feedback else None),
            "articles": article_stats,
        })



class KnowledgeBaseFeedbackViewSet(viewsets.ModelViewSet):
    """Employee usefulness feedback for published KB articles.

    Permissions:
    - Any authenticated user can create/update their own feedback on a
      published article (one row per article+user).
    - IT staff can see all feedback (stats / ineffective-article detection).
    """
    serializer_class = KnowledgeBaseFeedbackSerializer
    permission_classes = [IsActiveAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, "role", "") in ("system_admin", "it_manager",
                                         "it_support"):
            return KnowledgeBaseFeedback.objects.all()
        return KnowledgeBaseFeedback.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)


