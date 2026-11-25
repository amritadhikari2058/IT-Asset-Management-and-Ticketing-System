import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
cursor.execute("SELECT app, name FROM django_migrations WHERE app='backup' ORDER BY id")
rows = cursor.fetchall()
print("Backup migrations:")
for app, name in rows:
    print(f"  {app}.{name}")
conn.close()