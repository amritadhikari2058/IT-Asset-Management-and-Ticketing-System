lines = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", encoding="utf-8").read().splitlines()
for i in range(879, 1010):
    print(f"{i + 1}: {lines[i]}")

