import os
paths = [
    r'C:/Program Files/PostgreSQL/18/data/pg_hba.conf',
    r'C:/Program Files/PostgreSQL/17/data/pg_hba.conf',
    r'C:/Program Files/PostgreSQL/16/data/pg_hba.conf',
    r'/etc/postgresql/18/main/pg_hba.conf',
    '/var/lib/postgresql/18/main/pg_hba.conf',
]
for p in paths:
    exists = os.path.exists(p)
    status = 'exists' if exists else 'not exists'
    print(f'{p}: {status}')