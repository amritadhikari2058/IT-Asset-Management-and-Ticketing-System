"""Transactional ticket merge service.

Preserves notes, attachments, watchers, KB links and related-ticket links.
No data is hard-deleted. The duplicate ticket becomes status ``merged`` with a
reference to the primary ticket.
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from common.audit import log_action
from tickets.models import (
    Ticket, TicketHistory, TicketNote, TicketAttachment, TicketKbArticle,
    TicketRelation, TicketWatcher, TicketMergeRecord, TicketSlaPause,
)

MERGEABLE_STATUSES = {"open", "in_progress", "waiting_requester",
                      "waiting_third_party", "resolved", "closed"}


class MergeError(Exception):
    pass


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager")
             or getattr(user, "is_superuser", False))
    )


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note or "")

def merge_tickets(primary_ticket, duplicate_ticket, actor, reason, options=None):
    """Merge duplicate_ticket into primary_ticket atomically.

    Options (all booleans, defaults preserve data):
      copy_requester_visible_notes, copy_internal_notes, copy_attachments,
      transfer_watchers, transfer_kb_links, transfer_related_links,
      preserve_assignee, preserve_higher_priority, preserve_earliest_sla
    """
    if not _is_it_staff(actor):
        raise MergeError("Only IT Manager / System Admin may execute a merge.")
    from tickets.views import _ticket_visible_qs
    visible = _ticket_visible_qs(actor)
    if not visible.filter(pk=primary_ticket.pk, is_deleted=False).exists() or not visible.filter(pk=duplicate_ticket.pk, is_deleted=False).exists():
        raise MergeError("Primary or duplicate ticket not found.")
    options = options or {}

    if primary_ticket.pk == duplicate_ticket.pk:
        raise MergeError("Primary and duplicate cannot be the same ticket.")

    # Stable lock ordering by ID to avoid deadlocks.
    first, second = (primary_ticket, duplicate_ticket) if primary_ticket.pk < duplicate_ticket.pk else (duplicate_ticket, primary_ticket)

    with transaction.atomic():
        primary = Ticket.objects.select_for_update().get(pk=primary_ticket.pk)
        duplicate = Ticket.objects.select_for_update().get(pk=duplicate_ticket.pk)

        if duplicate.status == "merged":
            raise MergeError("Duplicate ticket is already merged.")
        if primary.status == "merged":
            raise MergeError("Primary ticket is already merged and cannot receive a merge.")
        if duplicate.merge_records_as_merged.filter(is_deleted=False).exists():
            raise MergeError("Duplicate ticket has already been merged once.")
        if duplicate.status not in MERGEABLE_STATUSES:
            raise MergeError(f"Duplicate ticket status '{duplicate.status}' cannot be merged.")
        if primary.status not in MERGEABLE_STATUSES:
            raise MergeError(f"Primary ticket status '{primary.status}' cannot receive a merge.")

        # Idempotency: an existing merge record for this pair blocks re-merge.
        if TicketMergeRecord.objects.filter(
                primary_ticket=primary, merged_ticket=duplicate,
                is_deleted=False).exists():
            raise MergeError("This merge has already been recorded.")

        previous_duplicate_status = duplicate.status
        previous_primary_status = primary.status

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        primary_prio_rank = priority_order.get(primary.priority, 9)
        duplicate_prio_rank = priority_order.get(duplicate.priority, 9)
        if options.get("preserve_higher_priority", True) and duplicate_prio_rank < primary_prio_rank:
            old_priority = primary.priority
            primary.priority = duplicate.priority
        else:
            old_priority = primary.priority

        old_sla_due = primary.sla_due_at
        if options.get("preserve_earliest_sla", True):
            if duplicate.sla_due_at and (
                    not primary.sla_due_at or duplicate.sla_due_at < primary.sla_due_at):
                primary.sla_due_at = duplicate.sla_due_at

        old_assignee = primary.assignee_id
        if options.get("preserve_assignee", True) and primary.assignee_id is None and duplicate.assignee_id:
            primary.assignee = duplicate.assignee

        primary.version = (primary.version or 1) + 1
        primary.save(update_fields=["priority", "sla_due_at", "assignee",
                                    "version", "updated_at"])

        notes_copied = 0
        if options.get("copy_requester_visible_notes", True) or options.get("copy_internal_notes", True):
            source_notes = TicketNote.objects.filter(
                ticket=duplicate, is_deleted=False)
            for note in source_notes:
                if note.is_internal and not options.get("copy_internal_notes", True):
                    continue
                if not note.is_internal and not options.get("copy_requester_visible_notes", True):
                    continue
                TicketNote.objects.create(
                    ticket=primary, author=note.author, body=note.body,
                    is_internal=note.is_internal)
                notes_copied += 1

        attachments_copied = 0
        if options.get("copy_attachments", True):
            for att in TicketAttachment.objects.filter(
                    ticket=duplicate, is_deleted=False):
                att.ticket = primary
                att.save(update_fields=["ticket", "updated_at"])
                attachments_copied += 1

        watchers_transferred = 0
        if options.get("transfer_watchers", True):
            for w in TicketWatcher.objects.filter(
                    ticket=duplicate, is_active=True, is_deleted=False):
                _, created = TicketWatcher.objects.update_or_create(
                    ticket=primary, user=w.user,
                    defaults={"watch_type": w.watch_type, "added_by": actor,
                              "is_active": True, "muted_until": w.muted_until})
                if created:
                    watchers_transferred += 1

        kb_transferred = 0
        if options.get("transfer_kb_links", True):
            for link in TicketKbArticle.objects.filter(
                    ticket=duplicate, is_deleted=False):
                TicketKbArticle.objects.update_or_create(
                    ticket=primary, article=link.article,
                    defaults={"helpful": link.helpful, "linked_by": link.linked_by})
                kb_transferred += 1

        relations_transferred = 0
        if options.get("transfer_related_links", True):
            for rel in TicketRelation.objects.filter(
                    source_ticket=duplicate, is_deleted=False):
                TicketRelation.objects.update_or_create(
                    source_ticket=primary, target_ticket=rel.target_ticket,
                    relation_type=rel.relation_type,
                    defaults={"created_by": actor, "notes": rel.notes})
                relations_transferred += 1
            for rel in TicketRelation.objects.filter(
                    target_ticket=duplicate, is_deleted=False):
                TicketRelation.objects.update_or_create(
                    source_ticket=rel.source_ticket, target_ticket=primary,
                    relation_type=rel.relation_type,
                    defaults={"created_by": actor, "notes": rel.notes})
                relations_transferred += 1

        duplicate.status = "merged"
        duplicate.merged_into = primary
        duplicate.version = (duplicate.version or 1) + 1
        duplicate.save(update_fields=["status", "merged_into", "version", "updated_at"])

        TicketSlaPause.objects.filter(
            ticket=duplicate, ended_at__isnull=True, is_deleted=False).update(
            ended_at=timezone.now(), ended_by=actor)

        merge_record = TicketMergeRecord.objects.create(
            primary_ticket=primary, merged_ticket=duplicate, merged_by=actor,
            reason=reason,
            merge_summary=(
                f"Merged #{duplicate.pk} into #{primary.pk}. "
                f"Priority preserved: {primary.priority}. "
                f"SLA due: {primary.sla_due_at}."),
            transferred_notes_count=notes_copied,
            transferred_attachments_count=attachments_copied,
            transferred_watchers_count=watchers_transferred,
            previous_status=previous_duplicate_status,
        )

        _write_history(primary, actor, "merged_into",
                       old={"status": previous_primary_status,
                            "priority": old_priority,
                            "sla_due_at": str(old_sla_due)},
                       new={"status": primary.status,
                            "priority": primary.priority,
                            "sla_due_at": str(primary.sla_due_at),
                            "merged_duplicate": duplicate.pk},
                       note=reason)
        _write_history(duplicate, actor, "merged",
                       old={"status": previous_duplicate_status},
                       new={"status": "merged", "merged_into": primary.pk},
                       note=reason)

        log_action(actor=actor, action="merge", instance=primary,
                   details={"merged_ticket": duplicate.pk, "reason": reason,
                            "record": merge_record.pk})

    return primary, duplicate, merge_record

