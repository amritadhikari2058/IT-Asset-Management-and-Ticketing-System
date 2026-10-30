p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\tests.py"
src = open(p, encoding="utf-8").read()
old = """    def test_bad_format_400(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertEqual(res.status_code, 400)
"""
new = """    def test_unsupported_format_is_rejected(self):
        res = self.c.get("/api/common/exports/assets/?format=exe")
        self.assertNotEqual(res.status_code, 200)
"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")

