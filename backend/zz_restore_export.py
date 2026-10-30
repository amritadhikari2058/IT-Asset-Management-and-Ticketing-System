p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()

old = '''@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_dataset(request, dataset):
    """TEMPORARY MINIMAL BODY FOR DEBUGGING."""
    from rest_framework.response import Response as _R
    return _R({"ok": True, "dataset": dataset})
'''

new = '''@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes(EXPORT_RENDERERS)
def export_dataset(request, dataset):
    """Render a read-only dataset export (CSV / XLSX / PDF / DOCX).

    Query params:
      - format: csv (default) | xlsx | pdf | docx
      - scope: all (default) | selected (requires ?ids=a,b,c)
      - ids: comma separated row ids used with scope=selected

    The response is an attachment; every export writes a protected AuditLog
    entry (dataset + format + scope + row count) without embedding secrets.
    """
    from common.exports import (DATASETS, EXPORT_FORMATS, EXPORT_RENDERERS,
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

assert src.count(old) == 1, src.count(old)
src = src.replace(old, new)
src = src.replace(
    "from rest_framework.decorators import action, api_view, permission_classes",
    "from rest_framework.decorators import (action, api_view, permission_classes,\n                                        renderer_classes)")
src = src.replace(
    "from common.exports import (DATASETS, EXPORT_FORMATS, EXPORT_RENDERERS,\n                                 build_rows, render_response)",
    "from common.exports import (DATASETS, EXPORT_FORMATS, EXPORT_RENDERERS,\n                                 build_rows, render_response)")
open(p, "w", encoding="utf-8").write(src)
print("restored export body + renderer_classes")
