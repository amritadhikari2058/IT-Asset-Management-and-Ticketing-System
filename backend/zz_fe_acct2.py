import re, sys
for path in ["D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\views.py", "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\tickets\\views.py"]:
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    for i, l in enumerate(lines):
        if re.search(r"def bulk_|bulk_delete|bulk_activate|def assign", l):
            print(f"{path.split(chr(92))[-1]}:{i + 1}: {l}")
sys.stdout.write("\n")

