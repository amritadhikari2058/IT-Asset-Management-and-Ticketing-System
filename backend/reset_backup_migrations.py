import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
# Delete backup migrations records
cursor.execute("DELETE FROM django_migrations WHERE app='backup'")
conn.commit()
print("Deleted backup migration records")
# Verify
cursor.execute("SELECT app, name FROM django_migrations WHERE app='backup' ORDER BY id")
rows = cursor.fetchall()
print("Remaining backup migrations:", rows)
conn.close()