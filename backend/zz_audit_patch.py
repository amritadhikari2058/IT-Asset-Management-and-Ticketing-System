p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\models.py"
src = open(p, encoding="utf-8").read()
old = '''        ("note", "Note / comment"),
        ("password_reset", "Password reset"),
    ]
'''
new = '''        ("note", "Note / comment"),
        ("password_reset", "Password reset"),
        ("export", "Export"),
    ]
'''
assert src.count(old) == 1, src.count(old)
open(p, "w", encoding="utf-8").write(src.replace(old, new))

mig = """from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (\"common\", \"0003_alter_auditlog_action\"),
    ]

    operations = [
        migrations.AlterField(
            model_name=\"auditlog\",
            name=\"action\",
            field=models.CharField(choices=[(\"create\", \"Create\"), (\"update\", \"Update\"), (\"soft_delete\", \"Soft delete\"), (\"restore\", \"Restore\"), (\"hard_delete\", \"Permanent delete\"), (\"bulk_create\", \"Bulk create\"), (\"bulk_update\", \"Bulk update\"), (\"bulk_soft_delete\", \"Bulk soft delete\"), (\"status_change\", \"Status change\"), (\"assignment\", \"Assignment change\"), (\"deactivate\", \"Deactivate\"), (\"reactivate\", \"Reactivate\"), (\"retire\", \"Retire\"), (\"note\", \"Note / comment\"), (\"password_reset\", \"Password reset\"), (\"export\", \"Export\")], max_length=32),
        ),
    ]
"""
open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\migrations\\0004_alter_auditlog_action.py", "w", encoding="utf-8").write(mig)
print("audit action + migration written")
