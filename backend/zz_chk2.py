src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", encoding="utf-8").read()
print("has helper:", "_validation_error_payload" in src)
i = src.find("_validation_error_payload")
print(src[i - 200:i + 700])
print("has assign old marker:", "with transaction.atomic():\n            # Record the open assignment first" in src)

