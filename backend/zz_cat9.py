print(open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\config\\urls.py", encoding="utf-8").read())
print("===== common/views tail =====")
ls = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read().splitlines()
for i in range(len(ls) - 60, len(ls)):
    print(f"{i + 1}: {ls[i]}")

