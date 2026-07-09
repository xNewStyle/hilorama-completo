import os

SimpleConnectionPool = None
RealDictCursor = None


def _modo_api_cliente():
    return os.environ.get("HILORAMA_DATA_MODE", "").strip().lower() == "api"


def require_direct_db_allowed():
    if _modo_api_cliente():
        raise RuntimeError("Base local bloqueada en modo API cliente.")


def _cargar_driver_postgres():
    global SimpleConnectionPool, RealDictCursor
    require_direct_db_allowed()
    if SimpleConnectionPool is not None and RealDictCursor is not None:
        return
    from psycopg2.pool import SimpleConnectionPool as _SimpleConnectionPool
    from psycopg2.extras import RealDictCursor as _RealDictCursor

    SimpleConnectionPool = _SimpleConnectionPool
    RealDictCursor = _RealDictCursor


def get_database_url():
    require_direct_db_allowed()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL no configurado")
    return database_url


_pool = None  # 🔥 pool lazy

def get_pool():
    global _pool
    if _pool is None:
        _cargar_driver_postgres()
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
