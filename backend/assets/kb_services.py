"""Knowledge Base revision, comparison, restore and review helpers.

All revision writes live here so article updates and their snapshot always
share one database transaction (callers use ``transaction.atomic`` and lock
the article row). Revisions are append-only: this module never updates or
deletes an existing ``KnowledgeBaseArticleRevision`` row.
"""
import difflib
import re

from django.db import models
from django.db.models import Max

from accounts import email_utils
from assets.models import KnowledgeBaseArticle, KnowledgeBaseArticleRevision
from common.audit import log_action
from common.models import Notification

# Fields whose change creates a new content revision. Status-only workflow
# transitions bump ``version`` but deliberately do not add revision noise.
CONTENT_FIELDS = ("title", "slug", "summary", "content", "category_id")


def user_label(user):
    if not user:
        return ""
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return name or getattr(user, "email", "") or getattr(user, "username", "")


def tags_snapshot(article):
    """Denormalised tag list that survives tag deletion."""
    return [
        {"name": tag.name, "slug": tag.slug}
        for tag in article.tags.all().order_by("name")
    ]


def article_snapshot(article):
    """Comparable snapshot of the revision-tracked article state."""
    return {
        "title": article.title,
        "slug": article.slug,
        "summary": article.summary or "",
        "content": article.content or "",
        "category_id": article.category_id,
        "tags": tags_snapshot(article),
    }


def changed_fields(before, article):
    after = article_snapshot(article)
    changed = []
    for field in CONTENT_FIELDS:
        if before.get(field) != after.get(field):
            changed.append(field.replace("_id", ""))
    if before.get("tags") != after.get("tags"):
        changed.append("tags")
    return changed


def create_revision(article, editor, change_note="", restored_from_revision=None):
    """Append the next immutable revision for ``article``.

    Creates the snapshot row and updates ``article.revision_number``. The
    caller owns the transaction and the optimistic-concurrency ``version``
    bump, so revision rows and the article row commit or roll back together.
    """
    current_max = (
        KnowledgeBaseArticleRevision.objects
        .filter(article=article)
        .aggregate(max_number=Max("revision_number"))
        .get("max_number") or 0
    )
    number = max(current_max, article.revision_number) + 1
    revision = KnowledgeBaseArticleRevision.objects.create(
        article=article,
        revision_number=number,
        title=article.title,
        slug=article.slug,
        summary=article.summary or "",
        content=article.content or "",
        category=article.category,
        category_name=article.category.name if article.category_id else "",
        tags=tags_snapshot(article),
        status=article.status,
        author=article.author,
        editor=editor,
        editor_name=user_label(editor),
        change_note=change_note or "",
        restored_from_revision=restored_from_revision,
    )
    article.revision_number = number
    KnowledgeBaseArticle.objects.filter(pk=article.pk).update(
        revision_number=number)
    log_action(
        actor=editor,
        action="create",
        instance=revision,
        details={
            "article_id": article.pk,
            "revision_number": number,
            "restored_from_revision": restored_from_revision,
        },
    )
    return revision


def create_revision_if_content_changed(article, editor, before, change_note=""):
    """Create a revision only when tracked content/metadata actually changed.

    Returns ``(revision_or_None, changed_fields)``. An unchanged PATCH still
    bumps nothing and leaves revision history untouched.
    """
    changed = changed_fields(before, article)
    if not changed:
        return None, []
    note = change_note or f"Updated {', '.join(changed)}"
    return create_revision(article, editor, change_note=note), changed


def apply_revision(article, revision, editor):
    """Restore a revision's content as a NEW revision.

    Existing revisions are never removed or rewritten. The article's current
    workflow status is preserved: restoration changes content, not the
    publication decision. ``article`` must already be locked by the caller.
    """
    from assets.models import KnowledgeBaseTag

    article.title = revision.title
    article.slug = revision.slug
    article.summary = revision.summary
    article.content = revision.content
    article.category_id = revision.category_id
    article.save()

    tag_objects = []
    for item in revision.tags or []:
        slug = item.get("slug") or ""
        if not slug:
            continue
        tag, _created = KnowledgeBaseTag.objects.get_or_create(
            slug=slug, defaults={"name": item.get("name") or slug})
        tag_objects.append(tag)
    article.tags.set(tag_objects)

    article.version += 1
    article.save(update_fields=["version", "updated_at"])
    new_revision = create_revision(
        article,
        editor,
        change_note=f"Restored from revision {revision.revision_number}",
        restored_from_revision=revision.revision_number,
    )
    log_action(
        actor=editor,
        action="update",
        instance=article,
        details={
            "action": "restore_revision",
            "source_revision": revision.revision_number,
            "new_revision": new_revision.revision_number,
        },
    )
    return new_revision


def _text_parts(old, new):
    """Word-level diff parts for short fields (title / summary)."""
    old_tokens = re.findall(r"\S+\s*", old or "")
    new_tokens = re.findall(r"\S+\s*", new or "")
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append({"type": "same", "text": "".join(old_tokens[i1:i2])})
        else:
            if i2 > i1:
                parts.append({"type": "removed",
                              "text": "".join(old_tokens[i1:i2])})
            if j2 > j1:
                parts.append({"type": "added",
                              "text": "".join(new_tokens[j1:j2])})
    if not parts:
        parts = [{"type": "same", "text": ""}]
    return parts


