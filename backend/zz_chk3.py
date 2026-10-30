import py_compile
py_compile.compile("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", doraise=True)
print("views.py compiles ok")
src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py", encoding="utf-8").read()
print("helper occurrences:", src.count("_validation_error_payload"))
i = src.find("def _validation_error_payload")
print(src[i-60:i+520])

