p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\exports.py"
src = open(p, encoding="utf-8").read()
old = """            "is_active": "true" if u.is_active else "false",
            "created_at": u.created_at.isoformat() if u.created_at else "",
            "updated_at": u.updated_at.isoformat() if u.updated_at else "",
        })
    return rows"""
new = """            "is_active": "true" if u.is_active else "false",
            "created_at": u.date_joined.isoformat() if u.date_joined else "",
            "updated_at": u.last_login.isoformat() if u.last_login else "",
        })
    return rows"""
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))
print("ok")

