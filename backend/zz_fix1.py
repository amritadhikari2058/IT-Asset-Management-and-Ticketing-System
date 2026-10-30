p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\tests.py"
src = open(p, encoding="utf-8").read()
old = """        self.asset = Asset.objects.create(
            asset_tag="L1", name="Laptop", category=self.cat,
            assigned_to=self.emp, department=self.dep)"""
new = """        self.asset = Asset.objects.create(
            asset_tag="L1", name="Laptop", category=self.cat,
            status="assigned", assigned_to=self.emp, department=self.dep)"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")
