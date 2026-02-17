import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise Exception("DATABASE_URL no configurado")

_pool = None  # 🔥 pool lazy

def get_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            1,
            10,
            database_url
        )
    return _pool


class PGConnection:
    def __init__(self):
        pool = get_pool()  # 🔥 se crea solo cuando se usa
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

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.cur.close()
        get_pool().putconn(self.conn)


def get_conn():
    return PGConnection()
