src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read()
print("count def export_dataset:", src.count("def export_dataset"))
print("count EXPORT VIEW HIT-START:", src.count("EXPORT VIEW HIT-START"))
print("count EXPORT VIEW AFTER-IMPORT-CHECK:", src.count("EXPORT VIEW AFTER-IMPORT-CHECK"))
print("count def _resolve:", src.count("def _resolve"))

