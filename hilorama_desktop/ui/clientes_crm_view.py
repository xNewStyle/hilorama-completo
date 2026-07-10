"""Vista CRM de clientas compradoras para el modo API de Hilorama Desktop."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import quote
import webbrowser

import customtkinter as ctk

try:
    from ..services import clientes_crm_service as crm
    from ..utils.logger import log_error, log_info
except ImportError:
    from services import clientes_crm_service as crm
    from utils.logger import log_error, log_info


_COLORES_SEGMENTO = {
    "VIP": "#9B4DCA",
    "FRECUENTE": "#2563EB",
    "ACTIVA": "#0F766E",
    "EN_RIESGO": "#B45309",
    "DORMIDA": "#6B7280",
    "NUEVA": "#15803D",
    "SIN_COMPRAS": "#64748B",
}

_NOMBRES_SEGMENTO = {
    "EN_RIESGO": "En riesgo",
    "SIN_COMPRAS": "Sin compras",
    "VIP": "VIP",
    "FRECUENTE": "Frecuente",
    "ACTIVA": "Activa",
    "DORMIDA": "Dormida",
    "NUEVA": "Nueva",
}


def abrir_clientes_crm(parent, cliente=None, editar_cliente_callback=None):
    """Abre el CRM comercial. La edicion usa el callback existente del visor."""
    ventana = ClientesCrmWindow(parent, editar_cliente_callback=editar_cliente_callback)
    ventana.mostrar_cliente_inicial(cliente)
    return ventana.win


class ClientesCrmWindow:
    def __init__(self, parent, editar_cliente_callback=None):
        self.editar_cliente_callback = editar_cliente_callback
        self.ranking_por_id = {}
        self.analitica_actual = None
        self.graficas = {}
        self.cliente_inicial_id = None

        self.win = ctk.CTkToplevel(parent)
        self.win.title("Clientas")
        self.win.geometry("1440x880")
        self.win.minsize(1180, 720)
        self.win.configure(fg_color="#F4F5F7")
        self.win.transient(parent.winfo_toplevel())

        self.busqueda_var = tk.StringVar()
        self.segmento_var = tk.StringVar(value="TODAS")
        self.desde_var = tk.StringVar()
        self.hasta_var = tk.StringVar()
        self.orden_var = tk.StringVar(value="total_comprado")
        self.metricas_vars = {
            "total_clientas": tk.StringVar(value="0"),
            "activas": tk.StringVar(value="0"),
            "dormidas": tk.StringVar(value="0"),
            "vip": tk.StringVar(value="0"),
            "ticket": tk.StringVar(value="$0.00"),
        }

        self._construir()
        self.win.after(80, self.cargar_datos)

    def mostrar_cliente_inicial(self, cliente):
        if isinstance(cliente, dict) and cliente.get("id") is not None:
            self.cliente_inicial_id = str(cliente.get("id"))

    def _construir(self):
        raiz = ctk.CTkFrame(self.win, fg_color="transparent")
        raiz.pack(fill="both", expand=True, padx=14, pady=14)
        raiz.grid_columnconfigure(0, weight=1)
        raiz.grid_rowconfigure(3, weight=1)

        encabezado = ctk.CTkFrame(raiz, corner_radius=6, fg_color="#FFFFFF")
        encabezado.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        encabezado.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            encabezado,
            text="Clientas",
            font=("Segoe UI", 22, "bold"),
            text_color="#1F2937",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=12)
        ctk.CTkButton(
            encabezado,
            text="Graficas",
            width=112,
            height=34,
            corner_radius=6,
            command=self.abrir_graficas,
        ).grid(row=0, column=1, padx=(8, 8), pady=10)
        ctk.CTkButton(
            encabezado,
            text="Actualizar",
            width=112,
            height=34,
            corner_radius=6,
            fg_color="#0F766E",
            hover_color="#115E59",
            command=self.cargar_datos,
        ).grid(row=0, column=2, padx=(0, 12), pady=10)

        filtros = ctk.CTkFrame(raiz, corner_radius=6, fg_color="#FFFFFF")
        filtros.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for columna in range(5):
            filtros.grid_columnconfigure(columna, weight=1 if columna == 0 else 0)

        self._crear_filtro(filtros, "Buscar", self.busqueda_var, 0, width=280)
        self._crear_combo(filtros, "Segmento", self.segmento_var, crm.SEGMENTOS, 1, width=150)
        self._crear_filtro(filtros, "Desde", self.desde_var, 2, width=120, placeholder="AAAA-MM-DD")
        self._crear_filtro(filtros, "Hasta", self.hasta_var, 3, width=120, placeholder="AAAA-MM-DD")
        self._crear_combo(
            filtros,
            "Orden",
            self.orden_var,
            ("total_comprado", "numero_compras", "ticket_promedio", "ultima_compra"),
            4,
            width=155,
        )
        self.busqueda_var.trace_add("write", self._programar_busqueda)

        tarjetas = ctk.CTkFrame(raiz, fg_color="transparent")
        tarjetas.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for columna in range(5):
            tarjetas.grid_columnconfigure(columna, weight=1)
        self._crear_tarjeta(tarjetas, 0, "Total clientas", self.metricas_vars["total_clientas"], "#1D4ED8")
        self._crear_tarjeta(tarjetas, 1, "Activas 30 dias", self.metricas_vars["activas"], "#0F766E")
        self._crear_tarjeta(tarjetas, 2, "Dormidas", self.metricas_vars["dormidas"], "#6B7280")
        self._crear_tarjeta(tarjetas, 3, "VIP", self.metricas_vars["vip"], "#9B4DCA")
        self._crear_tarjeta(tarjetas, 4, "Ticket promedio", self.metricas_vars["ticket"], "#B45309")

        contenido = ctk.CTkFrame(raiz, fg_color="transparent")
        contenido.grid(row=3, column=0, sticky="nsew")
        contenido.grid_columnconfigure(0, weight=3)
        contenido.grid_columnconfigure(1, weight=2)
        contenido.grid_rowconfigure(0, weight=1)

        self._construir_ranking(contenido)
        self._construir_detalle(contenido)

    def _crear_filtro(self, parent, etiqueta, variable, columna, width, placeholder=""):
        bloque = ctk.CTkFrame(parent, fg_color="transparent")
        bloque.grid(row=0, column=columna, sticky="ew", padx=(12 if columna == 0 else 5, 5), pady=9)
        ctk.CTkLabel(bloque, text=etiqueta, font=("Segoe UI", 11), text_color="#4B5563").pack(anchor="w")
        entrada = ctk.CTkEntry(bloque, textvariable=variable, width=width, height=34, corner_radius=5, placeholder_text=placeholder)
        entrada.pack(fill="x")
        entrada.bind("<Return>", lambda _event: self.cargar_datos())

    def _crear_combo(self, parent, etiqueta, variable, valores, columna, width):
        bloque = ctk.CTkFrame(parent, fg_color="transparent")
        bloque.grid(row=0, column=columna, sticky="ew", padx=5, pady=9)
        ctk.CTkLabel(bloque, text=etiqueta, font=("Segoe UI", 11), text_color="#4B5563").pack(anchor="w")
        combo = ctk.CTkComboBox(
            bloque,
            variable=variable,
            values=list(valores),
            width=width,
            height=34,
            corner_radius=5,
            command=lambda _valor: self.cargar_datos(),
        )
        combo.pack(fill="x")

    def _crear_tarjeta(self, parent, columna, etiqueta, variable, color):
        tarjeta = ctk.CTkFrame(parent, corner_radius=6, fg_color="#FFFFFF")
        tarjeta.grid(row=0, column=columna, sticky="ew", padx=(0 if columna == 0 else 5, 5), pady=0)
        ctk.CTkLabel(tarjeta, text=etiqueta, font=("Segoe UI", 11), text_color="#6B7280").pack(anchor="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(tarjeta, textvariable=variable, font=("Segoe UI", 20, "bold"), text_color=color).pack(anchor="w", padx=12, pady=(1, 10))

    def _construir_ranking(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=6, fg_color="#FFFFFF")
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="Ranking comercial", font=("Segoe UI", 15, "bold"), text_color="#1F2937").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 7)
        )

        tabla_frame = ttk.Frame(frame)
        tabla_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tabla_frame.columnconfigure(0, weight=1)
        tabla_frame.rowconfigure(0, weight=1)
        columnas = ("nombre", "telefono", "total", "compras", "ticket", "ultima", "frecuencia", "indice", "segmento")
        self.tabla = ttk.Treeview(tabla_frame, columns=columnas, show="headings", selectmode="browse")
        encabezados = {
            "nombre": "Nombre",
            "telefono": "Telefono",
            "total": "Total comprado",
            "compras": "Compras",
            "ticket": "Ticket prom.",
            "ultima": "Ultima compra",
            "frecuencia": "Cada cuanto",
            "indice": "Indice",
            "segmento": "Segmento",
        }
        anchos = {"nombre": 180, "telefono": 100, "total": 115, "compras": 72, "ticket": 100, "ultima": 105, "frecuencia": 95, "indice": 65, "segmento": 100}
        for columna in columnas:
            self.tabla.heading(columna, text=encabezados[columna])
            self.tabla.column(columna, width=anchos[columna], minwidth=55, anchor="w")
        self.tabla.grid(row=0, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=self.tabla.yview)
        scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.tabla.bind("<<TreeviewSelect>>", self._al_seleccionar_clienta)

    def _construir_detalle(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=6, fg_color="#FFFFFF")
        frame.grid(row=0, column=1, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="Ficha de clienta", font=("Segoe UI", 15, "bold"), text_color="#1F2937").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 7)
        )
        self.detalle_scroll = ctk.CTkScrollableFrame(frame, corner_radius=0, fg_color="#FFFFFF")
        self.detalle_scroll.grid(row=1, column=0, sticky="nsew", padx=7, pady=(0, 7))
        self._mostrar_vacio_detalle("Seleccione una clienta del ranking.")

    def _filtros_actuales(self):
        segmento = self.segmento_var.get().strip()
        return {
            "q": self.busqueda_var.get().strip(),
            "segmento": None if segmento in ("", "TODAS") else segmento,
            "desde": self.desde_var.get().strip(),
            "hasta": self.hasta_var.get().strip(),
        }

    def _programar_busqueda(self, *_args):
        if getattr(self, "_busqueda_pendiente", None):
            self.win.after_cancel(self._busqueda_pendiente)
        self._busqueda_pendiente = self.win.after(450, self.cargar_datos)

    def cargar_datos(self):
        if not self.win.winfo_exists():
            return
        filtros = self._filtros_actuales()
        seleccionado = self._cliente_seleccionado_id() or self.cliente_inicial_id
        try:
            resumen = crm.obtener_resumen(filtros)
            ranking = crm.listar_ranking(filtros, orden=self.orden_var.get().strip(), limit=100)
            try:
                self.graficas = crm.obtener_graficas(filtros)
            except Exception as exc:
                self.graficas = {}
                log_error("hilorama_desktop", "No se pudieron cargar las graficas de clientas", exc)
            self._mostrar_resumen(resumen)
            self._mostrar_ranking(ranking)
            log_info("hilorama_desktop", f"CRM clientas actualizado: {len(ranking)} filas")
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar CRM de clientas", exc)
            messagebox.showerror("Clientas", f"No se pudo cargar el CRM de clientas.\n\n{exc}", parent=self.win)
            return

        if seleccionado:
            self._seleccionar_por_id(seleccionado)
        elif not ranking:
            self._mostrar_vacio_detalle("No hay clientas que coincidan con los filtros.")

    def _mostrar_resumen(self, resumen):
        self.metricas_vars["total_clientas"].set(str(resumen.get("total_clientas", 0)))
        self.metricas_vars["activas"].set(str(resumen.get("clientas_activas_30d", 0)))
        self.metricas_vars["dormidas"].set(str(resumen.get("clientas_dormidas_60d", 0)))
        self.metricas_vars["vip"].set(str(resumen.get("clientas_vip", 0)))
        self.metricas_vars["ticket"].set(_moneda(resumen.get("ticket_promedio_general")))

    def _mostrar_ranking(self, ranking):
        self.ranking_por_id = {str(fila.get("cliente_id")): fila for fila in ranking if fila.get("cliente_id") is not None}
        for item in self.tabla.get_children():
            self.tabla.delete(item)
        for fila in ranking:
            cliente_id = str(fila.get("cliente_id"))
            frecuencia = fila.get("frecuencia_promedio_dias")
            frecuencia_texto = f"{round(float(frecuencia))} dias" if frecuencia not in (None, "") else "-"
            segmento = fila.get("segmento") or "SIN_COMPRAS"
            self.tabla.insert(
                "",
                "end",
                iid=cliente_id,
                values=(
                    fila.get("nombre") or "Sin nombre",
                    fila.get("telefono") or "-",
                    _moneda(fila.get("total_comprado")),
                    fila.get("numero_compras") or 0,
                    _moneda(fila.get("ticket_promedio")),
                    fila.get("ultima_compra") or "-",
                    frecuencia_texto,
                    fila.get("indice_compra") or 0,
                    _nombre_segmento(segmento),
                ),
                tags=(segmento,),
            )
        for segmento, color in _COLORES_SEGMENTO.items():
            self.tabla.tag_configure(segmento, foreground=color)

    def _cliente_seleccionado_id(self):
        seleccion = self.tabla.selection()
        return seleccion[0] if seleccion else None

    def _seleccionar_por_id(self, cliente_id):
        cliente_id = str(cliente_id)
        if cliente_id not in self.ranking_por_id:
            return
        self.tabla.selection_set(cliente_id)
        self.tabla.focus(cliente_id)
        self.tabla.see(cliente_id)
        self._cargar_detalle(cliente_id)
        self.cliente_inicial_id = None

    def _al_seleccionar_clienta(self, _event=None):
        cliente_id = self._cliente_seleccionado_id()
        if cliente_id:
            self._cargar_detalle(cliente_id)

    def _cargar_detalle(self, cliente_id):
        try:
            self.analitica_actual = crm.obtener_analitica_clienta(cliente_id)
            self._mostrar_detalle(self.analitica_actual)
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al cargar ficha CRM de clienta {cliente_id}", exc)
            self._mostrar_vacio_detalle(f"No se pudo cargar la ficha de la clienta.\n{exc}")

    def _limpiar_detalle(self):
        for child in self.detalle_scroll.winfo_children():
            child.destroy()

    def _mostrar_vacio_detalle(self, texto):
        self._limpiar_detalle()
        ctk.CTkLabel(
            self.detalle_scroll,
            text=texto,
            justify="left",
            wraplength=360,
            text_color="#6B7280",
            font=("Segoe UI", 13),
        ).pack(anchor="nw", padx=8, pady=10)

    def _mostrar_detalle(self, analitica):
        self._limpiar_detalle()
        segmento = analitica.get("segmento") or "SIN_COMPRAS"
        color = _COLORES_SEGMENTO.get(segmento, "#475569")
        nombre = analitica.get("nombre") or "Sin nombre"
        ctk.CTkLabel(self.detalle_scroll, text=nombre, font=("Segoe UI", 18, "bold"), text_color="#111827").pack(anchor="w", padx=6, pady=(6, 0))
        ctk.CTkLabel(
            self.detalle_scroll,
            text=f"{analitica.get('telefono') or 'Sin telefono'}  |  {_nombre_segmento(segmento)}",
            font=("Segoe UI", 12, "bold"),
            text_color=color,
        ).pack(anchor="w", padx=6, pady=(0, 7))

        direccion = _formatear_direccion(analitica.get("direccion"))
        if direccion:
            self._seccion_detalle("Direccion", direccion)

        metricas = (
            ("Total comprado", _moneda(analitica.get("total_comprado"))),
            ("Compras", str(analitica.get("numero_compras") or 0)),
            ("Ticket promedio", _moneda(analitica.get("ticket_promedio"))),
            ("Primera compra", analitica.get("primera_compra") or "-"),
            ("Ultima compra", analitica.get("ultima_compra") or "-"),
            ("Frecuencia", _frecuencia(analitica.get("frecuencia_promedio_dias"))),
            ("Proxima compra estimada", analitica.get("proxima_compra_estimada") or "-"),
            ("Indice de compra", f"{analitica.get('indice_compra') or 0}/100"),
        )
        tarjeta = ctk.CTkFrame(self.detalle_scroll, corner_radius=5, fg_color="#F8FAFC")
        tarjeta.pack(fill="x", padx=5, pady=5)
        for indice, (etiqueta, valor) in enumerate(metricas):
            fila = ctk.CTkFrame(tarjeta, fg_color="transparent")
            fila.grid(row=indice, column=0, sticky="ew", padx=9, pady=2)
            fila.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(fila, text=etiqueta, font=("Segoe UI", 11), text_color="#64748B").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(fila, text=valor, font=("Segoe UI", 11, "bold"), text_color="#1F2937").grid(row=0, column=1, sticky="e")

        self._seccion_detalle("Marcas favoritas", _lista_favoritos(analitica.get("marcas_favoritas"), "marca"))
        self._seccion_detalle("Productos favoritos", _lista_productos(analitica.get("productos_favoritos")))
        alertas = analitica.get("alertas_comerciales") or []
        self._seccion_detalle("Alertas comerciales", "\n".join(f"- {fila.get('mensaje', '')}" for fila in alertas) or "Sin alertas.")

        acciones = ctk.CTkFrame(self.detalle_scroll, fg_color="transparent")
        acciones.pack(fill="x", padx=5, pady=(8, 12))
        for columna in range(2):
            acciones.grid_columnconfigure(columna, weight=1)
        ctk.CTkButton(acciones, text="Ver historial", height=34, corner_radius=5, command=self.mostrar_historial).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=3)
        ctk.CTkButton(acciones, text="Copiar mensaje", height=34, corner_radius=5, command=self.copiar_mensaje).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=3)
        ctk.CTkButton(acciones, text="Abrir WhatsApp", height=34, corner_radius=5, fg_color="#15803D", hover_color="#166534", command=self.abrir_whatsapp).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=3)
        ctk.CTkButton(acciones, text="Actualizar datos", height=34, corner_radius=5, fg_color="#475569", hover_color="#334155", command=self.actualizar_datos).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=3)

    def _seccion_detalle(self, titulo, contenido):
        ctk.CTkLabel(self.detalle_scroll, text=titulo, font=("Segoe UI", 12, "bold"), text_color="#334155").pack(anchor="w", padx=6, pady=(9, 1))
        ctk.CTkLabel(
            self.detalle_scroll,
            text=contenido or "-",
            justify="left",
            anchor="w",
            wraplength=355,
            font=("Segoe UI", 11),
            text_color="#334155",
        ).pack(anchor="w", fill="x", padx=6)

    def mostrar_historial(self):
        if not self.analitica_actual:
            return
        cliente_id = self.analitica_actual.get("cliente_id")
        try:
            historial = crm.obtener_historial_compras(cliente_id)
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al abrir historial de clienta {cliente_id}", exc)
            messagebox.showerror("Clientas", f"No se pudo cargar el historial.\n\n{exc}", parent=self.win)
            return

        win = ctk.CTkToplevel(self.win)
        win.title(f"Historial - {self.analitica_actual.get('nombre') or ''}")
        win.geometry("980x540")
        win.minsize(760, 400)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columnas = ("fecha", "folio", "total", "estado", "productos")
        tabla = ttk.Treeview(frame, columns=columnas, show="headings")
        for columna, titulo, ancho in (
            ("fecha", "Fecha", 105),
            ("folio", "Folio", 130),
            ("total", "Total", 100),
            ("estado", "Estado", 105),
            ("productos", "Productos", 480),
        ):
            tabla.heading(columna, text=titulo)
            tabla.column(columna, width=ancho, anchor="w")
        tabla.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tabla.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tabla.configure(yscrollcommand=scroll.set)
        for compra in historial:
            productos = ", ".join(_nombre_producto(item) for item in compra.get("productos", [])) or "Sin productos"
            tabla.insert("", "end", values=(compra.get("fecha") or "-", compra.get("folio") or "-", _moneda(compra.get("total")), compra.get("estado") or "-", productos))
        if not historial:
            tabla.insert("", "end", values=("-", "-", "$0.00", "-", "No hay compras pagadas o confirmadas."))

    def copiar_mensaje(self):
        if not self.analitica_actual:
            return
        mensaje = crm.generar_mensaje_whatsapp(self.analitica_actual)
        self.win.clipboard_clear()
        self.win.clipboard_append(mensaje)
        self.win.update_idletasks()
        messagebox.showinfo("Clientas", "Mensaje copiado al portapapeles.", parent=self.win)

    def abrir_whatsapp(self):
        if not self.analitica_actual:
            return
        telefono = "".join(caracter for caracter in str(self.analitica_actual.get("telefono") or "") if caracter.isdigit())
        if len(telefono) != 10:
            messagebox.showwarning("Clientas", "La clienta no tiene un telefono de 10 digitos.", parent=self.win)
            return
        mensaje = crm.generar_mensaje_whatsapp(self.analitica_actual)
        webbrowser.open(f"https://wa.me/52{telefono}?text={quote(mensaje)}")

    def actualizar_datos(self):
        if not self.analitica_actual or not self.editar_cliente_callback:
            return
        cliente_id = self.analitica_actual.get("cliente_id")
        try:
            self.editar_cliente_callback(cliente_id, self.win, on_guardar=lambda _cliente: self._cargar_detalle(cliente_id))
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al abrir edicion de clienta {cliente_id}", exc)
            messagebox.showerror("Clientas", f"No se pudo abrir la edicion de datos.\n\n{exc}", parent=self.win)

    def abrir_graficas(self):
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except Exception:
            messagebox.showinfo("Clientas", "Graficas no disponibles en esta instalacion.", parent=self.win)
            return

        datos = self.graficas or {}
        win = ctk.CTkToplevel(self.win)
        win.title("Graficas de clientas")
        win.geometry("1120x760")
        win.minsize(820, 560)
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        figura = Figure(figsize=(10.5, 7), dpi=100)
        figura.patch.set_facecolor("#FFFFFF")
        ejes = figura.subplots(2, 2)
        self._grafica_barras(ejes[0][0], datos.get("top_clientas_por_total", []), "nombre", "total_comprado", "Top por total", "#2563EB", moneda=True)
        self._grafica_barras(ejes[0][1], datos.get("top_clientas_por_compras", []), "nombre", "numero_compras", "Top por compras", "#0F766E")
        self._grafica_segmentos(ejes[1][0], datos.get("segmentos", []))
        self._grafica_barras(ejes[1][1], datos.get("ventas_por_mes", []), "mes", "total", "Ventas por mes", "#B45309", moneda=True)
        figura.tight_layout(pad=2.0)
        canvas = FigureCanvasTkAgg(figura, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    @staticmethod
    def _grafica_barras(eje, filas, campo_etiqueta, campo_valor, titulo, color, moneda=False):
        if not filas:
            eje.set_title(titulo)
            eje.text(0.5, 0.5, "Sin datos", ha="center", va="center", transform=eje.transAxes, color="#6B7280")
            eje.set_xticks([])
            return
        etiquetas = [str(fila.get(campo_etiqueta) or "-")[:18] for fila in filas]
        valores = [float(fila.get(campo_valor) or 0) for fila in filas]
        eje.bar(range(len(valores)), valores, color=color)
        eje.set_title(titulo)
        eje.set_xticks(range(len(etiquetas)))
        eje.set_xticklabels(etiquetas, rotation=32, ha="right", fontsize=8)
        if moneda:
            eje.set_ylabel("MXN")
        eje.grid(axis="y", alpha=0.2)

    @staticmethod
    def _grafica_segmentos(eje, filas):
        if not filas:
            eje.set_title("Segmentos")
            eje.text(0.5, 0.5, "Sin datos", ha="center", va="center", transform=eje.transAxes, color="#6B7280")
            eje.set_xticks([])
            return
        etiquetas = [_nombre_segmento(fila.get("segmento")) for fila in filas]
        valores = [int(fila.get("cantidad") or 0) for fila in filas]
        colores = [_COLORES_SEGMENTO.get(str(fila.get("segmento") or ""), "#64748B") for fila in filas]
        eje.pie(valores, labels=etiquetas, colors=colores, autopct="%1.0f%%", textprops={"fontsize": 8})
        eje.set_title("Segmentos")


def _moneda(valor):
    try:
        return f"${float(valor or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _frecuencia(valor):
    try:
        return f"Cada {round(float(valor))} dias"
    except (TypeError, ValueError):
        return "Sin frecuencia aun"


def _nombre_segmento(segmento):
    return _NOMBRES_SEGMENTO.get(str(segmento or ""), str(segmento or "Sin compras").replace("_", " ").title())


def _formatear_direccion(direccion):
    if not isinstance(direccion, dict):
        return str(direccion or "").strip()
    partes = [
        direccion.get("calle"),
        direccion.get("numero_ext") or direccion.get("numero_exterior"),
        direccion.get("numero_int") or direccion.get("numero_interior"),
        direccion.get("colonia"),
        direccion.get("codigo_postal") or direccion.get("cp"),
        direccion.get("municipio"),
        direccion.get("estado"),
    ]
    return ", ".join(str(parte).strip() for parte in partes if str(parte or "").strip())


def _lista_favoritos(filas, campo):
    partes = []
    for fila in list(filas or [])[:5]:
        nombre = str(fila.get(campo) or "").strip()
        if nombre:
            partes.append(f"{nombre} ({fila.get('cantidad') or 0} pzas)")
    return "\n".join(partes) or "Sin compras registradas."


def _lista_productos(filas):
    partes = [_nombre_producto(fila) for fila in list(filas or [])[:6]]
    return "\n".join(partes) or "Sin compras registradas."


def _nombre_producto(fila):
    datos = [fila.get("marca"), fila.get("hilo"), fila.get("codigo"), fila.get("color")]
    nombre = " ".join(str(valor).strip() for valor in datos if str(valor or "").strip())
    cantidad = fila.get("cantidad")
    return f"{nombre or 'Producto'} ({cantidad or 0} pzas)"
