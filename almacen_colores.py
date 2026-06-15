import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from database.connection import get_conn
from datetime import datetime, timedelta
import math
import os

# ================= CONFIG =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASSWORD = "1"
STOCK_MINIMO = 50

# Parámetros para sugerencia de compra.
# Se pueden ajustar después sin tocar la base de datos.
DIAS_ANALISIS_COMPRA = 90       # cuántos días de historial se revisan
DIAS_COBERTURA_COMPRA = 45      # para cuántos días quieres comprar material
STOCK_SEGURIDAD_COMPRA = 5      # colchón extra recomendado
MINIMO_COMPRA_PIEZAS = 1        # evita recomendar cantidades negativas o absurdas

# ================= ESTADO GLOBAL UI =================
_schema_ok = False
autorizado = False
editor_activo = None
buscar_job = None
filtro_modo_actual = "TODOS"   # TODOS | BAJO | OK

# Widgets globales (se inicializan al crear la UI)
root = None
tabla = None
combo_marca = None
entry_hilo = None
entry_color = None
entry_codigo = None
entry_barras = None
entry_stock = None
entry_vol = None
entry_buscar = None
lbl_ganancia = None
lbl_estado = None
card_total_tonos = None
card_stock_total = None
card_stock_bajo = None
card_marcas = None
card_valor_costo = None
card_valor_venta = None
card_ganancia = None
btn_todos = None
btn_bajo = None
btn_ok = None
btn_items = None
var_es_inventariable = None

# ================= UTIL =================
def to_float(valor, default=0.0):
    if valor is None:
        return default
    try:
        if isinstance(valor, str):
            valor = valor.replace("$", "").replace(",", ".").strip()
            if valor == "":
                return default
        return float(valor)
    except Exception:
        return default


def money(valor):
    return f"${to_float(valor):,.2f}"


def es_inventariable_producto(p):
    """True si el producto debe contar en stock físico, inversión, ganancia de almacén y resurtido sugerido."""
    if p is None:
        return True
    valor = True
    try:
        valor = p.get("es_inventariable", True)
    except Exception:
        return True
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "f", "0", "no", "n", "item")
    return True


def tipo_producto_texto(p):
    return "Inventario" if es_inventariable_producto(p) else "Item cotización"


def stock_inventario(p):
    return int(p.get("stock") or 0) if es_inventariable_producto(p) else 0


def set_status(texto):
    global lbl_estado
    if lbl_estado is not None:
        lbl_estado.config(text=texto)


def ensure_almacen_schema():
    """Migración segura: solo agrega columnas/tablas si faltan. No borra datos."""
    global _schema_ok
    if _schema_ok:
        return

    conn = get_conn()
    try:
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS precio REAL DEFAULT 0
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS costo_neto REAL DEFAULT 0
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS es_inventariable BOOLEAN DEFAULT TRUE
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS tipo_producto TEXT DEFAULT 'INVENTARIO'
        """)
        conn.execute("""
            UPDATE productos
            SET es_inventariable=TRUE
            WHERE es_inventariable IS NULL
        """)
        conn.execute("""
            UPDATE productos
            SET tipo_producto='INVENTARIO'
            WHERE tipo_producto IS NULL OR tipo_producto=''
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_almacen (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT DEFAULT 'ADMIN',
                tipo TEXT NOT NULL,
                marca TEXT,
                hilo TEXT,
                color TEXT,
                codigo TEXT,
                stock_anterior INTEGER,
                stock_nuevo INTEGER,
                cantidad INTEGER DEFAULT 0,
                campo TEXT,
                valor_anterior TEXT,
                valor_nuevo TEXT,
                motivo TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mov_almacen_fecha
            ON movimientos_almacen(fecha DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mov_almacen_codigo
            ON movimientos_almacen(codigo)
        """)
        conn.commit()
        _schema_ok = True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def registrar_movimiento(
    tipo,
    marca=None,
    hilo=None,
    color=None,
    codigo=None,
    stock_anterior=None,
    stock_nuevo=None,
    cantidad=0,
    campo=None,
    valor_anterior=None,
    valor_nuevo=None,
    motivo="",
    conn=None
):
    cerrar = False
    if conn is None:
        ensure_almacen_schema()
        conn = get_conn()
        cerrar = True

    conn.execute("""
        INSERT INTO movimientos_almacen
        (fecha, usuario, tipo, marca, hilo, color, codigo,
         stock_anterior, stock_nuevo, cantidad, campo,
         valor_anterior, valor_nuevo, motivo)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        datetime.now(),
        "ADMIN",
        tipo,
        marca,
        hilo,
        color,
        codigo,
        stock_anterior,
        stock_nuevo,
        cantidad,
        campo,
        None if valor_anterior is None else str(valor_anterior),
        None if valor_nuevo is None else str(valor_nuevo),
        motivo
    ))

    if cerrar:
        conn.commit()
        conn.close()


def valores_financieros_producto(p):
    # Los items de cotización existen para venderse, pero no representan material físico en almacén.
    # Por eso su stock financiero se toma como 0 y no inflan costo, venta ni ganancia del inventario.
    stock = stock_inventario(p)
    costo_unitario = to_float(p.get("costo_neto")) or to_float(p.get("distribuidor"))
    venta_unitaria = to_float(p.get("precio")) or to_float(p.get("venta"))
    valor_costo = costo_unitario * stock
    valor_venta = venta_unitaria * stock
    ganancia = valor_venta - valor_costo
    return costo_unitario, venta_unitaria, valor_costo, valor_venta, ganancia


def marcas_existentes():
    ensure_almacen_schema()
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT marca FROM productos ORDER BY marca").fetchall()
    conn.close()
    return [r["marca"] for r in rows]


def obtener_productos():
    ensure_almacen_schema()
    conn = get_conn()
    productos = conn.execute("""
        SELECT
            p.marca,
            p.hilo,
            p.color,
            p.codigo,
            p.stock,
            p.codigo_barras,
            p.estado,
            p.precio,
            p.costo_neto,
            p.volumetrico,
            p.es_inventariable,
            p.tipo_producto,
            pr.distribuidor,
            pr.venta
        FROM productos p
        LEFT JOIN precios pr
            ON pr.marca = p.marca
        ORDER BY p.marca, p.hilo, p.color, p.codigo
    """).fetchall()
    conn.close()
    return productos


def filtrar_productos(productos, filtro=None, modo=None):
    resultado = []
    filtro = (filtro or "").strip().upper()
    modo = modo or filtro_modo_actual

    for p in productos:
        texto = " ".join([
            str(p.get("marca") or ""),
            str(p.get("hilo") or ""),
            str(p.get("color") or ""),
            str(p.get("codigo") or ""),
            str(p.get("codigo_barras") or ""),
            str(p.get("estado") or ""),
            str(p.get("tipo_producto") or ""),
            tipo_producto_texto(p)
        ]).upper()

        inv = es_inventariable_producto(p)
        if filtro and filtro not in texto:
            continue
        if modo == "BAJO" and (not inv or p.get("estado") != "RESURTIR"):
            continue
        if modo == "OK" and (not inv or p.get("estado") != "OK"):
            continue
        if modo == "ITEMS" and inv:
            continue
        resultado.append(p)
    return resultado


def calcular_totales(productos):
    stock_total = 0
    valor_costo_total = 0.0
    valor_venta_total = 0.0
    ganancia_total = 0.0
    stock_bajo = 0
    marcas = set()

    for r in productos:
        marcas.add(r.get("marca"))
        if es_inventariable_producto(r):
            stock_total += int(r.get("stock") or 0)
            if r.get("estado") == "RESURTIR":
                stock_bajo += 1
        _, _, valor_costo, valor_venta, ganancia = valores_financieros_producto(r)
        valor_costo_total += valor_costo
        valor_venta_total += valor_venta
        ganancia_total += ganancia

    return {
        "tonos": len(productos),
        "stock_total": stock_total,
        "stock_bajo": stock_bajo,
        "marcas": len(marcas),
        "valor_costo": valor_costo_total,
        "valor_venta": valor_venta_total,
        "ganancia": ganancia_total,
    }


def set_card(widget, valor):
    if widget is not None:
        widget.config(text=valor)


def actualizar_dashboard(productos_filtrados):
    tot = calcular_totales(productos_filtrados)
    set_card(card_total_tonos, str(tot["tonos"]))
    set_card(card_stock_total, str(tot["stock_total"]))
    set_card(card_stock_bajo, str(tot["stock_bajo"]))
    set_card(card_marcas, str(tot["marcas"]))
    set_card(card_valor_costo, money(tot["valor_costo"]))
    set_card(card_valor_venta, money(tot["valor_venta"]))
    set_card(card_ganancia, money(tot["ganancia"]))

    if lbl_ganancia is not None:
        lbl_ganancia.config(
            text=(
                f"Resumen actual  •  Tonos: {tot['tonos']}  •  Stock: {tot['stock_total']}  •  "
                f"Costo: {money(tot['valor_costo'])}  •  Venta: {money(tot['valor_venta'])}  •  "
                f"Ganancia estimada: {money(tot['ganancia'])}"
            )
        )


def limpiar_formulario():
    for widget in [entry_hilo, entry_color, entry_codigo, entry_barras, entry_stock, entry_vol]:
        if widget is not None:
            widget.delete(0, tk.END)
    if var_es_inventariable is not None:
        var_es_inventariable.set(True)
    if combo_marca is not None:
        combo_marca.focus_set()
    set_status("Formulario limpio")


def refrescar_tabla(filtro=None, modo=None):
    ensure_almacen_schema()
    filtro = entry_buscar.get() if filtro is None and entry_buscar is not None else (filtro or "")
    modo = modo or filtro_modo_actual

    abiertos = []
    for item in tabla.get_children():
        if tabla.item(item, "open"):
            abiertos.append(tabla.item(item, "text"))
            for sub in tabla.get_children(item):
                if tabla.item(sub, "open"):
                    abiertos.append((tabla.item(item, "text"), tabla.item(sub, "text")))

    tabla.delete(*tabla.get_children())

    productos = obtener_productos()
    productos_filtrados = filtrar_productos(productos, filtro=filtro, modo=modo)
    datos = {}

    for p in productos_filtrados:
        datos.setdefault(p["marca"], {}).setdefault(p["hilo"], []).append(p)

    for marca in sorted(datos):
        marca_id = tabla.insert("", "end", text=marca, tags=("marca",))
        if marca in abiertos:
            tabla.item(marca_id, open=True)

        for hilo in sorted(datos[marca]):
            hilo_id = tabla.insert(marca_id, "end", text=hilo, tags=("hilo",))
            if (marca, hilo) in abiertos:
                tabla.item(hilo_id, open=True)

            for idx, p in enumerate(datos[marca][hilo]):
                costo_unitario, venta_unitaria, valor_costo, valor_venta, ganancia = valores_financieros_producto(p)

                inv = es_inventariable_producto(p)
                estado = (p.get("estado") or "OK") if inv else "ITEM"
                base_tag = "item" if not inv else ("ok" if estado == "OK" else "bajo")
                stripe_tag = "par" if idx % 2 == 0 else "impar"
                tag = f"{base_tag}_{stripe_tag}"
                stock_mostrar = p["stock"] if inv else "—"

                tabla.insert(
                    hilo_id,
                    "end",
                    text="",
                    values=(
                        p["hilo"],
                        p["color"],
                        p["codigo"],
                        stock_mostrar,
                        p["codigo_barras"],
                        money(costo_unitario),
                        money(venta_unitaria),
                        f"{float(p['volumetrico']):.2f}" if p["volumetrico"] else "1.00",
                        tipo_producto_texto(p),
                        estado,
                        money(valor_costo),
                        money(valor_venta),
                        money(ganancia)
                    ),
                    tags=(tag,)
                )

    actualizar_dashboard(productos_filtrados)
    set_status(f"Vista actual: {len(productos_filtrados)} tonos mostrados • filtro: {modo}")
    actualizar_estilo_botones_filtro()

