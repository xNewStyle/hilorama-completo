import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise Exception("DATABASE_URL no configurado")

# 🔥 Pool global
pool = SimpleConnectionPool(
    1,      # mínimo conexiones
    10,     # máximo conexiones
    database_url
)

class PGConnection:
    def __init__(self):
        self.conn = pool.getconn()
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)

    def execute(self, query, params=None):
        self.cur.execute(query, params or ())
        return self

    def fetchall(self):
        return self.cur.fetchall()

    def fetchone(self):
        return self.cur.fetchone()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.cur.close()
        pool.putconn(self.conn)  # 🔥 NO se cierra, se devuelve al pool

def get_conn():
    return PGConnection()


