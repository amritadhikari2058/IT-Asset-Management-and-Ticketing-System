p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\tests.py"
src = open(p, encoding="utf-8").read()
src = src.replace("/api/exports/", "/api/common/exports/")
open(p, "w", encoding="utf-8").write(src)
print("fixed prefixes")