# ================= ACCIONES =================
def agregar_producto():
    ensure_almacen_schema()
    marca = combo_marca.get().strip().upper()
    hilo = entry_hilo.get().strip().upper()
    color = entry_color.get().strip().upper()
    codigo = entry_codigo.get().strip()
    codigo_barras = entry_barras.get().strip()
    inventariable = True if var_es_inventariable is None else bool(var_es_inventariable.get())
    stock = entry_stock.get().strip()
    vol = entry_vol.get().strip().replace(",", ".")

    if not vol:
        volumetrico = 1.0
    else:
        try:
            volumetrico = float(vol)
        except ValueError:
            messagebox.showerror("Error", f"Volumétrico inválido: {vol}")
            return

    if volumetrico <= 0:
        messagebox.showerror("Error", "Volumétrico debe ser mayor a 0")
        return

    if not all([marca, hilo, color, codigo]):
        messagebox.showerror("Error", "Completa marca, hilo, color y código")
        return

    if inventariable:
        if not stock:
            messagebox.showerror("Error", "El stock es obligatorio para productos de inventario")
            return
        try:
            stock = int(stock)
        except Exception:
            messagebox.showerror("Error", "Stock inválido")
            return
    else:
        # Los paquetes/combos/items de cotización se guardan con stock 0 para que no inflen cálculos.
        stock = 0

    conn = get_conn()
    existe = conn.execute("""
        SELECT 1 FROM productos
        WHERE marca=%s AND hilo=%s AND color=%s AND codigo=%s
    """, (marca, hilo, color, codigo)).fetchone()

    if existe:
        messagebox.showwarning("Duplicado", "Este tono ya existe")
        conn.close()
        return

    estado = ("OK" if stock >= STOCK_MINIMO else "RESURTIR") if inventariable else "ITEM"
    tipo_producto = "INVENTARIO" if inventariable else "ITEM"

    conn.execute("""
        INSERT INTO productos
        (marca,hilo,color,codigo,codigo_barras,stock,estado,volumetrico,es_inventariable,tipo_producto)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (marca, hilo, color, codigo, codigo_barras, stock, estado, volumetrico, inventariable, tipo_producto))

    registrar_movimiento(
        "ALTA_PRODUCTO" if inventariable else "ALTA_ITEM_COTIZACION",
        marca=marca,
        hilo=hilo,
        color=color,
        codigo=codigo,
        stock_anterior=0,
        stock_nuevo=stock,
        cantidad=stock,
        motivo="Producto agregado desde almacén" if inventariable else "Item cotización agregado desde almacén",
        conn=conn
    )

    conn.commit()
    conn.close()

    combo_marca["values"] = marcas_existentes()
    refrescar_tabla()
    limpiar_formulario()
    set_status(f"Producto agregado: {marca} / {hilo} / {color} / {codigo}")


def eliminar_tono():
    ensure_almacen_schema()
    item = tabla.focus()
    if not item:
        return

    item_data = tabla.item(item)
    if not item_data["values"]:
        return

    pwd = simpledialog.askstring("Contraseña", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    valores = item_data["values"]
    hilo = valores[0]
    color = valores[1]
    codigo = str(valores[2])

    parent_hilo = tabla.parent(item)
    parent_marca = tabla.parent(parent_hilo)
    marca = tabla.item(parent_marca)["text"]

    if not messagebox.askyesno("Confirmar", f"¿Eliminar {marca} / {hilo} / {color} / {codigo}?"):
        return

    conn = get_conn()
    anterior = conn.execute("""
        SELECT * FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (marca, hilo, codigo, color)).fetchone()

    conn.execute("""
        DELETE FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (marca, hilo, codigo, color))

    if anterior:
        registrar_movimiento(
            "ELIMINACION",
            marca=marca,
            hilo=hilo,
            color=anterior.get("color"),
            codigo=codigo,
            stock_anterior=anterior.get("stock"),
            stock_nuevo=0,
            cantidad=-(int(anterior.get("stock") or 0)),
            motivo="Producto eliminado del almacén",
            conn=conn
        )

    conn.commit()
    conn.close()
    refrescar_tabla()
    set_status("Producto eliminado correctamente")
    messagebox.showinfo("Correcto", "Producto eliminado")


def doble_click_editar(event):
    item = tabla.identify_row(event.y)
    columna = tabla.identify_column(event.x)
    if columna == "#1":
        return
    if not item:
        return

    tabla.selection_set(item)
    tabla.focus(item)
    item_data = tabla.item(item)
    if not item_data["values"]:
        return

    # #0 árbol | #1 hilo | #2 color | #3 código | #4 stock | #5 barras | #6 costo | #7 precio | #8 volumétrico | #9 tipo
    if columna == "#4":
        editar_celda(3, "stock")
    elif columna == "#5":
        editar_celda(4, "codigo_barras")
    elif columna == "#6":
        editar_celda(5, "costo_neto")
    elif columna == "#7":
        editar_celda(6, "precio")
    elif columna == "#8":
        editar_celda(7, "volumetrico")


def editar_celda(columna, campo):
    ensure_almacen_schema()
    item = tabla.focus()
    if not item:
        return

    item_data = tabla.item(item)
    if not item_data["values"]:
        return

    valores_item = item_data["values"]
    if campo == "stock" and len(valores_item) > 8 and "sin inventario" in str(valores_item[8]).lower():
        messagebox.showinfo("No aplica", "Este producto está marcado como item de cotización. No maneja stock físico.")
        return

    global autorizado, editor_activo
    if editor_activo and editor_activo.winfo_exists():
        editor_activo.destroy()

    if not autorizado:
        pwd = simpledialog.askstring("Contraseña", "Contraseña:", show="*")
        if pwd != PASSWORD:
            return
        autorizado = True

    bbox = tabla.bbox(item, f"#{columna + 1}")
    if not bbox:
        return

    x, y, width, height = bbox
    valor_actual = item_data["values"][columna]

    entry = tk.Entry(tabla, font=("Segoe UI", 10), justify="center", bd=1, relief="solid")
    editor_activo = entry
    entry.place(x=x, y=y, width=width, height=height)
    entry.insert(0, str(valor_actual).replace("$", ""))
    entry.focus()
    entry.select_range(0, tk.END)

    def guardar(event=None):
        global editor_activo
        if not entry.winfo_exists():
            return
        nuevo_valor = entry.get().strip()
        if nuevo_valor == "":
            entry.destroy()
            return

        valores = item_data["values"]
        hilo = valores[0]
        color = valores[1]
        codigo = str(valores[2])

        parent_hilo = tabla.parent(item)
        parent_marca = tabla.parent(parent_hilo)
        marca = tabla.item(parent_marca)["text"]

        conn = get_conn()
        anterior = conn.execute("""
            SELECT * FROM productos
            WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
        """, (marca, hilo, codigo, color)).fetchone()

        if campo == "stock":
            try:
                nuevo_valor = int(nuevo_valor)
            except Exception:
                conn.close()
                messagebox.showerror("Error", "Stock inválido")
                return

            estado = "OK" if nuevo_valor >= STOCK_MINIMO else "RESURTIR"
            conn.execute("""
                UPDATE productos
                SET stock=%s, estado=%s
                WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
            """, (nuevo_valor, estado, marca, hilo, codigo, color))

            stock_anterior = int(anterior.get("stock") or 0) if anterior else None
            registrar_movimiento(
                "AJUSTE_STOCK",
                marca=marca,
                hilo=hilo,
                color=color,
                codigo=codigo,
                stock_anterior=stock_anterior,
                stock_nuevo=nuevo_valor,
                cantidad=(nuevo_valor - stock_anterior) if stock_anterior is not None else 0,
                campo="stock",
                valor_anterior=stock_anterior,
                valor_nuevo=nuevo_valor,
                motivo="Edición manual de stock",
                conn=conn
            )
        else:
            if campo == "precio":
                try:
                    nuevo_valor = float(nuevo_valor)
                except Exception:
                    conn.close()
                    messagebox.showerror("Error", "Precio inválido")
                    return
                conn.execute("""
                    UPDATE productos
                    SET precio=%s
                    WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
                """, (nuevo_valor, marca, hilo, codigo, color))

            elif campo == "costo_neto":
                try:
                    nuevo_valor = float(str(nuevo_valor).replace("$", "").replace(",", "."))
                except Exception:
                    conn.close()
                    messagebox.showerror("Error", "Costo inválido")
                    return
                conn.execute("""
                    UPDATE productos
                    SET costo_neto=%s
                    WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
                """, (nuevo_valor, marca, hilo, codigo, color))

            elif campo == "volumetrico":
                try:
                    nuevo_valor = float(str(nuevo_valor).replace(",", "."))
                except Exception:
                    conn.close()
                    messagebox.showerror("Error", "Volumétrico inválido")
                    return
                conn.execute("""
                    UPDATE productos
                    SET volumetrico=%s
                    WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
                """, (nuevo_valor, marca, hilo, codigo, color))

            elif campo == "codigo_barras":
                conn.execute("""
                    UPDATE productos
                    SET codigo_barras=%s
                    WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
                """, (nuevo_valor, marca, hilo, codigo, color))

            registrar_movimiento(
                "CAMBIO_DATO",
                marca=marca,
                hilo=hilo,
                color=color,
                codigo=codigo,
                stock_anterior=anterior.get("stock") if anterior else None,
                stock_nuevo=anterior.get("stock") if anterior else None,
                campo=campo,
                valor_anterior=anterior.get(campo) if anterior and campo in anterior else None,
                valor_nuevo=nuevo_valor,
                motivo=f"Edición manual de {campo}",
                conn=conn
            )

        conn.commit()
        conn.close()
        refrescar_tabla()
        set_status(f"Campo actualizado: {campo}")
        entry.destroy()
        editor_activo = None

    entry.bind("<Return>", guardar)
    entry.bind("<FocusOut>", guardar)
    entry.bind("<Escape>", lambda e: entry.destroy())


def editar_precios_marca():
    ensure_almacen_schema()
    marca = combo_marca.get().strip().upper()
    if not marca:
        messagebox.showerror("Error", "Selecciona una marca")
        return

    pwd = simpledialog.askstring("Contraseña", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    dist = simpledialog.askfloat("Distribuidor", f"Precio distribuidor para {marca}:")
    venta = simpledialog.askfloat("Venta", f"Precio venta para {marca}:")
    if dist is None or venta is None:
        return

    conn = get_conn()
    anterior = conn.execute("""
        SELECT distribuidor, venta FROM precios WHERE marca=%s
    """, (marca,)).fetchone()

    conn.execute("""
        INSERT INTO precios(marca, distribuidor, venta)
        VALUES (%s,%s,%s)
        ON CONFLICT(marca)
        DO UPDATE SET
            distribuidor=excluded.distribuidor,
            venta=excluded.venta
    """, (marca, dist, venta))

    registrar_movimiento(
        "CAMBIO_PRECIO_MARCA",
        marca=marca,
        campo="precios_marca",
        valor_anterior=(f"costo={anterior.get('distribuidor')}, venta={anterior.get('venta')}" if anterior else "sin precio previo"),
        valor_nuevo=f"costo={dist}, venta={venta}",
        motivo="Cambio de precios generales por marca",
        conn=conn
    )

    conn.commit()
    conn.close()
    refrescar_tabla()
    set_status(f"Precios actualizados para la marca {marca}")


def asignar_volumetrico_hilo():
    ensure_almacen_schema()
    marca = combo_marca.get().strip().upper()
    hilo = entry_hilo.get().strip().upper()

    if not marca or not hilo:
        messagebox.showerror("Error", "Selecciona una marca y escribe el hilo")
        return

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    if pwd != PASSWORD:
        messagebox.showerror("Error", "Contraseña incorrecta")
        return

    vol = simpledialog.askfloat(
        "Peso volumétrico",
        f"Peso volumétrico para {marca} / {hilo}:",
        minvalue=0.01
    )
    if vol is None:
        return

    conn = get_conn()
    anteriores = conn.execute("""
        SELECT * FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchall()

    conn.execute("""
        UPDATE productos
        SET volumetrico=%s
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (vol, marca, hilo))

    for ant in anteriores:
        registrar_movimiento(
            "CAMBIO_DATO_MASIVO",
            marca=ant.get("marca"),
            hilo=ant.get("hilo"),
            color=ant.get("color"),
            codigo=ant.get("codigo"),
            stock_anterior=ant.get("stock"),
            stock_nuevo=ant.get("stock"),
            campo="volumetrico",
            valor_anterior=ant.get("volumetrico"),
            valor_nuevo=vol,
            motivo="Volumétrico aplicado por hilo",
            conn=conn
        )

    r = conn.execute("""
        SELECT COUNT(*) AS total FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchone()

    afectados = r["total"] if r else 0
    conn.commit()
    conn.close()

    refrescar_tabla()
    set_status(f"Volumétrico actualizado en {afectados} productos")
    messagebox.showinfo("Listo", f"Volumétrico aplicado a {afectados} productos")


def obtener_producto_por_codigo(codigo):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("SELECT * FROM productos WHERE codigo=%s", (codigo,)).fetchone()
    conn.close()
    return r


def actualizar_precio_hilo():
    ensure_almacen_schema()
    marca = combo_marca.get().strip().upper()
    hilo = entry_hilo.get().strip().upper()

    if not marca or not hilo:
        messagebox.showerror("Error", "Selecciona marca y escribe hilo")
        return

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    if pwd != PASSWORD:
        messagebox.showerror("Error", "Contraseña incorrecta")
        return

    nuevo_precio = simpledialog.askfloat(
        "Precio múltiple",
        f"Nuevo precio para {marca} / {hilo}:",
        minvalue=0.01
    )
    if nuevo_precio is None:
        return

    conn = get_conn()
    anteriores = conn.execute("""
        SELECT * FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchall()

    conn.execute("""
        UPDATE productos
        SET precio=%s
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (nuevo_precio, marca, hilo))

    for ant in anteriores:
        registrar_movimiento(
            "CAMBIO_DATO_MASIVO",
            marca=ant.get("marca"),
            hilo=ant.get("hilo"),
            color=ant.get("color"),
            codigo=ant.get("codigo"),
            stock_anterior=ant.get("stock"),
            stock_nuevo=ant.get("stock"),
            campo="precio",
            valor_anterior=ant.get("precio"),
            valor_nuevo=nuevo_precio,
            motivo="Precio aplicado por hilo",
            conn=conn
        )

    r = conn.execute("""
        SELECT COUNT(*) AS total FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchone()

    afectados = r["total"] if r else 0
    conn.commit()
    conn.close()

    refrescar_tabla()
    set_status(f"Precio actualizado en {afectados} productos")
    messagebox.showinfo("Actualizado", f"Se actualizaron {afectados} productos")


def asignar_volumetrico_multiple():
    ensure_almacen_schema()
    marca = simpledialog.askstring("Marca", "Marca (ej: KARINA):")
    if not marca:
        return

    hilo = simpledialog.askstring("Hilo", "Hilo (ej: KOMFY):")
    if not hilo:
        return

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    if pwd != PASSWORD:
        messagebox.showerror("Error", "Contraseña incorrecta")
        return

    nuevo_vol = simpledialog.askfloat(
        "Volumétrico",
        f"Nuevo volumétrico para {marca.upper()} / {hilo.upper()}:",
        minvalue=0.01
    )
    if nuevo_vol is None:
        return

    conn = get_conn()
    anteriores = conn.execute("""
        SELECT * FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchall()

    conn.execute("""
        UPDATE productos
        SET volumetrico=%s
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (nuevo_vol, marca, hilo))

    for ant in anteriores:
        registrar_movimiento(
            "CAMBIO_DATO_MASIVO",
            marca=ant.get("marca"),
            hilo=ant.get("hilo"),
            color=ant.get("color"),
            codigo=ant.get("codigo"),
            stock_anterior=ant.get("stock"),
            stock_nuevo=ant.get("stock"),
            campo="volumetrico",
            valor_anterior=ant.get("volumetrico"),
            valor_nuevo=nuevo_vol,
            motivo="Volumétrico múltiple por marca/hilo",
            conn=conn
        )

    r = conn.execute("""
        SELECT COUNT(*) AS total FROM productos
        WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)
    """, (marca, hilo)).fetchone()

    afectados = r["total"] if r else 0
    conn.commit()
    conn.close()

    refrescar_tabla()
    set_status(f"Volumétrico múltiple actualizado en {afectados} productos")
    messagebox.showinfo("Actualizado", f"Se actualizaron {afectados} productos")



def obtener_item_seleccionado():
    item = tabla.focus()
    if not item:
        messagebox.showinfo("Selecciona un producto", "Selecciona primero un producto de la tabla.")
        return None
    item_data = tabla.item(item)
    if not item_data["values"]:
        messagebox.showinfo("Selecciona un producto", "Selecciona una fila de producto, no una marca o hilo.")
        return None
    valores = item_data["values"]
    hilo = valores[0]
    color = valores[1]
    codigo = str(valores[2])
    parent_hilo = tabla.parent(item)
    parent_marca = tabla.parent(parent_hilo)
    marca = tabla.item(parent_marca)["text"]
    return marca, hilo, color, codigo


def marcar_item_sin_inventario():
    datos = obtener_item_seleccionado()
    if not datos:
        return
    marca, hilo, color, codigo = datos

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    if not messagebox.askyesno(
        "Confirmar",
        "Esto convertirá el producto seleccionado en ITEM DE COTIZACIÓN.\n\n"
        "- Su stock físico se pondrá en 0.\n"
        "- No contará en ganancia del almacén.\n"
        "- Sí aparecerá en ventas/cotizaciones y en la búsqueda de productos.\n"
        "- No se sugerirá como resurtido de proveedor.\n"
        "- Se podrá vender sin descontar stock físico.\n\n"
        f"¿Convertir {marca} / {hilo} / {color} / {codigo}?"
    ):
        return

    conn = get_conn()
    anterior = conn.execute("""
        SELECT * FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (marca, hilo, codigo, color)).fetchone()

    stock_anterior = int(anterior.get("stock") or 0) if anterior else 0
    conn.execute("""
        UPDATE productos
        SET es_inventariable=FALSE,
            tipo_producto='ITEM',
            stock=0,
            estado='ITEM'
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (marca, hilo, codigo, color))

    registrar_movimiento(
        "CAMBIO_A_ITEM_COTIZACION",
        marca=marca,
        hilo=hilo,
        color=color,
        codigo=codigo,
        stock_anterior=stock_anterior,
        stock_nuevo=0,
        cantidad=-stock_anterior,
        campo="tipo_producto",
        valor_anterior="INVENTARIO",
        valor_nuevo="ITEM",
        motivo="Convertido a item de cotización para vender/cotizar sin afectar cálculos de almacén",
        conn=conn
    )
    conn.commit()
    conn.close()
    refrescar_tabla()
    set_status("Producto convertido a item de cotización")


def marcar_como_inventario():
    datos = obtener_item_seleccionado()
    if not datos:
        return
    marca, hilo, color, codigo = datos

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    stock = simpledialog.askinteger(
        "Stock inicial",
        f"¿Con cuánto stock físico quieres dejar {marca} / {hilo} / {color} / {codigo}?",
        minvalue=0
    )
    if stock is None:
        return

    estado = "OK" if stock >= STOCK_MINIMO else "RESURTIR"
    conn = get_conn()
    anterior = conn.execute("""
        SELECT * FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (marca, hilo, codigo, color)).fetchone()

    stock_anterior = int(anterior.get("stock") or 0) if anterior else 0
    conn.execute("""
        UPDATE productos
        SET es_inventariable=TRUE,
            tipo_producto='INVENTARIO',
            stock=%s,
            estado=%s
        WHERE marca=%s AND hilo=%s AND codigo=%s AND color=%s
    """, (stock, estado, marca, hilo, codigo, color))

    registrar_movimiento(
        "CAMBIO_A_INVENTARIO",
        marca=marca,
        hilo=hilo,
        color=color,
        codigo=codigo,
        stock_anterior=stock_anterior,
        stock_nuevo=stock,
        cantidad=stock - stock_anterior,
        campo="tipo_producto",
        valor_anterior="ITEM",
        valor_nuevo="INVENTARIO",
        motivo="Convertido a producto de inventario físico",
        conn=conn
    )
    conn.commit()
    conn.close()
    refrescar_tabla()
    set_status("Producto convertido a inventario")


def ver_movimientos():
    ensure_almacen_schema()

    win = tk.Toplevel(root)
    win.title("Movimientos de almacén")
    win.geometry("1380x720")
    win.configure(bg="#EEF3F8")

    style = ttk.Style(win)
    style.configure("Mov.Treeview", rowheight=32, font=("Segoe UI", 10), background="white", fieldbackground="white")
    style.configure("Mov.Treeview.Heading", font=("Segoe UI", 10, "bold"))

    header = tk.Frame(win, bg="#1F3A5F", height=72)
    header.pack(fill="x")
    tk.Label(header, text="Historial de movimientos", font=("Segoe UI", 18, "bold"), fg="white", bg="#1F3A5F").pack(anchor="w", padx=18, pady=(12, 0))
    tk.Label(header, text="Consulta ajustes, altas, eliminaciones y cambios realizados en almacén.", font=("Segoe UI", 10), fg="#D9E6F2", bg="#1F3A5F").pack(anchor="w", padx=18, pady=(0, 12))

    body = tk.Frame(win, bg="#EEF3F8")
    body.pack(fill="both", expand=True, padx=16, pady=16)

    filtros = tk.Frame(body, bg="white", bd=1, relief="solid")
    filtros.pack(fill="x", pady=(0, 12))
    tk.Label(filtros, text="Buscar:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(14, 6), pady=12)
    entry = tk.Entry(filtros, width=38, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#D1D9E6")
    entry.pack(side="left", padx=(0, 8), pady=10)

    info = tk.Label(filtros, text="", bg="white", fg="#5E718D", font=("Segoe UI", 10))
    info.pack(side="right", padx=14)

    tabla_wrap = tk.Frame(body, bg="white", bd=1, relief="solid")
    tabla_wrap.pack(fill="both", expand=True)

    columnas = (
        "Fecha", "Tipo", "Marca", "Hilo", "Color", "Código",
        "Stock anterior", "Stock nuevo", "Cantidad", "Campo",
        "Antes", "Después", "Motivo"
    )

    tv = ttk.Treeview(tabla_wrap, columns=columnas, show="headings", style="Mov.Treeview")
    for col in columnas:
        tv.heading(col, text=col)
        ancho = 120
        if col in ("Antes", "Después", "Motivo"):
            ancho = 180
        elif col == "Fecha":
            ancho = 160
        elif col in ("Tipo", "Marca", "Hilo"):
            ancho = 130
        tv.column(col, width=ancho, anchor="center")

    scroll_y = ttk.Scrollbar(tabla_wrap, orient="vertical", command=tv.yview)
    scroll_x = ttk.Scrollbar(tabla_wrap, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    tv.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))
    scroll_x.pack(side="bottom", fill="x")
    scroll_y.pack(side="right", fill="y")

    tv.tag_configure("salida", background="#FFF1F2")
    tv.tag_configure("ajuste", background="#F3F8FF")
    tv.tag_configure("alta", background="#EEF9F1")
    tv.tag_configure("cambio", background="#FFFBEA")

    def cargar():
        filtro = entry.get().strip()
        tv.delete(*tv.get_children())
        conn = get_conn()
        if filtro:
            like = f"%{filtro}%"
            rows = conn.execute("""
                SELECT fecha, tipo, marca, hilo, color, codigo,
                       stock_anterior, stock_nuevo, cantidad, campo,
                       valor_anterior, valor_nuevo, motivo
                FROM movimientos_almacen
                WHERE marca ILIKE %s OR hilo ILIKE %s OR color ILIKE %s
                   OR codigo ILIKE %s OR tipo ILIKE %s OR campo ILIKE %s
                ORDER BY fecha DESC
                LIMIT 1000
            """, (like, like, like, like, like, like)).fetchall()
        else:
            rows = conn.execute("""
                SELECT fecha, tipo, marca, hilo, color, codigo,
                       stock_anterior, stock_nuevo, cantidad, campo,
                       valor_anterior, valor_nuevo, motivo
                FROM movimientos_almacen
                ORDER BY fecha DESC
                LIMIT 1000
            """).fetchall()
        conn.close()

        for r in rows:
            fecha = r.get("fecha")
            if hasattr(fecha, "strftime"):
                fecha = fecha.strftime("%Y-%m-%d %H:%M:%S")
            tipo = r.get("tipo") or ""
            tag = "cambio"
            if "SALIDA" in tipo:
                tag = "salida"
            elif "AJUSTE" in tipo:
                tag = "ajuste"
            elif "ALTA" in tipo:
                tag = "alta"
            elif "CAMBIO" in tipo:
                tag = "cambio"
            tv.insert("", "end", tags=(tag,), values=(
                fecha or "",
                tipo,
                r.get("marca") or "",
                r.get("hilo") or "",
                r.get("color") or "",
                r.get("codigo") or "",
                r.get("stock_anterior") if r.get("stock_anterior") is not None else "",
                r.get("stock_nuevo") if r.get("stock_nuevo") is not None else "",
                r.get("cantidad") if r.get("cantidad") is not None else "",
                r.get("campo") or "",
                r.get("valor_anterior") or "",
                r.get("valor_nuevo") or "",
                r.get("motivo") or ""
            ))
        info.config(text=f"{len(rows)} movimientos mostrados")

    ttk.Button(filtros, text="Actualizar", command=cargar).pack(side="left", padx=6)
    ttk.Button(filtros, text="Limpiar", command=lambda: (entry.delete(0, tk.END), cargar())).pack(side="left", padx=4)
    entry.bind("<Return>", lambda e: cargar())
    cargar()


# ================= REPORTES Y ESTADÍSTICAS =================
def _clave_producto(marca, hilo, color, codigo):
    return (
        str(marca or "").upper().strip(),
        str(hilo or "").upper().strip(),
        str(color or "").upper().strip(),
        str(codigo or "").upper().strip(),
    )


def _int_seguro(valor, default=0):
    try:
        if valor is None or valor == "":
            return default
        return int(float(valor))
    except Exception:
        return default


def _cantidad_vendida_movimiento(mov):
    cantidad = mov.get("cantidad")
    if cantidad is not None:
        return abs(_int_seguro(cantidad))

    anterior = mov.get("stock_anterior")
    nuevo = mov.get("stock_nuevo")
    if anterior is not None and nuevo is not None:
        return max(0, _int_seguro(anterior) - _int_seguro(nuevo))

    return 0


def cargar_estadisticas_ventas(marca=None, dias=DIAS_ANALISIS_COMPRA):
    """
    Une inventario actual + historial de SALIDA_STOCK.
    Sirve para estadísticas y resurtido sugerido.
    """
    ensure_almacen_schema()

    dias = max(1, _int_seguro(dias, DIAS_ANALISIS_COMPRA))
    marca = (marca or "").strip().upper()
    fecha_inicio = datetime.now() - timedelta(days=dias)
    fecha_30 = datetime.now() - timedelta(days=30)
    fecha_7 = datetime.now() - timedelta(days=7)

    productos = [p for p in obtener_productos() if es_inventariable_producto(p)]
    if marca:
        productos = [p for p in productos if str(p.get("marca") or "").upper() == marca]

    ventas = {}
    conn = get_conn()
    try:
        if marca:
            movs = conn.execute("""
                SELECT marca, hilo, color, codigo, fecha, cantidad, stock_anterior, stock_nuevo
                FROM movimientos_almacen
                WHERE tipo='SALIDA_STOCK'
                  AND fecha >= %s
                  AND UPPER(marca)=UPPER(%s)
            """, (fecha_inicio, marca)).fetchall()
        else:
            movs = conn.execute("""
                SELECT marca, hilo, color, codigo, fecha, cantidad, stock_anterior, stock_nuevo
                FROM movimientos_almacen
                WHERE tipo='SALIDA_STOCK'
                  AND fecha >= %s
            """, (fecha_inicio,)).fetchall()
    finally:
        conn.close()

    for m in movs:
        key = _clave_producto(m.get("marca"), m.get("hilo"), m.get("color"), m.get("codigo"))
        ventas.setdefault(key, {"vendidos_periodo": 0, "vendidos_30": 0, "vendidos_7": 0})
        cant = _cantidad_vendida_movimiento(m)
        fecha = m.get("fecha")

        ventas[key]["vendidos_periodo"] += cant
        if fecha and fecha >= fecha_30:
            ventas[key]["vendidos_30"] += cant
        if fecha and fecha >= fecha_7:
            ventas[key]["vendidos_7"] += cant

    resultado = []
    for p in productos:
        key = _clave_producto(p.get("marca"), p.get("hilo"), p.get("color"), p.get("codigo"))
        v = ventas.get(key, {"vendidos_periodo": 0, "vendidos_30": 0, "vendidos_7": 0})

        costo_unitario, venta_unitaria, valor_costo, valor_venta, ganancia = valores_financieros_producto(p)
        stock_actual = _int_seguro(p.get("stock"))

        promedio_periodo = v["vendidos_periodo"] / dias
        promedio_30 = v["vendidos_30"] / 30
        promedio_7 = v["vendidos_7"] / 7

        # Constante de venta: usa la mayor señal reciente para no quedarte corto.
        constante_venta = max(promedio_periodo, promedio_30, promedio_7)

        if constante_venta > 0:
            dias_cobertura = stock_actual / constante_venta
        else:
            dias_cobertura = None

        resultado.append({
            "marca": p.get("marca") or "",
            "hilo": p.get("hilo") or "",
            "color": p.get("color") or "",
            "codigo": p.get("codigo") or "",
            "stock": stock_actual,
            "estado": p.get("estado") or "",
            "costo_unitario": costo_unitario,
            "venta_unitaria": venta_unitaria,
            "ganancia_unitaria": venta_unitaria - costo_unitario,
            "valor_costo": valor_costo,
            "valor_venta": valor_venta,
            "ganancia_inventario": ganancia,
            "vendidos_periodo": v["vendidos_periodo"],
            "vendidos_30": v["vendidos_30"],
            "vendidos_7": v["vendidos_7"],
            "promedio_periodo": promedio_periodo,
            "promedio_30": promedio_30,
            "promedio_7": promedio_7,
            "constante_venta": constante_venta,
            "dias_cobertura": dias_cobertura,
        })

    resultado.sort(key=lambda r: (r["marca"], r["hilo"], r["color"], r["codigo"]))
    return resultado


def calcular_ganancia_por_marca():
    productos = obtener_productos()
    resumen = {}

    for p in productos:
        marca = p.get("marca") or "SIN MARCA"
        resumen.setdefault(marca, {
            "tonos": 0,
            "items_sin_inventario": 0,
            "stock": 0,
            "valor_costo": 0.0,
            "valor_venta": 0.0,
            "ganancia": 0.0,
        })

        inv = es_inventariable_producto(p)
        _, _, valor_costo, valor_venta, ganancia = valores_financieros_producto(p)
        if inv:
            resumen[marca]["tonos"] += 1
            resumen[marca]["stock"] += _int_seguro(p.get("stock"))
        else:
            resumen[marca]["items_sin_inventario"] += 1
        resumen[marca]["valor_costo"] += valor_costo
        resumen[marca]["valor_venta"] += valor_venta
        resumen[marca]["ganancia"] += ganancia

    filas = []
    for marca, r in resumen.items():
        margen = (r["ganancia"] / r["valor_venta"] * 100) if r["valor_venta"] else 0
        filas.append({
            "marca": marca,
            "hilo": "TOTAL MARCA",
            **r,
            "margen": margen,
        })

    filas.sort(key=lambda x: x["ganancia"], reverse=True)
    return filas


def calcular_ganancia_por_marca_hilo():
    """Resumen financiero agrupado por marca e hilo, sin inflar con items de cotización."""
    productos = obtener_productos()
    resumen = {}

    for p in productos:
        marca = p.get("marca") or "SIN MARCA"
        hilo = p.get("hilo") or "SIN HILO"
        key = (marca, hilo)
        resumen.setdefault(key, {
            "marca": marca,
            "hilo": hilo,
            "tonos": 0,
            "items_sin_inventario": 0,
            "stock": 0,
            "valor_costo": 0.0,
            "valor_venta": 0.0,
            "ganancia": 0.0,
        })

        inv = es_inventariable_producto(p)
        _, _, valor_costo, valor_venta, ganancia = valores_financieros_producto(p)
        if inv:
            resumen[key]["tonos"] += 1
            resumen[key]["stock"] += _int_seguro(p.get("stock"))
        else:
            resumen[key]["items_sin_inventario"] += 1
        resumen[key]["valor_costo"] += valor_costo
        resumen[key]["valor_venta"] += valor_venta
        resumen[key]["ganancia"] += ganancia

    filas = []
    for _, r in resumen.items():
        margen = (r["ganancia"] / r["valor_venta"] * 100) if r["valor_venta"] else 0
        filas.append({
            **r,
            "margen": margen,
        })

    filas.sort(key=lambda x: (x["marca"], -x["ganancia"], x["hilo"]))
    return filas


def calcular_ganancia_por_marca_hilo_tree():
    """Regresa marcas con hijos por hilo para mostrar una tabla jerárquica."""
    marcas = calcular_ganancia_por_marca()
    hilos = calcular_ganancia_por_marca_hilo()
    hijos = {}
    for h in hilos:
        hijos.setdefault(h["marca"], []).append(h)
    return marcas, hijos



def construir_recomendacion_compra(marca=None, dias=DIAS_ANALISIS_COMPRA, cobertura=None, modo=None, presupuesto=None):
    """
    Recomendación enfocada en ESTADÍSTICAS REALES DE VENTA.

    Ya no trabaja con un objetivo fijo de cobertura ni con modo conservador/agresivo.
    La compra se sugiere comparando:
    - lo vendido en 7 días
    - lo vendido en 30 días
    - lo vendido en el periodo elegido
    - el stock actual

    Excluye items de cotización para no comprar paquetes/combos como si fueran material físico.
    """
    dias = max(1, _int_seguro(dias, DIAS_ANALISIS_COMPRA))
    presupuesto = to_float(presupuesto, 0.0)

    stats = cargar_estadisticas_ventas(marca=marca, dias=dias)
    recomendaciones = []

    for r in stats:
        stock = _int_seguro(r.get("stock"), 0)
        vendidos = _int_seguro(r.get("vendidos_periodo"), 0)
        vendidos_30 = _int_seguro(r.get("vendidos_30"), 0)
        vendidos_7 = _int_seguro(r.get("vendidos_7"), 0)

        # Si no hay ventas, no se recomienda compra aquí.
        # Esto evita que el botón se base en objetivos o mínimos fijos.
        if vendidos <= 0 and vendidos_30 <= 0 and vendidos_7 <= 0:
            continue

        promedio_periodo = vendidos / dias if dias else 0
        ritmo_30 = vendidos_30
        ritmo_periodo_30 = math.ceil(promedio_periodo * 30) if promedio_periodo > 0 else 0
        ritmo_7_proyectado = vendidos_7 * 4

        # Señal principal: lo que realmente se está vendiendo más recientemente.
        base_venta = max(ritmo_30, ritmo_periodo_30, ritmo_7_proyectado, vendidos_7)
        if base_venta <= 0:
            continue

        # Tendencia: compara el ritmo de los últimos 7 días contra el de 30 días.
        if vendidos_30 > 0:
            tendencia = (vendidos_7 / 7) / (vendidos_30 / 30)
        elif vendidos_7 > 0:
            tendencia = 2.0
        else:
            tendencia = 1.0

        motivo = []
        prioridad = "MEDIA"
        accion = "Comprar por rotación"
        comprar = 0
        base_txt = "Ventas reales"

        if stock <= 0:
            prioridad = "URGENTE"
            accion = "Comprar primero"
            # Si no hay stock, compra al menos lo equivalente al movimiento reciente.
            comprar = max(vendidos_7, math.ceil(vendidos_30 / 2), math.ceil(base_venta / 2), MINIMO_COMPRA_PIEZAS)
            motivo.append("Sin stock y sí tiene ventas registradas")
            base_txt = "Reposición por falta de stock"

        elif vendidos_7 > 0 and stock <= vendidos_7:
            prioridad = "URGENTE"
            accion = "Comprar primero"
            comprar = max((vendidos_7 * 2) - stock, MINIMO_COMPRA_PIEZAS)
            motivo.append("El stock actual no alcanza ni lo vendido en los últimos 7 días")
            base_txt = "Últimos 7 días"

        elif vendidos_30 > 0 and stock <= math.ceil(vendidos_30 * 0.50):
            prioridad = "ALTA"
            accion = "Comprar pronto"
            comprar = max(math.ceil(vendidos_30 - stock), MINIMO_COMPRA_PIEZAS)
            motivo.append("Stock menor a la mitad de lo vendido en 30 días")
            base_txt = "Últimos 30 días"

        elif vendidos_30 > 0 and stock <= vendidos_30:
            prioridad = "MEDIA"
            accion = "Comprar esta vuelta"
            comprar = max(math.ceil(vendidos_30 - stock), MINIMO_COMPRA_PIEZAS)
            motivo.append("Stock menor o igual a lo vendido en 30 días")
            base_txt = "Últimos 30 días"

        elif tendencia >= 1.4 and vendidos_7 > 0 and stock <= base_venta:
            prioridad = "MEDIA"
            accion = "Comprar por tendencia"
            comprar = max(math.ceil(base_venta - stock), MINIMO_COMPRA_PIEZAS)
            motivo.append("Venta reciente acelerada contra el promedio de 30 días")
            base_txt = "Tendencia reciente"

        else:
            # Se vendió, pero el stock todavía alcanza bien según la estadística actual.
            continue

        if comprar < MINIMO_COMPRA_PIEZAS:
            continue

        if tendencia >= 1.4 and "Venta reciente acelerada contra el promedio de 30 días" not in motivo:
            motivo.append("Venta reciente acelerada")
            if prioridad == "MEDIA":
                prioridad = "ALTA"

        if r["ganancia_unitaria"] <= 0:
            motivo.append("Revisar precio/costo: ganancia baja o negativa")

        constante = r["constante_venta"]
        if vendidos_7 >= 7 or constante >= 1:
            rotacion = "🔥 Alta"
        elif vendidos_30 >= 5 or constante >= 0.25:
            rotacion = "✅ Media"
        elif vendidos > 0:
            rotacion = "🐢 Lenta"
        else:
            rotacion = "💤 Sin venta"

        dias_al_ritmo = None
        if constante > 0:
            dias_al_ritmo = stock / constante

        prioridad_peso = {"URGENTE": 4, "ALTA": 3, "MEDIA": 2, "NORMAL": 1}.get(prioridad, 1)
        score = (
            prioridad_peso * 1000
            + vendidos_7 * 30
            + vendidos_30 * 10
            + vendidos * 4
            + max(0, r["ganancia_unitaria"]) * 0.5
            + max(0, tendencia) * 20
        )

        recomendaciones.append({
            **r,
            "base_venta": base_txt,
            "tendencia": tendencia,
            "dias_al_ritmo": dias_al_ritmo,
            "comprar": int(comprar),
            "prioridad": prioridad,
            "accion": accion,
            "rotacion": rotacion,
            "motivo": " • ".join(motivo),
            "score": score,
            "costo_compra": int(comprar) * r["costo_unitario"],
            "venta_potencial": int(comprar) * r["venta_unitaria"],
            "ganancia_potencial": int(comprar) * r["ganancia_unitaria"],
            "incluido_presupuesto": True,
        })

    recomendaciones.sort(key=lambda r: (
        {"URGENTE": 0, "ALTA": 1, "MEDIA": 2, "NORMAL": 3}.get(r["prioridad"], 9),
        -r["score"],
        r["marca"],
        r["hilo"],
        r["color"],
    ))

    if presupuesto > 0:
        restante = presupuesto
        filtradas = []
        for r in recomendaciones:
            costo_unit = to_float(r["costo_unitario"], 0)
            if costo_unit <= 0:
                r["incluido_presupuesto"] = True
                filtradas.append(r)
                continue

            costo_total = r["comprar"] * costo_unit
            if costo_total <= restante:
                r["incluido_presupuesto"] = True
                restante -= costo_total
                filtradas.append(r)
            else:
                cantidad_posible = int(restante // costo_unit)
                if cantidad_posible >= MINIMO_COMPRA_PIEZAS and r["prioridad"] in ("URGENTE", "ALTA"):
                    r = dict(r)
                    r["comprar"] = cantidad_posible
                    r["costo_compra"] = cantidad_posible * r["costo_unitario"]
                    r["venta_potencial"] = cantidad_posible * r["venta_unitaria"]
                    r["ganancia_potencial"] = cantidad_posible * r["ganancia_unitaria"]
                    r["motivo"] += " • Ajustado al presupuesto"
                    r["incluido_presupuesto"] = True
                    restante -= r["costo_compra"]
                    filtradas.append(r)
                else:
                    # Si no alcanza el presupuesto, no lo metemos para respetar el monto.
                    pass
        recomendaciones = filtradas

    return recomendaciones

def _crear_ventana_reporte(titulo, subtitulo=None, size="1300x720"):
    win = tk.Toplevel(root)
    win.title(titulo)
    win.geometry(size)
    win.configure(bg="#EEF3F8")

    header = tk.Frame(win, bg="#1F3A5F", height=76)
    header.pack(fill="x")
    tk.Label(header, text=titulo, font=("Segoe UI", 18, "bold"), fg="white", bg="#1F3A5F").pack(anchor="w", padx=18, pady=(12, 0))
    if subtitulo:
        tk.Label(header, text=subtitulo, font=("Segoe UI", 10), fg="#D9E6F2", bg="#1F3A5F").pack(anchor="w", padx=18, pady=(0, 12))

    body = tk.Frame(win, bg="#EEF3F8")
    body.pack(fill="both", expand=True, padx=16, pady=16)
    return win, body


def ver_ganancia_por_marca():
    """Reporte de ganancia con dos vistas: total por marca y detalle por marca/hilo."""
    vista_actual = {"modo": "MARCA_HILO"}  # MARCA | MARCA_HILO
    marcas, hilos_por_marca = calcular_ganancia_por_marca_hilo_tree()

    win, body = _crear_ventana_reporte(
        "Ganancia por marca e hilo",
        "Resumen financiero del inventario físico. Los items de cotización no inflan el almacén.",
        "1420x760"
    )

    total_costo = sum(r["valor_costo"] for r in marcas)
    total_venta = sum(r["valor_venta"] for r in marcas)
    total_ganancia = sum(r["ganancia"] for r in marcas)
    total_hilos = sum(len(v) for v in hilos_por_marca.values())

    cards = tk.Frame(body, bg="#EEF3F8")
    cards.pack(fill="x", pady=(0, 10))
    crear_card(cards, "Costo total", money(total_costo), "#285A84")
    crear_card(cards, "Venta total", money(total_venta), "#D08B00")
    crear_card(cards, "Ganancia total", money(total_ganancia), "#16A34A")
    crear_card(cards, "Marcas / hilos", f"{len(marcas)} / {total_hilos}", "#8E5AF7")

    filtros = tk.Frame(body, bg="white", bd=1, relief="solid")
    filtros.pack(fill="x", pady=(0, 10))

    tk.Label(filtros, text="Buscar marca o hilo:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(12, 6), pady=12)
    buscar_entry = tk.Entry(filtros, width=28, font=("Segoe UI", 10))
    buscar_entry.pack(side="left", padx=(0, 10), pady=12)

    info = tk.Label(filtros, text="", bg="white", fg="#5E718D", font=("Segoe UI", 10))
    info.pack(side="right", padx=14)

    tabla_frame = tk.Frame(body, bg="white", bd=1, relief="solid")
    tabla_frame.pack(fill="both", expand=True)

    columnas = ("Hilo", "Tonos inv.", "Items cot.", "Stock", "Valor costo", "Valor venta", "Ganancia", "Margen")
    tv = ttk.Treeview(tabla_frame, columns=columnas, show="tree headings")
    tv.heading("#0", text="Marca")
    tv.column("#0", width=230, anchor="w")

    anchos = {
        "Hilo": 220,
        "Tonos inv.": 95,
        "Items cot.": 95,
        "Stock": 95,
        "Valor costo": 135,
        "Valor venta": 135,
        "Ganancia": 135,
        "Margen": 90,
    }
    for col in columnas:
        tv.heading(col, text=col)
        tv.column(col, width=anchos.get(col, 120), anchor="center")
    tv.column("Hilo", anchor="w")
    for col in ("Valor costo", "Valor venta", "Ganancia"):
        tv.column(col, anchor="e")

    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tv.yview)
    scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    tv.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
    scroll_y.grid(row=0, column=1, sticky="ns", pady=10)
    scroll_x.grid(row=1, column=0, sticky="ew", padx=(10, 0))
    tabla_frame.grid_rowconfigure(0, weight=1)
    tabla_frame.grid_columnconfigure(0, weight=1)

    tv.tag_configure("marca_pos", background="#DCE8F7", font=("Segoe UI", 10, "bold"), foreground="#21354D")
    tv.tag_configure("marca_neg", background="#FFE2E2", font=("Segoe UI", 10, "bold"), foreground="#7A2020")
    tv.tag_configure("hilo_pos", background="#EEF9F1")
    tv.tag_configure("hilo_neg", background="#FFF0F0")
    tv.tag_configure("hilo_neutro", background="white")

    def fila_valores(r):
        return (
            r.get("hilo") or "",
            r.get("tonos", 0),
            r.get("items_sin_inventario", 0),
            r.get("stock", 0),
            money(r.get("valor_costo", 0)),
            money(r.get("valor_venta", 0)),
            money(r.get("ganancia", 0)),
            f"{r.get('margen', 0):.1f}%"
        )

    def pasa_filtro(r, texto):
        if not texto:
            return True
        texto = texto.upper()
        return texto in str(r.get("marca", "")).upper() or texto in str(r.get("hilo", "")).upper()

    def cargar():
        nonlocal marcas, hilos_por_marca
        marcas, hilos_por_marca = calcular_ganancia_por_marca_hilo_tree()
        tv.delete(*tv.get_children())
        texto = buscar_entry.get().strip()
        modo = vista_actual["modo"]
        total_filas = 0

        if modo == "MARCA":
            filas = [r for r in marcas if pasa_filtro(r, texto)]
            filas.sort(key=lambda r: r["ganancia"], reverse=True)
            for r in filas:
                tag = "marca_pos" if r["ganancia"] >= 0 else "marca_neg"
                tv.insert("", "end", text=r["marca"], values=fila_valores(r), tags=(tag,))
            total_filas = len(filas)
            info.config(text=f"Vista por marca • {total_filas} marcas")
            return

        # Vista marca + hilo: la marca queda como encabezado y cada hilo como detalle.
        for marca_r in marcas:
            hijos = [h for h in hilos_por_marca.get(marca_r["marca"], []) if pasa_filtro(h, texto) or pasa_filtro(marca_r, texto)]
            if texto and not hijos and not pasa_filtro(marca_r, texto):
                continue
            tag_marca = "marca_pos" if marca_r["ganancia"] >= 0 else "marca_neg"
            parent = tv.insert("", "end", text=marca_r["marca"], values=fila_valores(marca_r), tags=(tag_marca,), open=True)
            total_filas += 1
            for h in hijos:
                tag = "hilo_pos" if h["ganancia"] > 0 else ("hilo_neg" if h["ganancia"] < 0 else "hilo_neutro")
                tv.insert(parent, "end", text="", values=fila_valores(h), tags=(tag,))
                total_filas += 1
        info.config(text=f"Vista marca + hilo • {total_filas} filas")

    def cambiar_vista(modo):
        vista_actual["modo"] = modo
        btn_marca.config(bg="#2F6FED" if modo == "MARCA" else "#F4F7FB", fg="white" if modo == "MARCA" else "#27415D")
        btn_hilo.config(bg="#2F6FED" if modo == "MARCA_HILO" else "#F4F7FB", fg="white" if modo == "MARCA_HILO" else "#27415D")
        cargar()

    btn_marca = tk.Button(filtros, text="Solo marcas", command=lambda: cambiar_vista("MARCA"), bg="#F4F7FB", fg="#27415D", relief="flat", padx=12, pady=6, cursor="hand2")
    btn_marca.pack(side="left", padx=4)
    btn_hilo = tk.Button(filtros, text="Marca + hilo", command=lambda: cambiar_vista("MARCA_HILO"), bg="#2F6FED", fg="white", relief="flat", padx=12, pady=6, cursor="hand2")
    btn_hilo.pack(side="left", padx=4)
    tk.Button(filtros, text="Actualizar", command=cargar, bg="#16A34A", fg="white", relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
    tk.Button(filtros, text="Limpiar", command=lambda: (buscar_entry.delete(0, tk.END), cargar()), bg="#F4F7FB", fg="#27415D", relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
    buscar_entry.bind("<Return>", lambda e: cargar())
    buscar_entry.bind("<KeyRelease>", lambda e: cargar())

    cargar()


def ver_estadisticas_ventas():
    marca_inicial = (combo_marca.get().strip().upper() if combo_marca is not None else "")
    win, body = _crear_ventana_reporte(
        "Estadísticas de venta por tono",
        "Basado en salidas de stock registradas en el historial de almacén.",
        "1500x760"
    )

    filtros = tk.Frame(body, bg="white", bd=1, relief="solid")
    filtros.pack(fill="x", pady=(0, 10))

    tk.Label(filtros, text="Marca:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(12, 6), pady=12)
    marca_entry = tk.Entry(filtros, width=18, font=("Segoe UI", 10))
    marca_entry.insert(0, marca_inicial)
    marca_entry.pack(side="left", padx=(0, 10), pady=12)

    tk.Label(filtros, text="Días:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 6), pady=12)
    dias_entry = tk.Entry(filtros, width=7, font=("Segoe UI", 10))
    dias_entry.insert(0, str(DIAS_ANALISIS_COMPRA))
    dias_entry.pack(side="left", padx=(0, 10), pady=12)

    info = tk.Label(filtros, text="", bg="white", fg="#5E718D", font=("Segoe UI", 10))
    info.pack(side="right", padx=14)

    tabla_frame = tk.Frame(body, bg="white", bd=1, relief="solid")
    tabla_frame.pack(fill="both", expand=True)

    columnas = (
        "Marca", "Hilo", "Color", "Código", "Stock",
        "Vend. 7d", "Vend. 30d", "Vend. periodo",
        "Constante/día", "Días cobertura", "Gan. unit.", "Gan. inventario"
    )
    tv = ttk.Treeview(tabla_frame, columns=columnas, show="headings")
    for col in columnas:
        tv.heading(col, text=col)
        tv.column(col, width=115, anchor="center")
    tv.column("Marca", width=135, anchor="w")
    tv.column("Hilo", width=130, anchor="w")
    tv.column("Color", width=130, anchor="w")

    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tv.yview)
    scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    tv.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=(10, 0))
    scroll_y.grid(row=0, column=1, sticky="ns", pady=(10, 0))
    scroll_x.grid(row=1, column=0, sticky="ew", padx=(10, 0))
    tabla_frame.grid_rowconfigure(0, weight=1)
    tabla_frame.grid_columnconfigure(0, weight=1)

    tv.tag_configure("urgente", background="#FFF0F0")
    tv.tag_configure("alta", background="#FFFBEA")
    tv.tag_configure("normal", background="white")

    def cargar():
        tv.delete(*tv.get_children())
        marca = marca_entry.get().strip().upper()
        dias = _int_seguro(dias_entry.get(), DIAS_ANALISIS_COMPRA)
        filas = cargar_estadisticas_ventas(marca=marca or None, dias=dias)
        filas.sort(key=lambda r: (r["dias_cobertura"] if r["dias_cobertura"] is not None else 999999, -r["vendidos_periodo"]))

        total_vendido = sum(r["vendidos_periodo"] for r in filas)
        con_venta = sum(1 for r in filas if r["vendidos_periodo"] > 0)
        info.config(text=f"{len(filas)} tonos • {con_venta} con venta • {total_vendido} piezas vendidas")

        for r in filas:
            cobertura = "Sin venta" if r["dias_cobertura"] is None else f"{r['dias_cobertura']:.1f}"
            tag = "normal"
            if r["dias_cobertura"] is not None and r["dias_cobertura"] <= 15:
                tag = "urgente"
            elif r["dias_cobertura"] is not None and r["dias_cobertura"] <= 30:
                tag = "alta"

            tv.insert("", "end", tags=(tag,), values=(
                r["marca"],
                r["hilo"],
                r["color"],
                r["codigo"],
                r["stock"],
                r["vendidos_7"],
                r["vendidos_30"],
                r["vendidos_periodo"],
                f"{r['constante_venta']:.2f}",
                cobertura,
                money(r["ganancia_unitaria"]),
                money(r["ganancia_inventario"]),
            ))

    tk.Button(filtros, text="Actualizar", command=cargar, bg="#2F6FED", fg="white", relief="flat", padx=14, pady=6, cursor="hand2").pack(side="left", padx=6)
    tk.Button(filtros, text="Limpiar marca", command=lambda: (marca_entry.delete(0, tk.END), cargar()), bg="#F4F7FB", fg="#27415D", relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
    marca_entry.bind("<Return>", lambda e: cargar())
    dias_entry.bind("<Return>", lambda e: cargar())
    cargar()



def generar_lista_compra():
    marca_inicial = (combo_marca.get().strip().upper() if combo_marca is not None else "")
    win, body = _crear_ventana_reporte(
        "Qué comprar por ventas",
        "Sugerencia basada en ventas reales: últimos 7 días, 30 días, periodo elegido y stock actual. No usa objetivo fijo de cobertura.",
        "1580x820"
    )

    filtros = tk.Frame(body, bg="white", bd=1, relief="solid")
    filtros.pack(fill="x", pady=(0, 10))

    tk.Label(filtros, text="Marca:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(12, 6), pady=12)
    marca_entry = tk.Entry(filtros, width=16, font=("Segoe UI", 10))
    marca_entry.insert(0, marca_inicial)
    marca_entry.pack(side="left", padx=(0, 8), pady=12)

    tk.Label(filtros, text="Historial:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 6), pady=12)
    dias_entry = tk.Entry(filtros, width=6, font=("Segoe UI", 10))
    dias_entry.insert(0, str(DIAS_ANALISIS_COMPRA))
    dias_entry.pack(side="left", padx=(0, 2), pady=12)
    tk.Label(filtros, text="días", bg="white", fg="#5E718D", font=("Segoe UI", 9)).pack(side="left", padx=(0, 8), pady=12)

    tk.Label(filtros, text="Presupuesto:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 6), pady=12)
    presupuesto_entry = tk.Entry(filtros, width=10, font=("Segoe UI", 10))
    presupuesto_entry.pack(side="left", padx=(0, 8), pady=12)
    presupuesto_entry.insert(0, "")

    info = tk.Label(filtros, text="", bg="white", fg="#5E718D", font=("Segoe UI", 10))
    info.pack(side="right", padx=14)

    notebook = ttk.Notebook(body)
    notebook.pack(fill="both", expand=True)

    tab_lista = tk.Frame(notebook, bg="#EEF3F8")
    tab_resumen = tk.Frame(notebook, bg="#EEF3F8")
    notebook.add(tab_lista, text="Lista sugerida")
    notebook.add(tab_resumen, text="Resumen por marca")

    columnas = (
        "Prioridad", "Acción", "Marca", "Hilo", "Color", "Código",
        "Stock", "Vend.7", "Vend.30", "Vendidos", "Prom/día",
        "Ritmo", "Tendencia", "Base venta", "Comprar",
        "Costo", "Venta pot.", "Ganancia pot.", "Rotación", "Motivo"
    )

    tabla_frame = tk.Frame(tab_lista, bg="white", bd=1, relief="solid")
    tabla_frame.pack(fill="both", expand=True, padx=0, pady=0)

    tv = ttk.Treeview(tabla_frame, columns=columnas, show="headings")
    anchos = {
        "Prioridad": 95,
        "Acción": 140,
        "Marca": 130,
        "Hilo": 130,
        "Color": 130,
        "Código": 90,
        "Stock": 70,
        "Vend.7": 75,
        "Vend.30": 80,
        "Vendidos": 85,
        "Prom/día": 85,
        "Ritmo": 110,
        "Tendencia": 95,
        "Base venta": 135,
        "Comprar": 85,
        "Costo": 105,
        "Venta pot.": 110,
        "Ganancia pot.": 115,
        "Rotación": 95,
        "Motivo": 420,
    }
    for col in columnas:
        tv.heading(col, text=col)
        tv.column(col, width=anchos.get(col, 110), anchor="center")
    for col in ("Marca", "Hilo", "Color", "Acción", "Base venta", "Rotación", "Motivo"):
        tv.column(col, anchor="w")
    for col in ("Costo", "Venta pot.", "Ganancia pot."):
        tv.column(col, anchor="e")

    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tv.yview)
    scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    tv.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=(10, 0))
    scroll_y.grid(row=0, column=1, sticky="ns", pady=(10, 0))
    scroll_x.grid(row=1, column=0, sticky="ew", padx=(10, 0))
    tabla_frame.grid_rowconfigure(0, weight=1)
    tabla_frame.grid_columnconfigure(0, weight=1)

    tv.tag_configure("URGENTE", background="#FFE5E5")
    tv.tag_configure("ALTA", background="#FFF1D6")
    tv.tag_configure("MEDIA", background="#FFFBEA")
    tv.tag_configure("NORMAL", background="#EEF9F1")

    resumen_cols = ("Marca", "Tonos", "Piezas", "Urgentes", "Altas", "Costo aprox.", "Venta potencial", "Ganancia potencial")
    resumen_frame = tk.Frame(tab_resumen, bg="white", bd=1, relief="solid")
    resumen_frame.pack(fill="both", expand=True)
    tv_res = ttk.Treeview(resumen_frame, columns=resumen_cols, show="headings")
    for col in resumen_cols:
        tv_res.heading(col, text=col)
        tv_res.column(col, width=150, anchor="center")
    tv_res.column("Marca", width=180, anchor="w")
    for col in ("Costo aprox.", "Venta potencial", "Ganancia potencial"):
        tv_res.column(col, anchor="e")

    res_scroll_y = ttk.Scrollbar(resumen_frame, orient="vertical", command=tv_res.yview)
    tv_res.configure(yscrollcommand=res_scroll_y.set)
    tv_res.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
    res_scroll_y.grid(row=0, column=1, sticky="ns", pady=10)
    resumen_frame.grid_rowconfigure(0, weight=1)
    resumen_frame.grid_columnconfigure(0, weight=1)

    estado_compra = {"filas": []}

    def leer_parametros():
        marca = marca_entry.get().strip().upper()
        dias = _int_seguro(dias_entry.get(), DIAS_ANALISIS_COMPRA)
        presupuesto = to_float(presupuesto_entry.get(), 0.0)
        return marca, dias, presupuesto

    def cargar():
        tv.delete(*tv.get_children())
        tv_res.delete(*tv_res.get_children())

        marca, dias, presupuesto = leer_parametros()
        filas = construir_recomendacion_compra(
            marca=marca or None,
            dias=dias,
            presupuesto=presupuesto
        )
        estado_compra["filas"] = filas

        total_piezas = sum(r["comprar"] for r in filas)
        total_costo = sum(r["costo_compra"] for r in filas)
        total_venta = sum(r["venta_potencial"] for r in filas)
        total_ganancia = sum(r["ganancia_potencial"] for r in filas)
        urgentes = sum(1 for r in filas if r["prioridad"] == "URGENTE")
        altas = sum(1 for r in filas if r["prioridad"] == "ALTA")

        presupuesto_txt = f" • presupuesto {money(presupuesto)}" if presupuesto > 0 else ""
        info.config(
            text=(
                f"{len(filas)} tonos • {total_piezas} piezas • costo {money(total_costo)} "
                f"• ganancia pot. {money(total_ganancia)} • urgentes {urgentes} • altas {altas}{presupuesto_txt}"
            )
        )

        for r in filas:
            ritmo_txt = "Sin venta" if r.get("dias_al_ritmo") is None else f"{r['dias_al_ritmo']:.1f} días al ritmo actual"
            tendencia = r.get("tendencia", 1)
            if tendencia >= 1.4:
                tendencia_txt = "Subiendo"
            elif tendencia <= 0.7:
                tendencia_txt = "Bajando"
            else:
                tendencia_txt = "Estable"

            tv.insert("", "end", tags=(r["prioridad"],), values=(
                r["prioridad"],
                r["accion"],
                r["marca"],
                r["hilo"],
                r["color"],
                r["codigo"],
                r["stock"],
                r["vendidos_7"],
                r["vendidos_30"],
                r["vendidos_periodo"],
                f"{r['constante_venta']:.2f}",
                ritmo_txt,
                tendencia_txt,
                r.get("base_venta", "Ventas reales"),
                r["comprar"],
                money(r["costo_compra"]),
                money(r["venta_potencial"]),
                money(r["ganancia_potencial"]),
                r["rotacion"],
                r["motivo"],
            ))

        resumen = {}
        for r in filas:
            marca_r = r["marca"] or "SIN MARCA"
            resumen.setdefault(marca_r, {
                "tonos": 0,
                "piezas": 0,
                "urgentes": 0,
                "altas": 0,
                "costo": 0.0,
                "venta": 0.0,
                "ganancia": 0.0,
            })
            resumen[marca_r]["tonos"] += 1
            resumen[marca_r]["piezas"] += r["comprar"]
            resumen[marca_r]["urgentes"] += 1 if r["prioridad"] == "URGENTE" else 0
            resumen[marca_r]["altas"] += 1 if r["prioridad"] == "ALTA" else 0
            resumen[marca_r]["costo"] += r["costo_compra"]
            resumen[marca_r]["venta"] += r["venta_potencial"]
            resumen[marca_r]["ganancia"] += r["ganancia_potencial"]

        for marca_r, r in sorted(resumen.items(), key=lambda item: item[1]["costo"], reverse=True):
            tv_res.insert("", "end", values=(
                marca_r,
                r["tonos"],
                r["piezas"],
                r["urgentes"],
                r["altas"],
                money(r["costo"]),
                money(r["venta"]),
                money(r["ganancia"]),
            ))

    def copiar_lista():
        filas = []
        for item in tv.get_children():
            valores = tv.item(item, "values")
            filas.append("\t".join(str(v) for v in valores))
        if not filas:
            messagebox.showinfo("Sin datos", "No hay productos sugeridos para copiar.")
            return
        encabezado = "\t".join(columnas)
        texto = encabezado + "\n" + "\n".join(filas)
        win.clipboard_clear()
        win.clipboard_append(texto)
        messagebox.showinfo("Copiado", "Lista copiada. Puedes pegarla en Excel o Google Sheets.")

    def copiar_resumen():
        filas = []
        for item in tv_res.get_children():
            valores = tv_res.item(item, "values")
            filas.append("\t".join(str(v) for v in valores))
        if not filas:
            messagebox.showinfo("Sin datos", "No hay resumen para copiar.")
            return
        encabezado = "\t".join(resumen_cols)
        texto = encabezado + "\n" + "\n".join(filas)
        win.clipboard_clear()
        win.clipboard_append(texto)
        messagebox.showinfo("Copiado", "Resumen por marca copiado.")

    def limpiar_marca():
        marca_entry.delete(0, tk.END)
        cargar()

    tk.Button(filtros, text="Generar", command=cargar, bg="#2F6FED", fg="white", relief="flat", padx=14, pady=6, cursor="hand2").pack(side="left", padx=6)
    tk.Button(filtros, text="Copiar lista", command=copiar_lista, bg="#16A34A", fg="white", relief="flat", padx=14, pady=6, cursor="hand2").pack(side="left", padx=4)
    tk.Button(filtros, text="Copiar resumen", command=copiar_resumen, bg="#8E5AF7", fg="white", relief="flat", padx=14, pady=6, cursor="hand2").pack(side="left", padx=4)
    tk.Button(filtros, text="Limpiar marca", command=limpiar_marca, bg="#F4F7FB", fg="#27415D", relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)

    marca_entry.bind("<Return>", lambda e: cargar())
    dias_entry.bind("<Return>", lambda e: cargar())
    presupuesto_entry.bind("<Return>", lambda e: cargar())

    cargar()


def crear_card(parent, titulo, valor_inicial="0", accent="#2F6FED", ancho=205):
    frame = tk.Frame(parent, bg="white", bd=1, relief="solid", padx=14, pady=12)
    frame.pack(side="left", fill="both", expand=True, padx=6, pady=6)
    bar = tk.Frame(frame, bg=accent, width=6)
    bar.place(x=0, y=0, relheight=1)
    tk.Label(frame, text=titulo, bg="white", fg="#61738F", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=(8, 0))
    value = tk.Label(frame, text=valor_inicial, bg="white", fg="#16263D", font=("Segoe UI", 18, "bold"))
    value.pack(anchor="w", padx=(8, 0), pady=(8, 2))
    return value


def aplicar_filtro_modo(modo):
    global filtro_modo_actual
    filtro_modo_actual = modo
    refrescar_tabla()


def actualizar_estilo_botones_filtro():
    estilo_activo = {"bg": "#2F6FED", "fg": "white"}
    estilo_normal = {"bg": "white", "fg": "#28405E"}
    mapa = {
        "TODOS": btn_todos,
        "BAJO": btn_bajo,
        "OK": btn_ok,
        "ITEMS": btn_items,
    }
    for modo, btn in mapa.items():
        if btn is None:
            continue
        cfg = estilo_activo if modo == filtro_modo_actual else estilo_normal
        btn.config(bg=cfg["bg"], fg=cfg["fg"], activebackground=cfg["bg"], activeforeground=cfg["fg"])


def buscar_diferido(event=None):
    global buscar_job
    if buscar_job:
        root.after_cancel(buscar_job)
    buscar_job = root.after(250, lambda: refrescar_tabla())


def construir_interfaz():
    global root, tabla, combo_marca, entry_hilo, entry_color, entry_codigo, entry_barras
    global entry_stock, entry_vol, entry_buscar, lbl_ganancia, lbl_estado
    global card_total_tonos, card_stock_total, card_stock_bajo, card_marcas, card_valor_costo, card_valor_venta, card_ganancia
    global btn_todos, btn_bajo, btn_ok, btn_items, var_es_inventariable

    root = tk.Tk()
    root.title("Almacén Hilorama • Moderno")
    root.geometry("1620x900")
    root.minsize(1420, 780)
    root.configure(bg="#EEF3F8")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("Treeview", rowheight=34, font=("Segoe UI", 10), background="white", fieldbackground="white", borderwidth=0)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#DDE7F2", foreground="#23374D")
    style.map("Treeview", background=[("selected", "#D7E7FF")], foreground=[("selected", "black")])
    style.configure("TCombobox", padding=6)
    style.configure("TButton", font=("Segoe UI", 10))

    # Encabezado
    header = tk.Frame(root, bg="#1F3A5F", height=92)
    header.pack(fill="x")
    tk.Label(header, text="ALMACÉN HILORAMA", font=("Segoe UI", 22, "bold"), fg="white", bg="#1F3A5F").pack(anchor="w", padx=20, pady=(16, 0))
    tk.Label(header, text="Control de inventario, costos, precios, stock, items de cotización y movimientos.", font=("Segoe UI", 10), fg="#D9E6F2", bg="#1F3A5F").pack(anchor="w", padx=20, pady=(0, 14))

    cont = tk.Frame(root, bg="#EEF3F8")
    cont.pack(fill="both", expand=True, padx=16, pady=16)

    # Dashboard
    frame_cards_1 = tk.Frame(cont, bg="#EEF3F8")
    frame_cards_1.pack(fill="x")
    card_total_tonos = crear_card(frame_cards_1, "Tonos visibles", "0", "#2F6FED")
    card_stock_total = crear_card(frame_cards_1, "Stock total", "0", "#00A66E")
    card_stock_bajo = crear_card(frame_cards_1, "Stock bajo", "0", "#E55353")
    card_marcas = crear_card(frame_cards_1, "Marcas", "0", "#8E5AF7")

    frame_cards_2 = tk.Frame(cont, bg="#EEF3F8")
    frame_cards_2.pack(fill="x")
    card_valor_costo = crear_card(frame_cards_2, "Valor a costo", "$0.00", "#285A84")
    card_valor_venta = crear_card(frame_cards_2, "Valor a venta", "$0.00", "#D08B00")
    card_ganancia = crear_card(frame_cards_2, "Ganancia estimada", "$0.00", "#16A34A")

    # Filtros y herramientas
    top_tools = tk.Frame(cont, bg="white", bd=1, relief="solid")
    top_tools.pack(fill="x", pady=(10, 12))

    left_tools = tk.Frame(top_tools, bg="white")
    left_tools.pack(side="left", fill="x", expand=True, padx=12, pady=10)

    tk.Label(left_tools, text="Buscar en inventario", bg="white", fg="#22364D", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
    entry_buscar = tk.Entry(left_tools, width=36, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_buscar.grid(row=1, column=0, sticky="w", pady=(4, 0))
    entry_buscar.bind("<KeyRelease>", buscar_diferido)

    tk.Button(left_tools, text="Limpiar", command=lambda: (entry_buscar.delete(0, tk.END), refrescar_tabla()), bg="#F4F7FB", fg="#27415D", relief="flat", padx=12, pady=6, cursor="hand2").grid(row=1, column=1, padx=8, pady=(4, 0))
    tk.Button(left_tools, text="Actualizar", command=refrescar_tabla, bg="#2F6FED", fg="white", relief="flat", padx=14, pady=6, cursor="hand2").grid(row=1, column=2, padx=2, pady=(4, 0))

    right_tools = tk.Frame(top_tools, bg="white")
    right_tools.pack(side="right", padx=12, pady=10)
    tk.Label(right_tools, text="Vista rápida", bg="white", fg="#22364D", font=("Segoe UI", 10, "bold")).pack(anchor="e")
    pills = tk.Frame(right_tools, bg="white")
    pills.pack(anchor="e", pady=(4, 0))
    btn_todos = tk.Button(pills, text="Todos", command=lambda: aplicar_filtro_modo("TODOS"), relief="flat", padx=14, pady=6, cursor="hand2")
    btn_todos.pack(side="left", padx=4)
    btn_bajo = tk.Button(pills, text="Stock bajo", command=lambda: aplicar_filtro_modo("BAJO"), relief="flat", padx=14, pady=6, cursor="hand2")
    btn_bajo.pack(side="left", padx=4)
    btn_ok = tk.Button(pills, text="Solo OK", command=lambda: aplicar_filtro_modo("OK"), relief="flat", padx=14, pady=6, cursor="hand2")
    btn_ok.pack(side="left", padx=4)
    btn_items = tk.Button(pills, text="Items cotización", command=lambda: aplicar_filtro_modo("ITEMS"), relief="flat", padx=14, pady=6, cursor="hand2")
    btn_items.pack(side="left", padx=4)

    # Formulario + acciones
    form_wrap = tk.Frame(cont, bg="#EEF3F8")
    form_wrap.pack(fill="x")

    form_card = tk.LabelFrame(form_wrap, text=" Alta rápida de producto ", bg="white", fg="#22364D", font=("Segoe UI", 10, "bold"), bd=1, relief="solid", labelanchor="n")
    form_card.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=(0, 12))

    actions_card = tk.LabelFrame(form_wrap, text=" Acciones ", bg="white", fg="#22364D", font=("Segoe UI", 10, "bold"), bd=1, relief="solid", labelanchor="n")
    actions_card.pack(side="right", fill="y", padx=(8, 0), pady=(0, 12))

    campos = [
        ("Marca", "combo"),
        ("Hilo", "entry"),
        ("Color", "entry"),
        ("Código", "entry"),
        ("Cod. barras", "entry"),
        ("Stock", "entry"),
        ("Volumétrico", "entry"),
    ]

    for i, (txt, _) in enumerate(campos):
        tk.Label(form_card, text=txt, bg="white", fg="#4D627C", font=("Segoe UI", 9, "bold")).grid(row=0, column=i, sticky="w", padx=10, pady=(10, 4))

    combo_marca = ttk.Combobox(form_card, width=14)
    combo_marca.grid(row=1, column=0, padx=10, pady=(0, 12), sticky="we")
    entry_hilo = tk.Entry(form_card, width=14, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_hilo.grid(row=1, column=1, padx=10, pady=(0, 12), sticky="we")
    entry_color = tk.Entry(form_card, width=14, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_color.grid(row=1, column=2, padx=10, pady=(0, 12), sticky="we")
    entry_codigo = tk.Entry(form_card, width=12, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_codigo.grid(row=1, column=3, padx=10, pady=(0, 12), sticky="we")
    entry_barras = tk.Entry(form_card, width=16, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_barras.grid(row=1, column=4, padx=10, pady=(0, 12), sticky="we")
    entry_stock = tk.Entry(form_card, width=10, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_stock.grid(row=1, column=5, padx=10, pady=(0, 12), sticky="we")
    entry_vol = tk.Entry(form_card, width=10, font=("Segoe UI", 10), relief="flat", highlightthickness=1, highlightbackground="#CAD4E0")
    entry_vol.grid(row=1, column=6, padx=10, pady=(0, 12), sticky="we")

    for c in range(7):
        form_card.grid_columnconfigure(c, weight=1)

    btns_form = tk.Frame(form_card, bg="white")
    btns_form.grid(row=2, column=0, columnspan=7, sticky="w", padx=10, pady=(0, 12))
    var_es_inventariable = tk.BooleanVar(value=True)
    tk.Checkbutton(
        btns_form,
        text="Cuenta como inventario físico",
        variable=var_es_inventariable,
        bg="white",
        fg="#27415D",
        activebackground="white",
        font=("Segoe UI", 9, "bold")
    ).pack(side="left", padx=(0, 14))
    tk.Button(btns_form, text="Agregar producto", command=agregar_producto, bg="#16A34A", fg="white", relief="flat", padx=16, pady=8, cursor="hand2").pack(side="left", padx=(0, 8))
    tk.Button(btns_form, text="Limpiar", command=limpiar_formulario, bg="#F4F7FB", fg="#27415D", relief="flat", padx=14, pady=8, cursor="hand2").pack(side="left")

    grid_actions = tk.Frame(actions_card, bg="white")
    grid_actions.pack(padx=10, pady=10)
    acciones = [
        ("Eliminar tono", eliminar_tono, "#E55353", "white"),
        ("Precios por marca", editar_precios_marca, "#F4F7FB", "#27415D"),
        ("Precio por hilo", actualizar_precio_hilo, "#F4F7FB", "#27415D"),
        ("Volumétrico por hilo", asignar_volumetrico_hilo, "#F4F7FB", "#27415D"),
        ("Volumétrico múltiple", asignar_volumetrico_multiple, "#F4F7FB", "#27415D"),
        ("Item cotización", marcar_item_sin_inventario, "#F4F7FB", "#27415D"),
        ("Hacer inventario", marcar_como_inventario, "#F4F7FB", "#27415D"),
        ("Movimientos", ver_movimientos, "#2F6FED", "white"),
        ("Ganancia marca/hilo", ver_ganancia_por_marca, "#16A34A", "white"),
        ("Estadísticas venta", ver_estadisticas_ventas, "#8E5AF7", "white"),
        ("Qué comprar", generar_lista_compra, "#D08B00", "white"),
    ]
    for i, (txt, cmd, bg, fg) in enumerate(acciones):
        tk.Button(grid_actions, text=txt, command=cmd, bg=bg, fg=fg, relief="flat", width=18, pady=8, cursor="hand2").grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="we")

    # Tabla principal
    table_card = tk.Frame(cont, bg="white", bd=1, relief="solid")
    table_card.pack(fill="both", expand=True)

    tk.Label(table_card, text="Inventario de almacén", bg="white", fg="#22364D", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(table_card, text="Doble clic sobre stock, código de barras, costo, precio o volumétrico para editar. Usa “Item cotización” para paquetes/combos que no deben contar como almacén.", bg="white", fg="#61738F", font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 8))

    tabla_wrap = tk.Frame(table_card, bg="white")
    tabla_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    tabla = ttk.Treeview(
        tabla_wrap,
        columns=(
            "Hilo", "Color", "Código", "Stock", "Codigo_Barras",
            "Costo", "Precio", "Volumetrico", "Tipo", "Estado",
            "Valor_Costo", "Valor_Venta", "Ganancia"
        ),
        show="tree headings"
    )

    tabla.heading("#0", text="Marca")
    tabla.column("#0", width=140, anchor="w")
    tabla.heading("Hilo", text="Hilo")
    tabla.column("Hilo", width=120, anchor="w")
    tabla.heading("Color", text="Color")
    tabla.column("Color", width=120, anchor="w")
    tabla.heading("Código", text="Código")
    tabla.column("Código", width=90, anchor="center")
    tabla.heading("Stock", text="Stock")
    tabla.column("Stock", width=80, anchor="center")
    tabla.heading("Codigo_Barras", text="Cod. barras")
    tabla.column("Codigo_Barras", width=145, anchor="center")
    tabla.heading("Costo", text="Costo neto")
    tabla.column("Costo", width=105, anchor="e")
    tabla.heading("Precio", text="Precio venta")
    tabla.column("Precio", width=105, anchor="e")
    tabla.heading("Volumetrico", text="Volumétrico")
    tabla.column("Volumetrico", width=100, anchor="center")
    tabla.heading("Tipo", text="Tipo")
    tabla.column("Tipo", width=130, anchor="center")
    tabla.heading("Estado", text="Estado")
    tabla.column("Estado", width=95, anchor="center")
    tabla.heading("Valor_Costo", text="Total costo")
    tabla.column("Valor_Costo", width=115, anchor="e")
    tabla.heading("Valor_Venta", text="Total venta")
    tabla.column("Valor_Venta", width=115, anchor="e")
    tabla.heading("Ganancia", text="Ganancia")
    tabla.column("Ganancia", width=115, anchor="e")

    scroll_y = ttk.Scrollbar(tabla_wrap, orient="vertical", command=tabla.yview)
    scroll_x = ttk.Scrollbar(tabla_wrap, orient="horizontal", command=tabla.xview)
    tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    tabla.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    tabla_wrap.grid_rowconfigure(0, weight=1)
    tabla_wrap.grid_columnconfigure(0, weight=1)

    tabla.bind("<Double-1>", doble_click_editar)
    tabla.tag_configure("marca", background="#DCE8F7", font=("Segoe UI", 10, "bold"), foreground="#21354D")
    tabla.tag_configure("hilo", background="#EEF4FB", font=("Segoe UI", 10, "bold"), foreground="#2F4968")
    tabla.tag_configure("ok_par", background="#F7FBF8")
    tabla.tag_configure("ok_impar", background="#EDF8F1")
    tabla.tag_configure("bajo_par", background="#FFF8F8")
    tabla.tag_configure("bajo_impar", background="#FFF0F0")
    tabla.tag_configure("item_par", background="#F3F4F6")
    tabla.tag_configure("item_impar", background="#E9EDF3")

    footer = tk.Frame(cont, bg="#EEF3F8")
    footer.pack(fill="x", pady=(10, 0))
    lbl_ganancia = tk.Label(footer, text="Resumen actual", bg="#EEF3F8", fg="#23374D", font=("Segoe UI", 11, "bold"))
    lbl_ganancia.pack(anchor="w")
    lbl_estado = tk.Label(footer, text="Listo", bg="#EEF3F8", fg="#5F738E", font=("Segoe UI", 9))
    lbl_estado.pack(anchor="w", pady=(2, 0))

    ensure_almacen_schema()
    combo_marca["values"] = marcas_existentes()
    refrescar_tabla()

    def cerrar():
        global autorizado
        autorizado = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", cerrar)
    return root

# ================= API PARA VENTAS =================
def obtener_stock(marca, hilo, codigo):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("""
        SELECT stock, es_inventariable FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (marca, hilo, codigo)).fetchone()
    conn.close()
    if not r:
        return 0
    if not es_inventariable_producto(r):
        # Para ventas: un item de cotización no debe bloquearse por falta de stock físico.
        return 999999
    return r["stock"] if r else 0


def actualizar_stock(marca, hilo, codigo, nuevo_stock):
    ensure_almacen_schema()
    estado = "OK" if nuevo_stock >= STOCK_MINIMO else "RESURTIR"
    conn = get_conn()

    anterior = conn.execute("""
        SELECT * FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (marca, hilo, codigo)).fetchone()

    if anterior and not es_inventariable_producto(anterior):
        registrar_movimiento(
            "AJUSTE_ITEM_COTIZACION",
            marca=marca,
            hilo=hilo,
            color=anterior.get("color"),
            codigo=codigo,
            stock_anterior=0,
            stock_nuevo=0,
            cantidad=0,
            campo="stock",
            valor_anterior="NO APLICA",
            valor_nuevo="NO APLICA",
            motivo="Se ignoró ajuste de stock porque es item de cotización",
            conn=conn
        )
        conn.commit()
        conn.close()
        return True

    conn.execute("""
        UPDATE productos
        SET stock=%s, estado=%s
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (nuevo_stock, estado, marca, hilo, codigo))

    stock_anterior = int(anterior.get("stock") or 0) if anterior else None
    registrar_movimiento(
        "AJUSTE_STOCK",
        marca=marca,
        hilo=hilo,
        color=anterior.get("color") if anterior else None,
        codigo=codigo,
        stock_anterior=stock_anterior,
        stock_nuevo=nuevo_stock,
        cantidad=(nuevo_stock - stock_anterior) if stock_anterior is not None else 0,
        campo="stock",
        valor_anterior=stock_anterior,
        valor_nuevo=nuevo_stock,
        motivo="Actualización de stock desde API",
        conn=conn
    )

    conn.commit()
    conn.close()
    return True


def descontar_stock(marca, hilo, codigo, cantidad):
    ensure_almacen_schema()
    conn = get_conn()

    anterior = conn.execute("""
        SELECT * FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (marca, hilo, codigo)).fetchone()

    # Si es un paquete/combo/item de cotización, se permite venderlo pero NO se descuenta stock físico.
    if anterior and not es_inventariable_producto(anterior):
        registrar_movimiento(
            "SALIDA_ITEM_COTIZACION",
            marca=marca,
            hilo=hilo,
            color=anterior.get("color"),
            codigo=codigo,
            stock_anterior=0,
            stock_nuevo=0,
            cantidad=-(int(cantidad)),
            campo="stock",
            valor_anterior="NO APLICA",
            valor_nuevo="NO APLICA",
            motivo="Venta de item de cotización; no descuenta almacén físico",
            conn=conn
        )
        conn.commit()
        conn.close()
        return True

    conn.execute("""
        UPDATE productos
        SET stock = stock - %s
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (cantidad, marca, hilo, codigo))

    stock_anterior = int(anterior.get("stock") or 0) if anterior else None
    stock_nuevo = stock_anterior - int(cantidad) if stock_anterior is not None else None
    nuevo_estado = "OK" if (stock_nuevo or 0) >= STOCK_MINIMO else "RESURTIR"
    conn.execute("""
        UPDATE productos
        SET estado=%s
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (nuevo_estado, marca, hilo, codigo))

    registrar_movimiento(
        "SALIDA_STOCK",
        marca=marca,
        hilo=hilo,
        color=anterior.get("color") if anterior else None,
        codigo=codigo,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        cantidad=-(int(cantidad)),
        campo="stock",
        valor_anterior=stock_anterior,
        valor_nuevo=stock_nuevo,
        motivo="Descuento por venta/cotización",
        conn=conn
    )

    conn.commit()
    conn.close()
    return True


def obtener_precio_venta(marca):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("SELECT venta FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return r["venta"] if r else 0


def obtener_precio_distribuidor(marca):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("SELECT distribuidor FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return r["distribuidor"] if r else 0


def es_stock_bajo(marca, hilo, codigo):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("""
        SELECT stock, es_inventariable FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (marca, hilo, codigo)).fetchone()
    conn.close()
    if not r or not es_inventariable_producto(r):
        return False
    return r["stock"] < STOCK_MINIMO


def obtener_producto_por_codigo_barras(codigo_barras):
    ensure_almacen_schema()
    conn = get_conn()
    r = conn.execute("SELECT * FROM productos WHERE codigo_barras=%s", (codigo_barras,)).fetchone()
    conn.close()
    return r


if __name__ == "__main__":
    app = construir_interfaz()
    app.mainloop()
