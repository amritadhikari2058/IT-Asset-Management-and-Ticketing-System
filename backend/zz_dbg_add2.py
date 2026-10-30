p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
old = """    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)

    print("EXPORT VIEW HIT", dataset, request.method, request.query_params)
"""
new = """    print("EXPORT VIEW HIT-START", dataset, request.method, request.query_params)
    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)
    print("EXPORT VIEW HIT-IMPORTED", dataset)
"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")

