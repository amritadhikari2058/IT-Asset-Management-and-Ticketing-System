p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
old = """    from common.exports import (DATASETS, EXPORT_FORMATS, EXPORT_RENDERERS,
                                 build_rows, render_response)"""
new = """    from common.exports import (DATASETS, EXPORT_FORMATS, build_rows,
                                 render_response)"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")

