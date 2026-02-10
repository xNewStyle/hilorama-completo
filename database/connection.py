import os
import psycopg2
from psycopg2.extras import RealDictCursor

class PGConnection:
    def __init__(self):
        database_url = os.environ.get("DATABASE_URL")

        if not database_url:
            raise Exception("DATABASE_URL no configurado")

        self.conn = psycopg2.connect(database_url)
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
        self.conn.close()

def get_conn():
    return PGConnection()
