p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()

old_imports = """from django.http import HttpResponse

EXPORT_FORMATS = ("csv", "xlsx", "pdf", "docx")
"""
new_imports = """from django.http import HttpResponse
from rest_framework.renderers import BaseRenderer

EXPORT_FORMATS = ("csv", "xlsx", "pdf", "docx")


class ExportCsvRenderer(BaseRenderer):
    media_type = "text/csv"
    format = "csv"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportXlsxRenderer(BaseRenderer):
    media_type = ("application/vnd.openxmlformats-officedocument."
                  "spreadsheetml.sheet")
    format = "xlsx"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportPdfRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


class ExportDocxRenderer(BaseRenderer):
    media_type = ("application/vnd.openxmlformats-officedocument."
                  "wordprocessingml.document")
    format = "docx"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else b""


EXPORT_RENDERERS = [
    ExportCsvRenderer(), ExportXlsxRenderer(), ExportPdfRenderer(),
    ExportDocxRenderer(),
]
"""
assert src.count(old_imports) == 1, src.count(old_imports)
src = src.replace(old_imports, new_imports)
open(p, "w", encoding="utf-8").write(src)
print("exports renderers added")

