import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise Exception("DATABASE_URL no configurado")

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    return conn
