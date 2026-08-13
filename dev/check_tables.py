import psycopg2
conn = psycopg2.connect(host='127.0.0.1', user='postgres', password='postgres', dbname='archive_system')
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
for r in cur.fetchall(): print(r[0])
