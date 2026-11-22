import psycopg

conn = psycopg.connect('host=localhost dbname=postgres user=postgres')
cur = conn.cursor()
cur.execute('ALTER USER ticketing_test WITH PASSWORD %s', ('password',))
conn.commit()
cur.close()
conn.close()
print('Password set successfully')