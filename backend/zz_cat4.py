lines = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if l.startswith("class ") or l.startswith("def ") or "@action" in l or "@api_view" in l:
        print(f"{i + 1}: {l}")

