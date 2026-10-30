p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()

addition = '''


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def data_integrity(request):
    """READ-ONLY data-integrity report (System Admin only).

    Identifies pre-existing inconsistent records so that any repair is a
    deliberate, reviewable human decision instead of a silent backfill.

    The report NEVER mutates anything. Repairs, when needed, must be made
    through explicit, confirmable workflows (dedicated workflows such as
    ``assign`` / ``return_asset`` / ``retire`` / ``mark_lost`` or the recycle
    bin) rather than blanket updates.
    """
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    from django.db.models import Count
    from assets.models import Asset, Assignment
    from accounts.models import User

    issues = []
    assets = Asset.objects.order_by("id")[:500]
    assets_checked = 0
    for a in assets:
        assets_checked += 1
        open_assignments = list(a.assignments.filter(returned_at__isnull=True))
        if a.status == "assigned" and not a.assigned_to_id:
            issues.append({
                "area": "asset",
                "code": "asset_assigned_without_holder",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset status is 'assigned' but no holder is set.",
                "suggested_fix": "Clear the stale status (set it back to "
                                 "'available') or assign a valid holder.",
            })
        if a.status in ("retired", "lost") and a.assigned_to_id:
            issues.append({
                "area": "asset",
                "code": "asset_ineligible_with_holder",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset status is '" + a.status + "' but a holder is set.",
                "suggested_fix": "Clear the holder before retiring/losing.",
            })
        if a.assigned_to_id and not open_assignments:
            issues.append({
                "area": "asset",
                "code": "holder_without_open_assignment",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset has a holder but no open assignment row.",
                "suggested_fix": "Return the asset (closes the open "
                                 "assignment) or create an open assignment.",
            })
        for assn in open_assignments:
            holder = assn.assigned_to
            if holder is not None and (
                    getattr(holder, "is_deleted", False)
                    or not getattr(holder, "is_active", True)):
                issues.append({
                    "area": "assignment",
                    "code": "assignment_to_inactive_user",
                    "object": "asset " + str(a.asset_tag),
                    "object_id": assn.pk,
                    "detail": "Open assignment points at an inactive or "
                              "soft-deleted user.",
                    "suggested_fix": "Return the asset or reactivate the user.",
                })
    dup_open = (Asset.objects.filter(assignments__returned_at__isnull=True)
                .values("id").annotate(n=Count("id")).filter(n__gt=1))
    for row in dup_open[:50]:
        issues.append({
            "area": "assignment",
            "code": "assignment_duplicate_open",
            "object": "asset #" + str(row["id"]),
            "detail": "Asset has " + str(row["n"]) + " open assignments.",
            "suggested_fix": "Return the asset(s) before assigning again.",
        })
    return Response({
        "issues": issues,
        "counts": {
            "issues": len(issues),
            "assets_checked": assets_checked,
        },
        "note": "Read-only data-integrity report; repairs are explicit and "
                "human-driven.",
    })


def _resolve(
'''

old_anchor = "\n\ndef _resolve("
assert src.count(old_anchor) == 1, src.count(old_anchor)
src = src.replace(old_anchor, addition, 1)
open(p, "w", encoding="utf-8").write(src)
print("common/views patched ok")
