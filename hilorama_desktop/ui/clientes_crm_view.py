"""Vista CRM de clientas compradoras para el modo API de Hilorama Desktop."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import time
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


def crear_vista_clientes_crm(parent, editar_cliente_callback=None):
    """Crea el CRM dentro del panel principal de Hilorama Desktop."""
    return ClientesCRMView(parent, editar_cliente_callback=editar_cliente_callback)


class ClientesCRMView(ctk.CTkFrame):
    """Contenedor embebible del CRM para el menu principal de Desktop."""
    def __init__(self, parent, editar_cliente_callback=None):
        super().__init__(parent, fg_color="#F4F5F7", corner_radius=0)
        self._controller = ClientesCrmWindow(
            self,
            editar_cliente_callback=editar_cliente_callback,
            embedded=True,
            host=self,
        )

    def mostrar_cliente_inicial(self, cliente):
        self._controller.mostrar_cliente_inicial(cliente)

    def seleccionar_cliente(self, cliente_id, abrir_historial=False):
        self._controller.seleccionar_cliente(cliente_id, abrir_historial=abrir_historial)


class ClientesCrmWindow:
    def __init__(self, parent, editar_cliente_callback=None, embedded=False, host=None):
        self.editar_cliente_callback = editar_cliente_callback
        self.ranking_por_id = {}
        self.analitica_actual = None
        self.cliente_inicial_id = None
        self.embedded = bool(embedded or host is not None)
        self._resultados_async = queue.Queue()
        self._carga_ranking_en_curso = False
        self._firma_carga_aplicada = None
        self._firma_carga_en_curso = None
        self._recarga_pendiente = False
        self._firma_tabla = None
        self._detalles_cache = {}
        self._historial_cache = {}
        self._graficas_cache = {}
        self._detalles_en_curso = set()
        self._historiales_en_curso = set()
        self._graficas_en_curso = set()
        self._ventanas_historial_pendientes = {}
        self._ventanas_graficas_pendientes = {}
        self._busqueda_pendiente = None
        self._historial_automatico_cliente_id = None

        if host is not None:
            self.win = host
        elif self.embedded:
            self.win = ctk.CTkFrame(parent, fg_color="#F4F5F7", corner_radius=0)
        else:
            self.win = ctk.CTkToplevel(parent)
            self.win.title("Clientas")
            self.win.geometry("1440x880")
            self.win.minsize(1180, 720)
            self.win.transient(parent.winfo_toplevel())
        self.win.configure(fg_color="#F4F5F7")

        self.busqueda_var = tk.StringVar()
        self.segmento_var = tk.StringVar(value="TODAS")
        self.desde_var = tk.StringVar()
        self.hasta_var = tk.StringVar()
        self.orden_var = tk.StringVar(value="total_comprado")
        self.limit_var = tk.StringVar(value="100")
        self.estado_carga_var = tk.StringVar(value="Cargando clientas...")
        self.metricas_vars = {
            "total_clientas": tk.StringVar(value="0"),
            "activas": tk.StringVar(value="0"),
            "dormidas": tk.StringVar(value="0"),
            "vip": tk.StringVar(value="0"),
            "ticket": tk.StringVar(value="$0.00"),
        }

        self._construir()
        self._mostrar_vacio_detalle("Cargando clientas...")
        self.win.after(40, self._procesar_resultados_async)
        self.win.after(80, lambda: self.cargar_datos(forzar=True))

    def mostrar_cliente_inicial(self, cliente):
        if isinstance(cliente, dict) and cliente.get("id") is not None:
            self.cliente_inicial_id = str(cliente.get("id"))

    def seleccionar_cliente(self, cliente_id, abrir_historial=False):
        cliente_id = str(cliente_id or "").strip()
        if not cliente_id:
            return
        self.cliente_inicial_id = cliente_id
        if abrir_historial:
            self._historial_automatico_cliente_id = cliente_id
        if cliente_id in self.ranking_por_id:
            self._seleccionar_por_id(cliente_id)
        else:
            self._cargar_detalle(cliente_id, forzar=True)

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
            text="Gráficas",
            width=112,
            height=34,
            corner_radius=6,
            command=self.abrir_graficas,
        ).grid(row=0, column=1, padx=(8, 8), pady=10)
        self.btn_actualizar = ctk.CTkButton(
            encabezado,
            text="Actualizar",
            width=112,
            height=34,
            corner_radius=6,
            fg_color="#0F766E",
            hover_color="#115E59",
            command=self.actualizar_crm,
        )
        self.btn_actualizar.grid(row=0, column=2, padx=(0, 12), pady=10)

        filtros = ctk.CTkFrame(raiz, corner_radius=6, fg_color="#FFFFFF")
        filtros.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for columna in range(6):
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
        self._crear_combo(filtros, "Mostrar", self.limit_var, ("100", "200", "Todas"), 5, width=100)
        self.busqueda_var.trace_add("write", self._programar_busqueda)

        tarjetas = ctk.CTkFrame(raiz, fg_color="transparent")
        tarjetas.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for columna in range(5):
            tarjetas.grid_columnconfigure(columna, weight=1)
        self._crear_tarjeta(tarjetas, 0, "Total clientas", self.metricas_vars["total_clientas"], "#1D4ED8")
        self._crear_tarjeta(tarjetas, 1, "Activas 30 días", self.metricas_vars["activas"], "#0F766E")
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
        encabezado = ctk.CTkFrame(frame, fg_color="transparent")
        encabezado.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 7))
        encabezado.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(encabezado, text="Ranking comercial", font=("Segoe UI", 15, "bold"), text_color="#1F2937").grid(
            row=0, column=0, sticky="w"
        )
        self.estado_carga_label = ctk.CTkLabel(
            encabezado,
            textvariable=self.estado_carga_var,
            font=("Segoe UI", 11),
            text_color="#64748B",
        )
        self.estado_carga_label.grid(row=0, column=1, sticky="e")

        tabla_frame = ttk.Frame(frame)
        tabla_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tabla_frame.columnconfigure(0, weight=1)
        tabla_frame.rowconfigure(0, weight=1)
        columnas = ("nombre", "telefono", "total", "compras", "ticket", "ultima", "frecuencia", "indice", "segmento")
        self.tabla = ttk.Treeview(tabla_frame, columns=columnas, show="headings", selectmode="browse")
        encabezados = {
            "nombre": "Nombre",
            "telefono": "Teléfono",
            "total": "Total comprado",
            "compras": "Compras",
            "ticket": "Ticket prom.",
            "ultima": "Última compra",
            "frecuencia": "Cada cuánto",
            "indice": "Índice",
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
        if self._busqueda_pendiente:
            try:
                self.win.after_cancel(self._busqueda_pendiente)
            except tk.TclError:
                pass
        self._busqueda_pendiente = self.win.after(400, self._ejecutar_busqueda_programada)

    def _ejecutar_busqueda_programada(self):
        self._busqueda_pendiente = None
        self.cargar_datos()

    def _limite_ranking(self):
        valor = self.limit_var.get().strip()
        if valor == "Todas":
            return 500
        try:
            return 200 if int(valor) >= 200 else 100
        except (TypeError, ValueError):
            return 100

    def _firma_carga_actual(self):
        filtros = self._filtros_actuales()
        return (
            filtros.get("q") or "",
            filtros.get("segmento") or "",
            filtros.get("desde") or "",
            filtros.get("hasta") or "",
            self.orden_var.get().strip() or "total_comprado",
            self._limite_ranking(),
        )

    def _firma_graficas_actual(self):
        filtros = self._filtros_actuales()
        return (
            filtros.get("q") or "",
            filtros.get("segmento") or "",
            filtros.get("desde") or "",
            filtros.get("hasta") or "",
        )

    def _vista_disponible(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _ejecutar_tarea_async(self, tipo, funcion, **contexto):
        """Ejecuta una llamada API sin tocar widgets desde el hilo secundario."""
        def worker():
            inicio = time.perf_counter()
            try:
                resultado = funcion()
                error = None
            except Exception as exc:  # La UI procesa el error de manera controlada.
                resultado = None
                error = exc
            self._resultados_async.put({
                "tipo": tipo,
                "resultado": resultado,
                "error": error,
                "segundos": time.perf_counter() - inicio,
                **contexto,
            })

        threading.Thread(target=worker, name=f"crm-{tipo}", daemon=True).start()

    def cargar_datos(self, forzar=False):
        if not self._vista_disponible():
            return
        firma = self._firma_carga_actual()
        if not forzar and firma == self._firma_carga_aplicada and not self._carga_ranking_en_curso:
            return
        if self._carga_ranking_en_curso:
            self._recarga_pendiente = True
            return

        filtros = self._filtros_actuales()
        seleccionado = self._cliente_seleccionado_id() or self.cliente_inicial_id
        orden = self.orden_var.get().strip() or "total_comprado"
        limite = self._limite_ranking()
        self._carga_ranking_en_curso = True
        self._firma_carga_en_curso = firma
        self.btn_actualizar.configure(state="disabled")
        self.estado_carga_var.set("Cargando clientas...")
        if not seleccionado:
            self._mostrar_vacio_detalle("Cargando clientas...")
        self._ejecutar_tarea_async(
            "panoramica",
            lambda: crm.cargar_panoramica(filtros=filtros, orden=orden, limit=limite),
            firma=firma,
            seleccionado=seleccionado,
            forzar=bool(forzar),
        )

    def actualizar_crm(self):
        """Refresca los datos comerciales solicitados por la usuaria."""
        self._detalles_cache.clear()
        self._historial_cache.clear()
        self._graficas_cache.clear()
        self.cargar_datos(forzar=True)

    def _procesar_resultados_async(self):
        if not self._vista_disponible():
            return
        while True:
            try:
                resultado = self._resultados_async.get_nowait()
            except queue.Empty:
                break
            self._aplicar_resultado_async(resultado)
        if self._vista_disponible():
            self.win.after(60, self._procesar_resultados_async)

    def _aplicar_resultado_async(self, resultado):
        tipo = resultado.get("tipo")
        segundos = float(resultado.get("segundos") or 0)
        if tipo == "panoramica":
            self._aplicar_panoramica(resultado, segundos)
        elif tipo == "detalle":
            self._aplicar_detalle(resultado, segundos)
        elif tipo == "historial":
            self._aplicar_historial(resultado, segundos)
        elif tipo == "graficas":
            self._aplicar_graficas(resultado, segundos)

    def _aplicar_panoramica(self, resultado, segundos):
        self._carga_ranking_en_curso = False
        self._firma_carga_en_curso = None
        self.btn_actualizar.configure(state="normal")
        error = resultado.get("error")
        firma = resultado.get("firma")
        if error:
            log_error("hilorama_desktop", "Error al cargar resumen y ranking CRM", error)
            if self._manejar_sesion_expirada(error):
                return
            self.estado_carga_var.set("No se pudo cargar. Revise su conexión o sesión.")
            self._mostrar_vacio_detalle("No se pudo cargar el CRM de clientas. Puede intentarlo nuevamente.")
            if self._recarga_pendiente:
                self._recarga_pendiente = False
                self.cargar_datos(forzar=True)
            return

        # Si el usuario cambió filtros durante la petición, se descarta esta vista.
        if firma != self._firma_carga_actual():
            self._recarga_pendiente = False
            self.cargar_datos(forzar=True)
            return

        datos = resultado.get("resultado") or {}
        ranking = list(datos.get("ranking") or [])
        self._mostrar_resumen(datos.get("resumen") or {})
        self._mostrar_ranking(ranking, firma=firma, forzar=bool(resultado.get("forzar")))
        self._firma_carga_aplicada = firma
        self.estado_carga_var.set(f"{len(ranking)} clientas mostradas")
        log_info("hilorama_desktop", f"CRM resumen/ranking: {segundos:.3f}s")

        seleccionado = resultado.get("seleccionado")
        if seleccionado:
            self._seleccionar_por_id(seleccionado)
        elif not ranking:
            self._mostrar_vacio_detalle("No hay clientas que coincidan con los filtros.")

        if self._recarga_pendiente:
            self._recarga_pendiente = False
            self.cargar_datos(forzar=True)

    def _aplicar_detalle(self, resultado, segundos):
        cliente_id = str(resultado.get("cliente_id"))
        self._detalles_en_curso.discard(cliente_id)
        error = resultado.get("error")
        if error:
            log_error("hilorama_desktop", f"Error al cargar ficha CRM de clienta {cliente_id}", error)
            if self._manejar_sesion_expirada(error):
                return
            if self._cliente_seleccionado_id() == cliente_id:
                self._mostrar_vacio_detalle("No se pudo cargar la ficha de la clienta. Inténtelo nuevamente.")
            return
        analitica = resultado.get("resultado") or {}
        self._detalles_cache[cliente_id] = analitica
        log_info("hilorama_desktop", f"CRM ficha: {segundos:.3f}s")
        if self._cliente_seleccionado_id() == cliente_id or self.cliente_inicial_id == cliente_id:
            self.analitica_actual = analitica
            self._mostrar_detalle(analitica)
            self.cliente_inicial_id = None
            if self._historial_automatico_cliente_id == cliente_id:
                self._historial_automatico_cliente_id = None
                self.win.after(20, self.mostrar_historial)

    def _aplicar_historial(self, resultado, segundos):
        cliente_id = str(resultado.get("cliente_id"))
        self._historiales_en_curso.discard(cliente_id)
        ventanas = self._ventanas_historial_pendientes.pop(cliente_id, [])
        error = resultado.get("error")
        if error:
            log_error("hilorama_desktop", f"Error al cargar historial CRM de clienta {cliente_id}", error)
            if self._manejar_sesion_expirada(error):
                return
            for ventana in ventanas:
                self._mostrar_error_historial(ventana, "No se pudo cargar el historial de compras.")
            return
        historial = list(resultado.get("resultado") or [])
        self._historial_cache[cliente_id] = historial
        log_info("hilorama_desktop", f"CRM historial: {segundos:.3f}s")
        for ventana in ventanas:
            self._llenar_historial_ventana(ventana, historial)

    def _aplicar_graficas(self, resultado, segundos):
        firma = resultado.get("firma")
        self._graficas_en_curso.discard(firma)
        ventanas = self._ventanas_graficas_pendientes.pop(firma, [])
        error = resultado.get("error")
        if error:
            log_error("hilorama_desktop", "Error al cargar gráficas CRM", error)
            if self._manejar_sesion_expirada(error):
                return
            for ventana in ventanas:
                ventana.mostrar_error("No se pudieron cargar las gráficas. Revise su conexión o sesión.")
            return
        graficas = resultado.get("resultado") or {}
        self._graficas_cache[firma] = graficas
        log_info("hilorama_desktop", f"CRM gráficas: {segundos:.3f}s")
        for ventana in ventanas:
            ventana.cargar_datos(graficas)

    def _manejar_sesion_expirada(self, error):
        if getattr(error, "status", None) != 401:
            return False

        current = self.win
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            handler = getattr(current, "manejar_sesion_expirada", None)
            if callable(handler):
                handler("La sesión expiró. Cierra y vuelve a iniciar sesión.")
                return True
            current = getattr(current, "master", None)
        return False

    def _mostrar_resumen(self, resumen):
        self.metricas_vars["total_clientas"].set(str(resumen.get("total_clientas", 0)))
        self.metricas_vars["activas"].set(str(resumen.get("clientas_activas_30d", 0)))
        self.metricas_vars["dormidas"].set(str(resumen.get("clientas_dormidas_60d", 0)))
        self.metricas_vars["vip"].set(str(resumen.get("clientas_vip", 0)))
        self.metricas_vars["ticket"].set(_moneda(resumen.get("ticket_promedio_general")))

    def _mostrar_ranking(self, ranking, firma=None, forzar=False):
        if not forzar and firma is not None and firma == self._firma_tabla:
            return
        self.ranking_por_id = {str(fila.get("cliente_id")): fila for fila in ranking if fila.get("cliente_id") is not None}
        for item in self.tabla.get_children():
            self.tabla.delete(item)
        for fila in ranking:
            cliente_id = str(fila.get("cliente_id"))
            frecuencia = fila.get("frecuencia_promedio_dias")
            frecuencia_texto = _frecuencia(frecuencia) if frecuencia not in (None, "") else "-"
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
                    _fecha_clara(fila.get("ultima_compra")) or "-",
                    frecuencia_texto,
                    fila.get("indice_compra") or 0,
                    _nombre_segmento(segmento),
                ),
                tags=(segmento,),
            )
        for segmento, color in _COLORES_SEGMENTO.items():
            self.tabla.tag_configure(segmento, foreground=color)
        self._firma_tabla = firma

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

    def _cargar_detalle(self, cliente_id, forzar=False):
        cliente_id = str(cliente_id)
        if not forzar and cliente_id in self._detalles_cache:
            self.analitica_actual = self._detalles_cache[cliente_id]
            self._mostrar_detalle(self.analitica_actual)
            return
        if cliente_id in self._detalles_en_curso:
            return
        self._detalles_en_curso.add(cliente_id)
        self._mostrar_vacio_detalle("Cargando ficha de la clienta...")
        self._ejecutar_tarea_async(
            "detalle",
            lambda: crm.obtener_analitica_clienta(cliente_id),
            cliente_id=cliente_id,
        )

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
            text=f"{analitica.get('telefono') or 'Sin teléfono'}  |  {_nombre_segmento(segmento)}",
            font=("Segoe UI", 12, "bold"),
            text_color=color,
        ).pack(anchor="w", padx=6, pady=(0, 7))

        direccion = _formatear_direccion(analitica.get("direccion"))
        if direccion:
            self._seccion_detalle("Dirección", direccion)

        metricas = (
            ("Total comprado", _moneda(analitica.get("total_comprado"))),
            ("Compras", str(analitica.get("numero_compras") or 0)),
            ("Ticket promedio", _moneda(analitica.get("ticket_promedio"))),
            ("Primera compra", _fecha_clara(analitica.get("primera_compra")) or "-"),
            ("Última compra", _fecha_clara(analitica.get("ultima_compra")) or "-"),
            ("Frecuencia", _frecuencia(analitica.get("frecuencia_promedio_dias"))),
            ("Próxima compra estimada", _fecha_clara(analitica.get("proxima_compra_estimada")) or "-"),
            ("Índice de compra", f"{analitica.get('indice_compra') or 0}/100"),
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
        cliente_id = str(self.analitica_actual.get("cliente_id"))
        ventana = self._crear_ventana_historial()
        if cliente_id in self._historial_cache:
            self._llenar_historial_ventana(ventana, self._historial_cache[cliente_id])
            return
        self._ventanas_historial_pendientes.setdefault(cliente_id, []).append(ventana)
        if cliente_id in self._historiales_en_curso:
            return
        self._historiales_en_curso.add(cliente_id)
        self._ejecutar_tarea_async(
            "historial",
            lambda: crm.obtener_historial_compras(cliente_id),
            cliente_id=cliente_id,
        )

    def _crear_ventana_historial(self):
        win = ctk.CTkToplevel(self.win)
        win.title(f"Historial - {self.analitica_actual.get('nombre') or ''}")
        win.geometry("980x540")
        win.minsize(760, 400)
        ctk.CTkLabel(
            win,
            text="Cargando historial de compras...",
            font=("Segoe UI", 13),
            text_color="#64748B",
        ).pack(fill="both", expand=True, padx=20, pady=20)
        return win

    def _mostrar_error_historial(self, win, texto):
        try:
            if not win.winfo_exists():
                return
            for child in win.winfo_children():
                child.destroy()
            ctk.CTkLabel(win, text=texto, font=("Segoe UI", 13), text_color="#B91C1C").pack(
                fill="both", expand=True, padx=20, pady=20
            )
        except tk.TclError:
            return

    def _llenar_historial_ventana(self, win, historial):
        try:
            if not win.winfo_exists():
                return
            for child in win.winfo_children():
                child.destroy()
        except tk.TclError:
            return
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
            tabla.insert("", "end", values=(_fecha_clara(compra.get("fecha")) or "-", compra.get("folio") or "-", _moneda(compra.get("total")), compra.get("estado") or "-", productos))
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
            self.editar_cliente_callback(
                cliente_id,
                self.win,
                on_guardar=lambda _cliente: self._refrescar_detalle_cliente(cliente_id),
            )
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al abrir edicion de clienta {cliente_id}", exc)
            messagebox.showerror("Clientas", f"No se pudo abrir la edicion de datos.\n\n{exc}", parent=self.win)

    def _refrescar_detalle_cliente(self, cliente_id):
        cliente_id = str(cliente_id)
        self._detalles_cache.pop(cliente_id, None)
        self._historial_cache.pop(cliente_id, None)
        self._cargar_detalle(cliente_id, forzar=True)

    def abrir_graficas(self):
        firma = self._firma_graficas_actual()
        ventana = GraficasClientasWindow(self.win)
        if firma in self._graficas_cache:
            ventana.cargar_datos(self._graficas_cache[firma])
            return
        self._ventanas_graficas_pendientes.setdefault(firma, []).append(ventana)
        if firma in self._graficas_en_curso:
            return
        self._graficas_en_curso.add(firma)
        filtros = self._filtros_actuales()
        self._ejecutar_tarea_async(
            "graficas",
            lambda: crm.obtener_graficas(filtros),
            firma=firma,
        )


class GraficasClientasWindow:
    """Gráficas ligeras hechas con Canvas nativo, sin dependencia de Matplotlib."""

    _CONFIGURACION = {
        "total": ("Top total", "top_clientas_por_total", "nombre", "total_comprado", "#2563EB", True),
        "compras": ("Compras", "top_clientas_por_compras", "nombre", "numero_compras", "#0F766E", False),
        "segmentos": ("Segmentos", "segmentos", "segmento", "cantidad", "#8B5CF6", False),
        "mensual": ("Ventas por mes", "ventas_por_mes", "mes", "total", "#B45309", True),
    }

    def __init__(self, parent):
        self.win = ctk.CTkToplevel(parent)
        self.win.title("Gráficas de clientas")
        self.win.geometry("980x650")
        self.win.minsize(720, 460)
        self._datos = {}
        self._error = ""
        self._canvas = {}

        raiz = ttk.Frame(self.win, padding=10)
        raiz.pack(fill="both", expand=True)
        self.estado_var = tk.StringVar(value="Cargando gráficas...")
        ttk.Label(raiz, textvariable=self.estado_var, foreground="#64748B").pack(anchor="w", pady=(0, 6))
        pestañas = ttk.Notebook(raiz)
        pestañas.pack(fill="both", expand=True)
        for clave, (titulo, *_resto) in self._CONFIGURACION.items():
            pagina = ttk.Frame(pestañas)
            pestañas.add(pagina, text=titulo)
            canvas = tk.Canvas(pagina, background="#FFFFFF", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Configure>", lambda _evento, nombre=clave: self._dibujar(nombre))
            self._canvas[clave] = canvas

    def _existe(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def cargar_datos(self, datos):
        if not self._existe():
            return
        self._datos = dict(datos or {})
        self._error = ""
        self.estado_var.set("Datos comerciales actualizados")
        for clave in self._canvas:
            self._dibujar(clave)

    def mostrar_error(self, texto):
        if not self._existe():
            return
        self._error = texto
        self.estado_var.set(texto)
        for clave in self._canvas:
            self._dibujar(clave)

    def _dibujar(self, clave):
        if not self._existe():
            return
        canvas = self._canvas[clave]
        canvas.delete("all")
        ancho = max(canvas.winfo_width(), 640)
        alto = max(canvas.winfo_height(), 380)
        if self._error:
            canvas.create_text(ancho / 2, alto / 2, text=self._error, fill="#B91C1C", font=("Segoe UI", 12))
            return

        titulo, clave_datos, campo_etiqueta, campo_valor, color, moneda = self._CONFIGURACION[clave]
        filas = list(self._datos.get(clave_datos) or [])[:10]
        canvas.create_text(18, 20, anchor="w", text=titulo, fill="#1F2937", font=("Segoe UI", 13, "bold"))
        if not filas:
            canvas.create_text(
                ancho / 2,
                alto / 2,
                text="Sin datos suficientes para graficar",
                fill="#6B7280",
                font=("Segoe UI", 12),
            )
            return

        valores = [_numero_grafica(fila.get(campo_valor)) for fila in filas]
        maximo = max(valores) if valores else 0
        if maximo <= 0:
            maximo = 1
        margen_izquierdo = min(230, max(150, int(ancho * 0.30)))
        margen_derecho = 94
        inicio_y = 48
        alto_util = max(1, alto - inicio_y - 22)
        paso = max(28, alto_util / len(filas))
        alto_barra = min(22, max(12, paso - 9))
        ancho_barra = max(80, ancho - margen_izquierdo - margen_derecho)
        for indice, (fila, valor) in enumerate(zip(filas, valores)):
            y = inicio_y + indice * paso
            etiqueta = fila.get(campo_etiqueta)
            if clave == "segmentos":
                etiqueta = _nombre_segmento(etiqueta)
                color_fila = _COLORES_SEGMENTO.get(str(fila.get(campo_etiqueta) or ""), color)
            else:
                color_fila = color
            texto = _recortar_texto(etiqueta or "-", 26)
            canvas.create_text(margen_izquierdo - 8, y + alto_barra / 2, anchor="e", text=texto, fill="#334155", font=("Segoe UI", 10))
            final = margen_izquierdo + (valor / maximo) * ancho_barra
            canvas.create_rectangle(margen_izquierdo, y, final, y + alto_barra, fill=color_fila, outline="")
            valor_texto = _moneda(valor) if moneda else f"{int(round(valor)):,}"
            canvas.create_text(min(final + 7, ancho - 6), y + alto_barra / 2, anchor="w", text=valor_texto, fill="#1F2937", font=("Segoe UI", 10, "bold"))


def _moneda(valor):
    try:
        return f"${float(valor or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _numero_grafica(valor):
    try:
        return max(0.0, float(valor or 0))
    except (TypeError, ValueError):
        return 0.0


def _recortar_texto(valor, limite):
    texto = str(valor or "").strip()
    return texto if len(texto) <= limite else f"{texto[:max(1, limite - 3)]}..."


def _fecha_clara(valor):
    texto = str(valor or "").strip()
    if len(texto) >= 10 and texto[4:5] == "-" and texto[7:8] == "-":
        return f"{texto[8:10]}/{texto[5:7]}/{texto[:4]}"
    return texto


def _frecuencia(valor):
    try:
        return f"Cada {round(float(valor))} días"
    except (TypeError, ValueError):
        return "Sin frecuencia aún"


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
