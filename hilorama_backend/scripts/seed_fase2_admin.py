"""Seed local para probar FASE 2.

No se ejecuta automaticamente. Lee DATABASE_URL y crea usuarios con bcrypt.
"""

import os
import secrets
import sys

import bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor


DEFAULT_CLIENTE = "Hilorama Local Pruebas"
DEFAULT_ADMIN_USER = "admin_local"
DEFAULT_VENDOR_USER = "vendedor_local"


def _env(name, default=None):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _connect():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL no configurado. Use una base de prueba, no produccion.")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def _ensure_cliente(cur):
    nombre_negocio = _env("HILORAMA_SEED_CLIENTE", DEFAULT_CLIENTE)
    cur.execute(
        """
        SELECT id
        FROM clientes_sistema
        WHERE nombre_negocio=%s
        ORDER BY id ASC
        LIMIT 1
        """,
        (nombre_negocio,),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            """
            UPDATE clientes_sistema
            SET estado='activo',
                contacto=%s,
                telefono=%s,
                email=%s,
                fecha_vencimiento=COALESCE(fecha_vencimiento, CURRENT_DATE + 30),
                max_dispositivos=%s,
                puede_actualizar=FALSE,
                plan=%s,
                updated_at=NOW()
            WHERE id=%s
            """,
            (
                _env("HILORAMA_SEED_CONTACTO", "Prueba local"),
                _env("HILORAMA_SEED_TELEFONO", ""),
                _env("HILORAMA_SEED_EMAIL", "local@hilorama.test"),
                int(_env("HILORAMA_SEED_MAX_DISPOSITIVOS", "3")),
                _env("HILORAMA_SEED_PLAN", "local"),
                row["id"],
            ),
        )
        return row["id"]

    cur.execute(
        """
        INSERT INTO clientes_sistema (
            nombre_negocio, contacto, telefono, email, estado,
            fecha_vencimiento, max_dispositivos, puede_actualizar, plan, notas_admin
        )
        VALUES (%s,%s,%s,%s,'activo',CURRENT_DATE + 30,%s,FALSE,%s,%s)
        RETURNING id
        """,
        (
            nombre_negocio,
            _env("HILORAMA_SEED_CONTACTO", "Prueba local"),
            _env("HILORAMA_SEED_TELEFONO", ""),
            _env("HILORAMA_SEED_EMAIL", "local@hilorama.test"),
            int(_env("HILORAMA_SEED_MAX_DISPOSITIVOS", "3")),
            _env("HILORAMA_SEED_PLAN", "local"),
            "Seed FASE 2 local. No usar como datos reales.",
        ),
    )
    return cur.fetchone()["id"]


def _upsert_usuario(cur, cliente_id, nombre, usuario, password, rol):
    password_hash = _hash_password(password)
    cur.execute(
        """
        INSERT INTO usuarios_sistema (
            cliente_id, nombre, usuario, password_hash, rol, activo
        )
        VALUES (%s,%s,%s,%s,%s,TRUE)
        ON CONFLICT (usuario) DO UPDATE
        SET cliente_id=EXCLUDED.cliente_id,
            nombre=EXCLUDED.nombre,
            password_hash=EXCLUDED.password_hash,
            rol=EXCLUDED.rol,
            activo=TRUE,
            updated_at=NOW()
        RETURNING id
        """,
        (cliente_id, nombre, usuario, password_hash, rol),
    )
    return cur.fetchone()["id"]


def main():
    admin_user = _env("HILORAMA_SEED_ADMIN_USER", DEFAULT_ADMIN_USER)
    admin_password = _env("HILORAMA_SEED_ADMIN_PASSWORD")
    generated_admin_password = False
    if not admin_password:
        admin_password = secrets.token_urlsafe(12)
        generated_admin_password = True

    create_vendor = _env("HILORAMA_SEED_CREATE_VENDOR", "1") == "1"
    vendor_user = _env("HILORAMA_SEED_VENDOR_USER", DEFAULT_VENDOR_USER)
    vendor_password = _env("HILORAMA_SEED_VENDOR_PASSWORD")
    generated_vendor_password = False
    if create_vendor and not vendor_password:
        vendor_password = secrets.token_urlsafe(12)
        generated_vendor_password = True

    with _connect() as conn:
        with conn.cursor() as cur:
            cliente_id = _ensure_cliente(cur)
            admin_id = _upsert_usuario(
                cur,
                cliente_id,
                _env("HILORAMA_SEED_ADMIN_NAME", "Administrador Local"),
                admin_user,
                admin_password,
                "super_admin",
            )
            vendor_id = None
            if create_vendor:
                vendor_id = _upsert_usuario(
                    cur,
                    cliente_id,
                    _env("HILORAMA_SEED_VENDOR_NAME", "Vendedor Local"),
                    vendor_user,
                    vendor_password,
                    "vendedor",
                )
        conn.commit()

    print("Seed FASE 2 creado/actualizado en base de prueba.")
    print(f"cliente_id={cliente_id}")
    print(f"super_admin id={admin_id} usuario={admin_user}")
    if generated_admin_password:
        print(f"super_admin password temporal={admin_password}")
        print("Guarde esta clave solo para prueba local; no queda en archivos.")
    else:
        print("super_admin password tomada de HILORAMA_SEED_ADMIN_PASSWORD")
    if create_vendor:
        print(f"vendedor id={vendor_id} usuario={vendor_user}")
        if generated_vendor_password:
            print(f"vendedor password temporal={vendor_password}")
        else:
            print("vendedor password tomada de HILORAMA_SEED_VENDOR_PASSWORD")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR seed FASE 2: {exc}", file=sys.stderr)
        raise
