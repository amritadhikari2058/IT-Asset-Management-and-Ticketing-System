import re, sys

src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\views.py", encoding="utf-8").read()
lines = src.splitlines()
for i, l in enumerate(lines):
    if re.match(r"^(def|async def|class) ", l):
        print(f"{i + 1}: {l}")
sys.stdout.write("\n")

