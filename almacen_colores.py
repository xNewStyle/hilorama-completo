import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from database.connection import get_conn
import os

# ================= CONFIG =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PASSWORD = "12587987521"
STOCK_MINIMO = 50




# ================= UTIL =================
def marcas_existentes():
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT marca FROM productos").fetchall()
    conn.close()
    return sorted([r["marca"] for r in rows])


def calcular_ganancia_total(productos):
    total = 0
    for r in productos:
        if r["venta"] and r["distribuidor"]:
            total += (r["venta"] - r["distribuidor"]) * r["stock"]

    lbl_ganancia.config(
        text=f"Ganancia estimada total: ${total:.2f}"
    )



# ================= TABLA =================
def refrescar_tabla(filtro=None):
    tabla.delete(*tabla.get_children())

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
            pr.venta,
            pr.distribuidor
        FROM productos p
        LEFT JOIN precios pr 
            ON pr.marca = p.marca
        """).fetchall()

    conn.close()

    datos = {}

    for p in productos:
        texto = f"{p['marca']} {p['hilo']} {p['color']} {p['codigo']}"
        if filtro and filtro.upper() not in texto:
            continue

        datos.setdefault(p["marca"], {}).setdefault(p["hilo"], []).append(p)

    for marca in sorted(datos):
        marca_id = tabla.insert("", "end", text=marca, tags=("marca",))


        for hilo in sorted(datos[marca]):
            hilo_id = tabla.insert(marca_id, "end", text=hilo, tags=("hilo",))


            for p in datos[marca][hilo]:
                tag = "ok" if p["estado"] == "OK" else "bajo"
                tabla.insert(
                    hilo_id,
                    "end",
                    text="",
                    values=(
                        p["hilo"],
                        p["color"],
                        p["codigo"],
                        p["stock"],
                        p["codigo_barras"],
                        p["estado"]
                    ),
                    tags=(tag,)
                )


    calcular_ganancia_total(productos)



# ================= ACCIONES =================
def agregar_producto():
    marca = combo_marca.get().strip().upper()
    hilo = entry_hilo.get().strip().upper()
    color = entry_color.get().strip().upper()
    codigo = entry_codigo.get().strip()
    codigo_barras = entry_barras.get().strip()
    stock = entry_stock.get().strip()
    vol = entry_vol.get().strip().replace(",", ".")

    if not vol:
        volumetrico = 1.0   # valor por defecto
    else:
        try:
           volumetrico = float(vol)
        except ValueError:
            messagebox.showerror("Error", f"Volumétrico inválido: {vol}")
            return


    if volumetrico <= 0:
        messagebox.showerror("Error", "Volumétrico debe ser mayor a 0")
        return

    if not all([marca, hilo, color, codigo, stock]):
        messagebox.showerror("Error", "Completa todos los campos")
        return

    try:
        stock = int(stock)
    except:
        messagebox.showerror("Error", "Stock inválido")
        return

    conn = get_conn()

    existe = conn.execute("""
    SELECT 1 FROM productos
    WHERE marca=%s AND hilo=%s AND color=%s AND codigo=%s
    """,(marca,hilo,color,codigo)).fetchone()

    if existe:
        messagebox.showwarning("Duplicado","Este tono ya existe")
        conn.close()
        return

    estado = "OK" if stock >= STOCK_MINIMO else "RESURTIR"

    conn.execute("""
   INSERT INTO productos
   (marca,hilo,color,codigo,codigo_barras,stock,estado,volumetrico)
   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)

    """,(marca,hilo,color,codigo,codigo_barras,stock,estado,volumetrico))

    conn.commit()
    conn.close()


    

    combo_marca["values"] = marcas_existentes()
    refrescar_tabla()

def eliminar_tono():
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
    codigo = str(valores[2])

    parent_hilo = tabla.parent(item)
    parent_marca = tabla.parent(parent_hilo)
    marca = tabla.item(parent_marca)["text"]

    conn = get_conn()

    conn.execute("""
        DELETE FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """, (marca, hilo, codigo))

    conn.commit()
    conn.close()

    messagebox.showinfo("Correcto", "Producto eliminado")

    refrescar_tabla()



def editar_producto(event):
    item = tabla.focus()
    if not item:
        return

    item_data = tabla.item(item)

    # Si no tiene values, es marca o hilo
    if not item_data["values"]:
        return

    valores = item_data["values"]

    # Seguridad extra
    if len(valores) < 4:
        return

    pwd = simpledialog.askstring("Contraseña", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    opcion = simpledialog.askstring(
        "Editar",
        "¿Qué deseas editar?\n\n1 = Stock\n2 = Código de barras"
    )

    # valores ahora son:
    # [Hilo, Color, Código, Stock, Codigo_Barras, Estado]

    hilo = valores[0]
    color = valores[1]
    codigo = str(valores[2])
    stock_actual = valores[3]

    # Marca ahora está en el padre
    parent_hilo = tabla.parent(item)
    parent_marca = tabla.parent(parent_hilo)
    marca = tabla.item(parent_marca)["text"]

    if opcion == "1":
        nuevo_stock = simpledialog.askinteger("Stock", "Nuevo stock:")
        if nuevo_stock is None:
            return

        estado = "OK" if nuevo_stock >= STOCK_MINIMO else "RESURTIR"

        conn = get_conn()
        conn.execute("""
            UPDATE productos
            SET stock=%s, estado=%s
            WHERE marca=%s AND hilo=%s AND codigo=%s
        """,(nuevo_stock,estado,marca,hilo,codigo))
        conn.commit()
        conn.close()

    elif opcion == "2":
        nuevo_barras = simpledialog.askstring("Código de barras", "Nuevo código:")
        if not nuevo_barras:
            return

        conn = get_conn()
        conn.execute("""
            UPDATE productos
            SET codigo_barras=%s
            WHERE marca=%s AND hilo=%s AND codigo=%s
        """,(nuevo_barras,marca,hilo,codigo))
        conn.commit()
        conn.close()

    refrescar_tabla()



def editar_precios_marca():
    marca = combo_marca.get()
    if not marca:
        return

    pwd = simpledialog.askstring("Contraseña", "Contraseña:", show="*")
    if pwd != PASSWORD:
        return

    dist = simpledialog.askfloat("Distribuidor", "Precio distribuidor:")
    venta = simpledialog.askfloat("Venta", "Precio venta:")

    if dist is None or venta is None:
        return

    conn = get_conn()

    conn.execute("""
    INSERT INTO precios(marca, distribuidor, venta)
    VALUES (%s,%s,%s)
    ON CONFLICT(marca)
    DO UPDATE SET
        distribuidor=excluded.distribuidor,
        venta=excluded.venta
    """,(marca,dist,venta))

    conn.commit()
    conn.close()

def asignar_volumetrico_hilo():
    marca = combo_marca.get().strip().upper()
    hilo = entry_hilo.get().strip().upper()

    if not marca or not hilo:
        messagebox.showerror(
            "Error",
            "Selecciona una marca y escribe el hilo",
        )
        return

    # 🔒 contraseña
    pwd = simpledialog.askstring(
        "Autorización",
        "Contraseña:",
        show="*"
    )
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

    cur = conn.execute("""
    UPDATE productos
    SET volumetrico=%s
    WHERE marca=%s AND hilo=%s
    """,(vol,marca,hilo))

    conn.commit()
    cambios = cur.rowcount
    conn.close()


    messagebox.showinfo(
        "Listo",
        f"Volumétrico aplicado a {cambios} productos"
    )


# ================= INTERFAZ =================
# ================= INICIO =================
if __name__ == "__main__":

    root = tk.Tk()
    root.title("ALMACÉN HILORAMA")
    root.geometry("1200x700")

    # Buscador
    frame_buscar = tk.Frame(root)
    frame_buscar.pack(fill="x", padx=10, pady=5)

    entry_buscar = tk.Entry(frame_buscar)
    entry_buscar.pack(side="left", padx=5)

    tk.Button(
        frame_buscar,
        text="Buscar",
        command=lambda: refrescar_tabla(entry_buscar.get())
    ).pack(side="left")

    # Formulario
    frame_form = tk.Frame(root)
    frame_form.pack(fill="x", padx=10, pady=5)

    labels = ["Marca", "Hilo", "Color", "Código", "Cod. Barras", "Stock", "Volumetrico"]

    for i, txt in enumerate(labels):
        tk.Label(frame_form, text=txt).grid(row=0, column=i, padx=5)

    combo_marca = ttk.Combobox(frame_form, width=15)
    combo_marca.grid(row=1, column=0, padx=5)

    entry_hilo = tk.Entry(frame_form, width=15)
    entry_hilo.grid(row=1, column=1, padx=5)

    entry_color = tk.Entry(frame_form, width=15)
    entry_color.grid(row=1, column=2, padx=5)

    entry_codigo = tk.Entry(frame_form, width=10)
    entry_codigo.grid(row=1, column=3, padx=5)

    entry_barras = tk.Entry(frame_form, width=15)   # ⭐ NUEVO
    entry_barras.grid(row=1, column=4, padx=5)

    entry_stock = tk.Entry(frame_form, width=10)
    entry_stock.grid(row=1, column=5, padx=5)

    entry_vol = tk.Entry(frame_form, width=10)
    entry_vol.grid(row=1, column=6, padx=5)

    
    tk.Button(frame_form, text="Agregar", command=agregar_producto).grid(row=1, column=8)
    tk.Button(frame_form, text="Eliminar tono", command=eliminar_tono).grid(row=1, column=9)
    tk.Button(frame_form, text="$ Precios marca", command=editar_precios_marca).grid(row=1, column=10)
    tk.Button(
    frame_form,
    text="📦 Volumétrico por hilo",
    command=asignar_volumetrico_hilo
    ).grid(row=1, column=11, padx=5)


    # Tabla
    # Fondo general moderno
    root.configure(bg="#F4F6F9")

    # ===== CARD CONTENEDOR =====
    card_tabla = tk.Frame(
        root,
        bg="white",
        bd=0,
        highlightthickness=0
    )
    card_tabla.pack(fill="both", expand=True, padx=20, pady=15)

    # ===== ESTILO MODERNO =====
    style = ttk.Style()
    style.theme_use("default")

    style.configure(
        "Treeview",
        background="white",
        foreground="black",
        rowheight=32,
        fieldbackground="white",
        borderwidth=0,
        font=("Segoe UI", 11)
    )

    style.configure(
        "Treeview.Heading",
        font=("Segoe UI", 11, "bold"),
        background="#E3EAF2",
        foreground="#333"
    )

    style.map(
        "Treeview",
        background=[("selected", "#DCEBFF")]
    )

    # ===== TABLA =====
    tabla = ttk.Treeview(
        card_tabla,
        columns=("Hilo", "Color", "Código", "Stock","Codigo_Barras", "Estado"),
        show="tree headings"
    )

    tabla.heading("#0", text="Marca")
    tabla.column("#0", width=160, anchor="w")


    tabla.pack(fill="both", expand=True, padx=15, pady=15)
    tabla.bind("<Double-1>", editar_producto)


    tabla.tag_configure("marca", background="#BBDEFB", font=("Segoe UI", 10, "bold"))
    tabla.tag_configure("hilo", background="#E3F2FD", font=("Segoe UI", 9, "bold"))
    tabla.tag_configure("ok", background="#E8F5E9")
    tabla.tag_configure("bajo", background="#FFEBEE")

    lbl_ganancia = tk.Label(
        root,
        text="Ganancia estimada total: $0.00",
        font=("Segoe UI", 12, "bold")
    )
    lbl_ganancia.pack(pady=10)

    combo_marca["values"] = marcas_existentes()
    refrescar_tabla()

    root.mainloop()


# ================= API PARA VENTAS =================

def obtener_stock(marca,hilo,codigo):
    conn = get_conn()
    r = conn.execute("""
        SELECT stock FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """,(marca,hilo,codigo)).fetchone()
    conn.close()
    return r["stock"] if r else 0



def actualizar_stock(marca,hilo,codigo,nuevo_stock):

    estado = "OK" if nuevo_stock >= STOCK_MINIMO else "RESURTIR"

    conn = get_conn()

    conn.execute("""
    UPDATE productos
    SET stock=%s, estado=%s
    WHERE marca=%s AND hilo=%s AND codigo=%s
    """,(nuevo_stock,estado,marca,hilo,codigo))

    conn.commit()
    conn.close()

    return True



def descontar_stock(marca,hilo,codigo,cantidad):

    conn = get_conn()

    conn.execute("""
    UPDATE productos
    SET stock = stock - %s
    WHERE marca=%s AND hilo=%s AND codigo=%s
    """,(cantidad,marca,hilo,codigo))

    conn.commit()
    conn.close()

    return True



def obtener_precio_venta(marca):
    conn = get_conn()
    r = conn.execute(
        "SELECT venta FROM precios WHERE marca=%s",
        (marca,)
    ).fetchone()
    conn.close()
    return r["venta"] if r else 0


def obtener_precio_distribuidor(marca):
    conn = get_conn()
    r = conn.execute(
        "SELECT distribuidor FROM precios WHERE marca=%s",
        (marca,)
    ).fetchone()
    conn.close()
    return r["distribuidor"] if r else 0

def es_stock_bajo(marca,hilo,codigo):
    conn = get_conn()
    r = conn.execute("""
        SELECT stock FROM productos
        WHERE marca=%s AND hilo=%s AND codigo=%s
    """,(marca,hilo,codigo)).fetchone()
    conn.close()

    if not r:
        return False

    return r["stock"] < STOCK_MINIMO

def obtener_producto_por_codigo_barras(codigo_barras):
    conn = get_conn()
    r = conn.execute("""
        SELECT * FROM productos
        WHERE codigo_barras=%s
    """,(codigo_barras,)).fetchone()
    conn.close()
    return r




