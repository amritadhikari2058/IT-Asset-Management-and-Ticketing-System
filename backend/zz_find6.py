p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\tests.py"
lines = open(p, encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if "assign" in l.lower() and ("/assign/" in l or "def test" in l):
        print(f"{i + 1}: {l}")
print("===== assign-related contexts =====")
for i, l in enumerate(lines):
    if "assign" in l.lower():
        seg = lines[max(0, i - 3):i + 4]
        if any("Asset.objects.create" in s or "Asset(" in s for s in seg):
            for j in range(max(0, i - 3), min(len(lines), i + 4)):
                print(f"{j + 1}: {lines[j]}")
            print("-----")