def _line_diff(old, new):
    """Readable line diff for the article body."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    rows = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                rows.append({"type": "same", "text": line})
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                rows.append({"type": "removed", "text": line})
            for line in new_lines[j1:j2]:
                rows.append({"type": "added", "text": line})
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                rows.append({"type": "removed", "text": line})
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                rows.append({"type": "added", "text": line})
    if not rows:
        rows = [{"type": "same", "text": ""}]
    return rows


def revision_changes(old_rev, new_rev):
    """Structured, human-readable comparison of two revision snapshots."""
    title_changed = old_rev.title != new_rev.title
    summary_changed = (old_rev.summary or "") != (new_rev.summary or "")
    content_changed = (old_rev.content or "") != (new_rev.content or "")
    old_tags = [t.get("name", "") for t in (old_rev.tags or [])]
    new_tags = [t.get("name", "") for t in (new_rev.tags or [])]
    return {
        "title": {
            "changed": title_changed,
            "old": old_rev.title,
            "new": new_rev.title,
            "parts": _text_parts(old_rev.title, new_rev.title),
        },
        "summary": {
            "changed": summary_changed,
            "old": old_rev.summary or "",
            "new": new_rev.summary or "",
            "parts": _text_parts(old_rev.summary or "", new_rev.summary or ""),
        },
        "content": {
            "changed": content_changed,
            "old": old_rev.content or "",
            "new": new_rev.content or "",
            "lines": _line_diff(old_rev.content, new_rev.content),
        },
        "category": {
            "changed": (old_rev.category_name or "") != (new_rev.category_name or ""),
            "old": old_rev.category_name or "",
            "new": new_rev.category_name or "",
        },
        "tags": {
            "changed": old_tags != new_tags,
            "old": old_tags,
            "new": new_tags,
        },
        "status": {
            "changed": (old_rev.status or "") != (new_rev.status or ""),
            "old": old_rev.status or "",
            "new": new_rev.status or "",
        },
    }


# ---------------------------------------------------------------------------
# Knowledge Base workflow notifications (in-app + preference-gated email).
#
# In-app Notification rows are always delivered (project policy: in-app
# notifications are independent of email preferences). Email is best-effort
# and gated by the ``kb_review`` category preference via
# ``accounts.email_utils.send_kb_notification``. All helpers are designed to
# be called from ``transaction.on_commit()`` so a rolled-back transaction
# never produces a notification.
# ---------------------------------------------------------------------------

def _active_it_staff():
    """Active, non-deleted IT staff / admins eligible to review KB articles."""
    from accounts.models import User
    return User.objects.filter(
        models.Q(role__in=("system_admin", "it_manager", "it_support"))
        | models.Q(is_superuser=True),
        is_active=True,
        is_deleted=False,
    )


def _kb_notify(recipient, actor, title, body, article):
    """Create an in-app KB notification.

    Never notifies the actor of their own action, never inactive/deleted
    recipients. Mirrors the ticket in-app notification convention.
    """
    if recipient is None or not getattr(recipient, "pk", None):
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    return Notification.objects.create(
        recipient=recipient, title=title[:255], body=body or "",
        entity_type="assets.KnowledgeBaseArticle", object_id=str(article.pk))


def notify_submitted_for_review(article, actor, note=""):
    """Notify IT staff that an article was submitted for review.

    Only fired on a real transition into ``pending_review`` (caller gates
    on status change) so repeated submissions do not spam reviewers.
    """
    title = f"KB article submitted for review: {article.title}"
    body = (
        f"'{article.title}' (revision {article.revision_number}) was "
        f"submitted for review by {user_label(actor)}. "
        f"Review it in the Knowledge Base."
    )
    if note.strip():
        body += f"\nNote: {note.strip()}"
    for recipient in _active_it_staff():
        _kb_notify(recipient, actor, title, body, article)


def notify_article_approved(article, actor, reviewer, comment=""):
    """Notify the article author that their article was approved."""
    title = f"KB article approved: {article.title}"
    body = f"'{article.title}' was approved by {user_label(reviewer)}."
    if comment.strip():
        body += f"\nComment: {comment.strip()}"
    if article.author:
        _kb_notify(article.author, actor, title, body, article)
        if article.author.email:
            email_utils.send_kb_notification(
                article.author.email, title, body,
                article=article, user=article.author)


def notify_article_rejected(article, actor, reviewer, comment):
    """Notify the article author that their article was rejected (with reason)."""
    title = f"KB article rejected: {article.title}"
    body = (
        f"'{article.title}' was rejected by {user_label(reviewer)} and "
        f"returned to draft.\nReason: {comment}"
    )
    if article.author:
        _kb_notify(article.author, actor, title, body, article)
        if article.author.email:
            email_utils.send_kb_notification(
                article.author.email, title, body,
                article=article, user=article.author)


def notify_article_published(article, actor):
    """Notify the article author that their article was published."""
    title = f"KB article published: {article.title}"
    body = f"'{article.title}' (revision {article.revision_number}) is now published."
    if article.author:
        _kb_notify(article.author, actor, title, body, article)
        if article.author.email:
            email_utils.send_kb_notification(
                article.author.email, title, body,
                article=article, user=article.author)
