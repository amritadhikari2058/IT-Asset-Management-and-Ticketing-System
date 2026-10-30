p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
old = """    print("EXPORT VIEW HIT-START", dataset, request.method, request.query_params)
    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)
    print("EXPORT VIEW HIT-IMPORTED", dataset)
"""
new = """    print("EXPORT VIEW HIT-START", dataset, request.method, request.query_params)
"""
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new)
old2 = """    spec = DATASETS.get(dataset)
    if spec is None:
        return Response({"detail": "Unknown export dataset."}, status=404)"""
new2 = """    print("EXPORT VIEW AFTER-IMPORT-CHECK")
    spec = DATASETS.get(dataset)
    if spec is None:
        return Response({"detail": "Unknown export dataset."}, status=404)"""
assert src.count(old2) == 1, src.count(old2)
src = src.replace(old2, new2)
open(p, "w", encoding="utf-8").write(src)
print("ok")

