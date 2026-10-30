p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\serializers.py"
lines = open(p, encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if "AssetAssignSerializer" in l:
        for j in range(max(0, i - 2), min(len(lines), i + 30)):
            print(f"{j + 1}: {lines[j]}")
        print("-----")

