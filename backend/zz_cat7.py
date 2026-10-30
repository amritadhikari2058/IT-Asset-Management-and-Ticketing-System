lines = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\tests.py", encoding="utf-8").read().splitlines()
for i in range(355, 432):
    print(f"{i + 1}: {lines[i]}")

