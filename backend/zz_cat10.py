import os
for root, dirs, files in os.walk("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common"):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in sorted(files):
        if f.endswith(".py"):
            print(os.path.join(root, f).replace("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\", ""))
print("===== models tail =====")
ls = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\models.py", encoding="utf-8").read().splitlines()
for i in range(len(ls) - 40, len(ls)):
    print(f"{i + 1}: {ls[i]}")
print("===== audit =====")
print("\n".join(open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\audit.py", encoding="utf-8").read().splitlines()))

