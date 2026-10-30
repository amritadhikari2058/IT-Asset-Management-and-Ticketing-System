src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read()
i = src.find("def export_dataset")
print(src[i-700:i+2200])

