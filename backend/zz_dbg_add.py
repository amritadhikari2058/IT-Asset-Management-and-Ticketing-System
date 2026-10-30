p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
old = """    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)

    spec = DATASETS.get(dataset)"""
new = """    from common.exports import (BUILDERS, DATASETS, EXPORT_FORMATS,
                                 build_rows, render_response)

    print("EXPORT VIEW HIT", dataset, request.method, request.query_params)

    spec = DATASETS.get(dataset)"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("debug added")

