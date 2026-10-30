src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", encoding="utf-8").read()
i = src.find("def assign(self, request, pk=None):")
print(src[i - 30:i + 2600])

