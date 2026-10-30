p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()

anchor = "def _resolve("
assert src.count(anchor) == 1

view = '''def _can_access_export(user, permission):
    if permission == "it_staff":
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", "") in
            ("system_admin", "it_manager", "it_support"))
    return bool(user and user.is_authenticated)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_dataset(request, dataset):
    """Render a read-only dataset export (CSV / XLSX / PDF / DOCX).

    Query params:
      - format: csv (default) | xlsx | pdf | docx
      - scope: all (default) | selected (requires ?ids=a,b,c)
      - ids: comma separated row ids used with scope=selected

    The response is an attachment; every export writes a protected AuditLog
    entry (dataset + format + scope + row count) without embedding secrets.
    """
    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)

    spec = DATASETS.get(dataset)
    if spec is None:
        return Response({"detail": "Unknown export dataset."}, status=404)
    if not _can_access_export(request.user, spec.get("permission", "authenticated")):
        return Response({"detail": "Forbidden."}, status=403)
    fmt = (request.query_params.get("format") or "csv").lower()
    if fmt not in EXPORT_FORMATS:
        return Response({"detail": "Unsupported format."}, status=400)
    scope = (request.query_params.get("scope") or "all").lower()
    ids_raw = request.query_params.get("ids") or ""
    ids = [i for i in str(ids_raw).split(",") if i.strip()]
    rows = build_rows(dataset, request.user)
    if scope == "selected":
        id_set = set(ids)
        rows = [r for r in rows if str(r.get("id")) in id_set]
    response = render_response(dataset, rows, fmt, request.user, request)
    AuditLog.objects.create(
        actor=request.user,
        action="export",
        entity_type="exports." + dataset,
        object_id="",
        object_repr=dataset,
        reason="",
        details={
            "dataset": dataset,
            "format": fmt,
            "scope": scope,
            "rows": len(rows),
        },
    )
    return response


'''

src = src.replace(anchor, view + anchor, 1)
open(p, "w", encoding="utf-8").write(src)

p2 = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\urls.py"
src2 = open(p2, encoding="utf-8").read()
src2 = src2.replace(
    "from common.views import (AuditLogViewSet, NotificationViewSet,  # noqa: F401\n                          data_integrity)",
    "from common.views import (AuditLogViewSet, NotificationViewSet,  # noqa: F401\n                          data_integrity, export_dataset)")
src2 = src2.replace(
    '    path("data-integrity/", data_integrity, name="data-integrity"),',
    '    path("data-integrity/", data_integrity, name="data-integrity"),\n    path("exports/<str:dataset>/", export_dataset, name="export"),')
open(p2, "w", encoding="utf-8").write(src2)
print("export view + route added")
