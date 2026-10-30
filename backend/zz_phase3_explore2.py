import os, re, sys

backend = "D:\\IT-Asset-Management-and-Ticketing-System\\backend"
frontend = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"

def show(path, needles):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    hits = []
    for n in needles:
        for m in re.finditer(re.escape(n), text):
            ln = text[: m.start()].count("\n") + 1
            hits.append((ln, n))
    seen = set()
    print(f"===== {path}")
    for ln, n in sorted(hits):
        if (ln, n) in seen:
            continue
        seen.add((ln, n))
        line = f"{ln}: {lines[ln - 1]}"
        line = line.encode("cp1252", "replace").decode("cp1252")
        print(line)

show(os.path.join(backend, "accounts", "models.py"), ["class User", "photo", "image", "FileField", "first_name", "last_name", "date_joined", "USERNAME_FIELD"])
show(os.path.join(frontend, "App.jsx"), ["path:", "Dashboard", "dashboard", "employees", "assets", "tickets", "notific"])
show(os.path.join(frontend, "pages.jsx"), ["function EmployeeDetail", "photo", "Avatar", "avatar"])

