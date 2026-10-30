p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()
old = """EXPORT_RENDERERS = [
    ExportCsvRenderer(), ExportXlsxRenderer(), ExportPdfRenderer(),
    ExportDocxRenderer(),
]
"""
new = """EXPORT_RENDERER_CLASSES = [
    ExportCsvRenderer, ExportXlsxRenderer, ExportPdfRenderer, ExportDocxRenderer,
]
"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))

p2 = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src2 = open(p2, encoding="utf-8").read()
src2 = src2.replace("from common.exports import EXPORT_RENDERERS",
                   "from common.exports import EXPORT_RENDERER_CLASSES")
src2 = src2.replace("@renderer_classes(EXPORT_RENDERERS)",
                   "@renderer_classes(EXPORT_RENDERER_CLASSES)")
open(p2, "w", encoding="utf-8").write(src2)
print("ok")

