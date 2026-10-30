lines = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read().splitlines()
for i in range(100, 200):
    print(f"{i + 1}: {lines[i]}")

