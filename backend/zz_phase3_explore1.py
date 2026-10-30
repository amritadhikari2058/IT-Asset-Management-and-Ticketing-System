import os, re

backend = "D:\\IT-Asset-Management-and-Ticketing-System\\backend"
frontend = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"

def show(path, needles, limit=25):
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
        print(f"{ln}: ...{lines[ln - 1]}...")

show(os.path.join(backend, "assets", "models.py"), ["photo", "image", "attachment", "FileField", "upload_to", "Warranty", "warranty", "purchase", "vendor"])
show(os.path.join(frontend, "assets.jsx"), ["Preview", "preview", "photo", "image", "thumbnail", "selected", "onToggle", "bulk", "Badge"])
show(os.path.join(frontend, "components.jsx"), ["Badge", "STATUS_TONE", "PRIORITY_TONE", "badge-"])
show(os.path.join(frontend, "tickets.jsx"), ["Badge", "STATUS_TONE"])
show(os.path.join(frontend, "index.css"), ["badge-", "thumbnail", "photo", "preview", "selected", "input-date"])
show(os.path.join(frontend, "bulk.jsx"), ["Preview", "preview", "selected", "onToggle", "Bulk"])
show(os.path.join(frontend, "App.jsx"), ["Dashboard", "dashboard", "Badge"])
show(os.path.join(frontend, "notifications.jsx"), ["Badge"])

