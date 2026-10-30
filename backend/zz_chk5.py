src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read()
print("has EXPORT VIEW HIT:", "EXPORT VIEW HIT" in src)
print("has TEMPORARY MINIMAL:", "TEMPORARY MINIMAL" in src)
print("has debug traced:", "traced_dispatch" in src)
i = src.find("def export_dataset")
print(src[i-200:i+1600])

