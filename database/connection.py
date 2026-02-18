import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

def get_database_url():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL no configurado")
    return database_url


_pool = None  # 🔥 pool lazy

def get_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            1,
            5,
            get_database_url()
        )
    return _pool



class PGConnection:
    def __init__(self):
        pool = get_pool()
        self.pool = pool
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
        if self.cur:
            self.cur.close()
        if self.conn:
            self.pool.putconn(self.conn)

    # 🔥 CLAVE
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

def get_conn():
    return PGConnection()

with get_conn() as conn:
    conn.execute("SELECT * FROM productos")
    rows = conn.fetchall()
