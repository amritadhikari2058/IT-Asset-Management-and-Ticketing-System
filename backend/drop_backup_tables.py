import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
# Drop backup tables
tables_to_drop = [
    'backup_backupretentionpolicy',
    'backup_backupschedule', 
    'backup_restoreoperation',
    'backup_backup',
    'backup_backupjob'
]
for table in tables_to_drop:
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        print(f"Dropped table: {table}")
    except Exception as e:
        print(f"Error dropping {table}: {e}")
conn.commit()
conn.close()
print("Done dropping tables")