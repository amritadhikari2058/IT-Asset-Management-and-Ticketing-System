p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()
pairs = [
    ("def employee_rows():", "def employee_rows(user=None):"),
    ("def department_rows():", "def department_rows(user=None):"),
    ("def asset_rows():", "def asset_rows(user=None):"),
    ("def assignment_rows():", "def assignment_rows(user=None):"),
    ("def ticket_history_rows():", "def ticket_history_rows(user=None):"),
]
for o, n in pairs:
    assert src.count(o) == 1, (o, src.count(o))
    src = src.replace(o, n)
open(p, "w", encoding="utf-8").write(src)
print("ok")

