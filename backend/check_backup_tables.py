import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'backup_%'")
rows = cursor.fetchall()
print("Backup-related tables:")
for row in rows:
    print(f"  {row[0]}")
conn.close()