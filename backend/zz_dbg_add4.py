p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
start = src.find("def export_dataset(request, dataset):")
end = src.find("\n\ndef _resolve(")
body = """def export_dataset(request, dataset):
    \"\"\"TEMPORARY MINIMAL BODY FOR DEBUGGING.\"\"\"
    from rest_framework.response import Response as _R
    return _R({"ok": True, "dataset": dataset})
"""
src = src[:start] + body + src[end:]
open(p, "w", encoding="utf-8").write(src)
print("replaced body")

