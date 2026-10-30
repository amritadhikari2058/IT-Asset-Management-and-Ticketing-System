lines = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\views.py", encoding="utf-8").read().splitlines()
import re
for i, l in enumerate(lines):
    if "def perform_update" in l or "def bulk_activate" in l or "def deactivate" in l or "def reactivate" in l or "def hard_delete" in l or "def change_role" in l or "def bulk_deactivate" in l or "def bulk_delete" in l:
        print(f"@@@ {i + 1}: {l}")
        for j in range(i, min(len(lines), i + 55)):
            print(f"{j + 1}: {lines[j]}")

