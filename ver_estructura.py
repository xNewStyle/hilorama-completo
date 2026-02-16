from database.connection import get_conn

conn = get_conn()

# 1️⃣ eliminar constraint vieja
conn.execute("""
ALTER TABLE productos
DROP CONSTRAINT productos_codigo_key;
""")

# 2️⃣ crear nueva constraint compuesta
conn.execute("""
ALTER TABLE productos
ADD CONSTRAINT productos_marca_hilo_codigo_key
UNIQUE (marca, hilo, codigo);
""")

conn.commit()
conn.close()

print("Constraint corregida correctamente.")
