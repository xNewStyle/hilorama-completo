from db import get_conn
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def init_db():
    conn = get_conn()

    schema_path = os.path.join(BASE_DIR, "schema.sql")

    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.close()

    print("✅ Base de datos creada correctamente")

if __name__ == "__main__":
    init_db()
