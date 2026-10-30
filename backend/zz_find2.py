paths = [
    "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\tests.py",
    "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\tests.py",
    "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\tickets\\tests.py",
]
for p in paths:
    lines = open(p, encoding="utf-8").read().splitlines()
    print("=====", p)
    for i, line in enumerate(lines):
        if ("Asset.objects.create(" in line or "Asset.objects.get_or_create(" in line
                or "self.asset = Asset(" in line or "self.busy = Asset(" in line
                or "busy = Asset(" in line or "gone = Asset(" in line
                or "self.free = Asset(" in line or "self.ret = Asset(" in line
                or "self.rep = Asset(" in line or "self.lost = Asset(" in line
                or "self.gone = Asset(" in line or "self.free2 = Asset(" in line
                or "self.a1 = Asset(" in line or "self.a2 = Asset(" in line
                or "self.asset = Asset(" in line or "self.first = Asset(" in line
                or "other = Asset(" in line or "self.asset = Asset" in line
                or "a1 = Asset(" in line or "a2 = Asset(" in line or "a = Asset(" in line
                or "base = {" in line):
            window = lines[max(0, i - 2):i + 8]
            hits = [j + 1 for j, l in enumerate(window) if "assigned_to" in l or "status" in l or "clean" in l]
            if hits:
                print("--- context near line", i + 1)
                for j, l in enumerate(window, start=max(1, i - 1)):
                    print(f"{j}: {l}")

