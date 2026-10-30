p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\views.py"
src = open(p, encoding="utf-8").read()

old1 = """    def perform_update(self, serializer):
        # Ordinary updates NEVER modify role / ticket-creation rights.
        serializer.validated_data.pop("role", None)
        serializer.validated_data.pop("can_create_tickets", None)
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)
"""

new1 = """    def perform_update(self, serializer):
        # Ordinary updates NEVER modify role / ticket-creation rights.
        serializer.validated_data.pop("role", None)
        serializer.validated_data.pop("can_create_tickets", None)
        obj = self.get_object()
        wants_inactive = (
            "is_active" in serializer.validated_data
            and serializer.validated_data.get("is_active") is False)
        if wants_inactive and obj.assignments_received.filter(
                returned_at__isnull=True).exists():
            from rest_framework.exceptions import ValidationError as DRFValidationError
            raise DRFValidationError(
                {"is_active": ["Cannot deactivate: still holds open asset "
                               "assignment(s). Return the asset(s) first."]})
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)
"""

old2 = """    @action(detail=False, methods=["post"])
    def bulk_activate(self, request):
        ids, activate = request.data.get("ids", []), request.data.get(
            "activate", True)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            qs = User.objects.filter(id__in=ids)
            return Response({"preview": [u.employee_id for u in qs],
                             "affected": qs.count()})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed = [], []
        for pk in ids:
            try:
                with transaction.atomic():
                    obj = User.objects.get(pk=pk)
                    obj.is_active = bool(activate)
                    obj.save(update_fields=["is_active"])
                    log_action(
                        actor=request.user,
                        action="reactivate" if activate else "deactivate",
                        instance=obj)
                    ok.append(pk)
            except Exception as exc:
                failed.append({"id": pk, "errors": str(exc)})
        return Response({"successful": ok, "failed": failed})
"""

new2 = """    @action(detail=False, methods=["post"])
    def bulk_activate(self, request):
        ids, activate = request.data.get("ids", []), request.data.get(
            "activate", True)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            qs = User.objects.filter(id__in=ids)
            blocked = [
                u.employee_id for u in qs
                if not activate and u.assignments_received.filter(
                    returned_at__isnull=True).exists()
            ]
            return Response({
                "preview": [u.employee_id for u in qs],
                "affected": qs.count(),
                "blocked": blocked})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for pk in ids:
            try:
                with transaction.atomic():
                    obj = User.objects.get(pk=pk)
                    if not activate and obj.assignments_received.filter(
                            returned_at__isnull=True).exists():
                        skipped.append({
                            "id": pk,
                            "reason": "still holds open asset assignment(s); "
                                      "return the asset first"})
                        continue
                    obj.is_active = bool(activate)
                    obj.save(update_fields=["is_active"])
                    log_action(
                        actor=request.user,
                        action="reactivate" if activate else "deactivate",
                        instance=obj)
                    ok.append(pk)
            except Exception as exc:
                failed.append({"id": pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})
"""

for o, n in ((old1, new1), (old2, new2)):
    assert src.count(o) == 1, (o[:50], src.count(o))
    src = src.replace(o, n)

open(p, "w", encoding="utf-8").write(src)
print("accounts patches ok")
