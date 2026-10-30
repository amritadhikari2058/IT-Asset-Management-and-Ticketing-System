p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py"
src = open(p, encoding="utf-8").read()
src = src.replace("from django.db import transaction\nfrom django.urls import path\nfrom rest_framework", "from django.db import transaction\nfrom rest_framework", 1)
open(p, "w", encoding="utf-8").write(src)
print("removed unused import")

