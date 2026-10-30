p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()
src = src.replace('resp = HttpResponse(\n            content=_csv_bytes(rows, fields), content_type="text/csv")',
                  'resp = HttpResponse(\n            _csv_bytes(rows, fields), content_type="text/csv")')
src = src.replace("""        data = _xlsx_bytes(rows, fields, title)
        resp = HttpResponse(
            data=data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")""",
                  """        data = _xlsx_bytes(rows, fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")""")
src = src.replace("""        data = _pdf_bytes(rows, fields, title)
        resp = HttpResponse(data=data, content_type="application/pdf")""",
                  """        data = _pdf_bytes(rows, fields, title)
        resp = HttpResponse(data, content_type="application/pdf")""")
src = src.replace("""        data = _docx_bytes(rows, fields, title)
        resp = HttpResponse(
            data=data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")""",
                  """        data = _docx_bytes(rows, fields, title)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")""")
open(p, "w", encoding="utf-8").write(src)
print("fixed")
