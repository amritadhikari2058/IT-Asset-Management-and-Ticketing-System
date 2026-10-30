p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py"
src = open(p, encoding="utf-8").read()

old = '''    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Explicit assignment change (recorded in history)."""
        obj = self.get_object()
        ser = AssetAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from accounts.models import User
        target_id = ser.validated_data.get("assigned_to")
        target = User.objects.filter(pk=target_id).first() if target_id else None
        old = {"assigned_to": obj.assigned_to_id, "status": obj.status}
        with transaction.atomic():
            # Record the open assignment first so the asset'"'"'s clean()
            # (status == assigned requires a holder + open assignment) passes
            # when we flip the asset below.
            assignment = Assignment.objects.create(
                asset=obj, assigned_to=target,
                assigned_by=request.user,
                note=ser.validated_data.get("note", ""))
            obj.assigned_to = target
            obj.status = "assigned" if target else "available"
            obj.save(update_fields=["assigned_to", "status"])
            _history(obj, request.user, "assigned", old=old,
                     new={"assigned_to": target_id, "status": obj.status,
                          "assignment_id": assignment.pk},
                     note=ser.validated_data.get("note", ""))
            _notify_assignee(target, request.user,
                             f"Asset {obj.asset_tag} assigned to you",
                             f"{obj.name}", obj)
            log_action(actor=request.user, action="assignment", instance=obj,
                       details={"assigned_to": target_id})
        return Response(AssetSerializer(obj).data)
'''

new = '''    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Explicit assignment change (recorded in history)."""
        obj = self.get_object()
        ser = AssetAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import IntegrityError as DjangoIntegrityError
        from django.utils import timezone
        from accounts.models import User
        target_id = ser.validated_data.get("assigned_to")
        target = User.objects.filter(pk=target_id).first() if target_id else None
        old = {"assigned_to": obj.assigned_to_id, "status": obj.status}
        assignment = None
        try:
            with transaction.atomic():
                if target:
                    # Record the open assignment first so the asset'"'"'s clean()
                    # (status == assigned requires a holder + open assignment)
                    # passes when we flip the asset below.
                    assignment = Assignment.objects.create(
                        asset=obj, assigned_to=target,
                        assigned_by=request.user,
                        note=ser.validated_data.get("note", ""))
                    obj.assigned_to = target
                    obj.status = "assigned"
                else:
                    # Unassign: close any open assignment, clear the holder.
                    for open_a in obj.assignments.filter(
                            returned_at__isnull=True):
                        open_a.returned_at = timezone.now()
                        open_a.save(update_fields=["returned_at"])
                    obj.assigned_to = None
                    obj.status = "available"
                obj.save(update_fields=["assigned_to", "status"])
                _history(obj, request.user, "assigned", old=old,
                         new={"assigned_to": obj.assigned_to_id,
                              "status": obj.status,
                              **({"assignment_id": assignment.pk}
                                 if assignment else {})},
                         note=ser.validated_data.get("note", ""))
                _notify_assignee(target, request.user,
                                 f"Asset {obj.asset_tag} assigned to you",
                                 f"{obj.name}", obj)
                log_action(actor=request.user, action="assignment",
                           instance=obj, details={"assigned_to": obj.assigned_to_id})
        except DjangoValidationError as exc:
            # Integrity rules (ineligible holder, already assigned, retired/
            # lost asset, ...) are business errors -> clean 400, never a 500.
            return Response(
                {"detail": "Assignment rejected by the data-integrity rules.",
                 "errors": _validation_error_payload(exc)},
                status=status.HTTP_400_BAD_REQUEST)
        except DjangoIntegrityError:
            return Response(
                {"detail": "Assignment could not be recorded: the asset may "
                           "already be assigned to another employee."},
                status=status.HTTP_409_CONFLICT)
        return Response(AssetSerializer(obj).data)
'''

helper = '''def _validation_error_payload(exc):
    """Flatten a Django ValidationError into a DRF-friendly payload."""
    if hasattr(exc, "error_dict") and exc.error_dict:
        return exc.error_dict
    errors = getattr(exc, "error_list", None) or [str(exc)]
    return {"non_field_errors": [str(e) for e in errors]}


'''

new_src = src.replace(old, new).replace("def _notify_assignee(", helper + "def _notify_assignee(", 1)
open(p, "w", encoding="utf-8").write(new_src)
print("assign patched ok")
