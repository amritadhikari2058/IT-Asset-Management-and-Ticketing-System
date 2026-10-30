p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\urls.py"
src = open(p, encoding="utf-8").read()
src = src.replace("from django.urls import path", "from django.urls import include, path", 1)
open(p, "w", encoding="utf-8").write(src)
print("ok")

