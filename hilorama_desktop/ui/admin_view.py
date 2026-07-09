import tkinter as tk
from tkinter import messagebox, ttk

try:
    from ..api_client.render_api_client import RenderApiClient, RenderApiError
    from ..utils.logger import log_error, log_info
except ImportError:
    from api_client.render_api_client import RenderApiClient, RenderApiError
    from utils.logger import log_error, log_info


CLIENTE_COLUMNS = (
    ("id", "ID", 70),
    ("contacto", "Nombre cliente", 170),
    ("nombre_negocio", "Negocio", 220),
    ("estado", "Estado", 110),
    ("fecha_vencimiento", "Vencimiento", 120),
    ("created_at", "Creado", 160),
)

SESION_COLUMNS = (
    ("usuario", "Usuario", 150),
    ("nombre_negocio", "Cliente", 200),
    ("modulo_actual", "Modulo", 120),
    ("app_version", "Version", 110),
    ("ip", "IP", 140),
    ("ultimo_heartbeat", "Ultimo heartbeat", 170),
    ("estado", "Estado", 100),
)

AUDITORIA_COLUMNS = (
    ("created_at", "Fecha", 170),
    ("usuario", "Usuario", 140),
    ("evento", "Accion", 160),
    ("nombre_negocio", "Cliente", 200),
    ("detalle", "Detalle", 320),
)

FORM_FIELDS = (
    ("nombre_negocio", "Negocio"),
    ("contacto", "Nombre/contacto"),
    ("telefono", "Telefono"),
    ("email", "Email"),
    ("fecha_vencimiento", "Fecha vencimiento"),
    ("max_dispositivos", "Max dispositivos"),
    ("plan", "Plan"),
    ("notas_admin", "Notas admin"),
)


def crear_vista_admin(parent, auth_service=None, session=None):
    if not _es_super_admin(session):
        log_info("hilorama_desktop", "Intento de abrir Administracion sin rol super_admin")
        return _crear_no_autorizado(parent)

    api = getattr(auth_service, "api", None) or RenderApiClient()
    return AdminView(parent, api, session)


def _es_super_admin(session):
    usuario = (session or {}).get("usuario") or {}
    permisos = (session or {}).get("permisos") or []
    return usuario.get("rol") == "super_admin" or "super_admin" in permisos


def _token(session):
    return (session or {}).get("token")


def _lista(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "clientes", "sesiones", "auditoria"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _valor(row, key):
    value = row.get(key, "") if isinstance(row, dict) else ""
    return "" if value is None else str(value)


class AdminView(ttk.Frame):
    def __init__(self, parent, api, session):
        super().__init__(parent, padding=10)
        self.api = api
        self.session = session or {}
        self.clientes = []
        self.sesiones = []
        self.auditoria = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(
            self,
            text="Administracion",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="nsew")

        self._crear_tab_clientes()
        self._crear_tab_sesiones()
        self._crear_tab_auditoria()

        self.after(100, self.cargar_todo)

    def cargar_todo(self):
        self.cargar_clientes()
        self.cargar_sesiones()
        self.cargar_auditoria()

    def _crear_tab_clientes(self):
        tab = ttk.Frame(self.tabs, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.tabs.add(tab, text="Clientes")

        self.tree_clientes = _crear_tree(tab, CLIENTE_COLUMNS)
        self.tree_clientes.grid(row=0, column=0, sticky="nsew")

        acciones = ttk.Frame(tab)
        acciones.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        botones = [
            ("Actualizar", self.cargar_clientes),
            ("Crear cliente", self.crear_cliente),
            ("Editar cliente", self.editar_cliente),
            ("Suspender", lambda: self._accion_estado("suspender")),
            ("Bloquear", lambda: self._accion_estado("bloquear")),
            ("Reactivar", lambda: self._accion_estado("reactivar")),
        ]
        for texto, comando in botones:
            ttk.Button(acciones, text=texto, command=comando).pack(side="left", padx=(0, 6))

    def _crear_tab_sesiones(self):
        tab = ttk.Frame(self.tabs, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.tabs.add(tab, text="Sesiones activas")

        self.tree_sesiones = _crear_tree(tab, SESION_COLUMNS)
        self.tree_sesiones.grid(row=0, column=0, sticky="nsew")

        acciones = ttk.Frame(tab)
        acciones.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(acciones, text="Actualizar sesiones", command=self.cargar_sesiones).pack(side="left")

    def _crear_tab_auditoria(self):
        tab = ttk.Frame(self.tabs, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.tabs.add(tab, text="Auditoria")

        self.tree_auditoria = _crear_tree(tab, AUDITORIA_COLUMNS)
        self.tree_auditoria.grid(row=0, column=0, sticky="nsew")

        acciones = ttk.Frame(tab)
        acciones.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(acciones, text="Actualizar auditoria", command=self.cargar_auditoria).pack(side="left")

    def cargar_clientes(self):
        try:
            log_info("hilorama_desktop", "Cargando clientes admin")
            self.clientes = _lista(self.api.admin_listar_clientes(token=_token(self.session)))
            _llenar_tree(self.tree_clientes, CLIENTE_COLUMNS, self.clientes)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar clientes admin", exc)
            _mostrar_error(self, "No se pudieron cargar los clientes.", exc)

    def cargar_sesiones(self):
        try:
            log_info("hilorama_desktop", "Cargando sesiones activas admin")
            self.sesiones = _lista(self.api.admin_sesiones_activas(token=_token(self.session)))
            _llenar_tree(self.tree_sesiones, SESION_COLUMNS, self.sesiones)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar sesiones activas admin", exc)
            _mostrar_error(self, "No se pudieron cargar las sesiones activas.", exc)

    def cargar_auditoria(self):
        try:
            log_info("hilorama_desktop", "Cargando auditoria admin")
            self.auditoria = _lista(self.api.admin_auditoria(token=_token(self.session)))
            _llenar_tree(self.tree_auditoria, AUDITORIA_COLUMNS, self.auditoria)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar auditoria admin", exc)
            _mostrar_error(self, "No se pudo cargar la auditoria.", exc)

    def crear_cliente(self):
        self._abrir_form_cliente("Crear cliente", None)

    def editar_cliente(self):
        cliente = self._cliente_seleccionado()
        if not cliente:
            messagebox.showwarning("Administracion", "Seleccione un cliente.", parent=self)
            return
        self._abrir_form_cliente("Editar cliente", cliente)

    def _abrir_form_cliente(self, titulo, cliente):
        win = tk.Toplevel(self)
        win.title(titulo)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        variables = {}
        for row, (campo, etiqueta) in enumerate(FORM_FIELDS):
            ttk.Label(frame, text=etiqueta).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=_valor(cliente or {}, campo))
            variables[campo] = var
            ttk.Entry(frame, textvariable=var, width=42).grid(row=row, column=1, sticky="ew", pady=4)

        puede_actualizar = tk.BooleanVar(value=bool((cliente or {}).get("puede_actualizar")))
        ttk.Checkbutton(
            frame,
            text="Puede actualizar",
            variable=puede_actualizar,
        ).grid(row=len(FORM_FIELDS), column=1, sticky="w", pady=(4, 10))

        acciones = ttk.Frame(frame)
        acciones.grid(row=len(FORM_FIELDS) + 1, column=0, columnspan=2, sticky="e")

        def guardar():
            data = _payload_cliente(variables, puede_actualizar)
            if not data.get("nombre_negocio"):
                messagebox.showwarning("Administracion", "El negocio es obligatorio.", parent=win)
                return
            try:
                if cliente:
                    log_info("hilorama_desktop", f"Actualizando cliente admin id={cliente.get('id')}")
                    self.api.admin_actualizar_cliente(cliente["id"], data, token=_token(self.session))
                    mensaje = "Cliente actualizado."
                else:
                    log_info("hilorama_desktop", "Creando cliente admin")
                    self.api.admin_crear_cliente(data, token=_token(self.session))
                    mensaje = "Cliente creado."
                messagebox.showinfo("Administracion", mensaje, parent=win)
                win.destroy()
                self.cargar_clientes()
            except Exception as exc:
                accion = "editar cliente" if cliente else "crear cliente"
                log_error("hilorama_desktop", f"Error al {accion}", exc)
                _mostrar_error(win, f"No se pudo {accion}.", exc)

        ttk.Button(acciones, text="Cancelar", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(acciones, text="Guardar", command=guardar).pack(side="right")

    def _accion_estado(self, accion):
        cliente = self._cliente_seleccionado()
        if not cliente:
            messagebox.showwarning("Administracion", "Seleccione un cliente.", parent=self)
            return

        cliente_id = cliente.get("id")
        nombre = cliente.get("nombre_negocio") or cliente.get("contacto") or cliente_id
        if not messagebox.askyesno(
            "Administracion",
            f"Desea {accion} el cliente {nombre}?",
            parent=self,
        ):
            return

        try:
            log_info("hilorama_desktop", f"Accion admin {accion} cliente id={cliente_id}")
            if accion == "suspender":
                self.api.admin_suspender_cliente(cliente_id, token=_token(self.session))
            elif accion == "bloquear":
                self.api.admin_bloquear_cliente(cliente_id, token=_token(self.session))
            elif accion == "reactivar":
                self.api.admin_reactivar_cliente(cliente_id, token=_token(self.session))
            messagebox.showinfo("Administracion", "Accion aplicada.", parent=self)
            self.cargar_clientes()
            self.cargar_sesiones()
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al {accion} cliente", exc)
            _mostrar_error(self, f"No se pudo {accion} el cliente.", exc)

    def _cliente_seleccionado(self):
        tree = _tree_from_container(self.tree_clientes)
        sel = tree.focus()
        if not sel:
            return None
        idx = int(sel)
        if idx < 0 or idx >= len(self.clientes):
            return None
        return self.clientes[idx]


def _payload_cliente(variables, puede_actualizar):
    data = {}
    for campo, var in variables.items():
        value = var.get().strip()
        if campo == "max_dispositivos":
            if value:
                try:
                    data[campo] = int(value)
                except ValueError:
                    data[campo] = value
            continue
        if value:
            data[campo] = value
        else:
            data[campo] = None
    data["puede_actualizar"] = bool(puede_actualizar.get())
    return data


def _crear_tree(parent, columns):
    contenedor = ttk.Frame(parent)
    contenedor.columnconfigure(0, weight=1)
    contenedor.rowconfigure(0, weight=1)

    tree = ttk.Treeview(
        contenedor,
        columns=[col[0] for col in columns],
        show="headings",
        height=14,
    )
    scroll_y = ttk.Scrollbar(contenedor, orient="vertical", command=tree.yview)
    scroll_x = ttk.Scrollbar(contenedor, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w")

    tree.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    return contenedor


def _llenar_tree(tree_container, columns, rows):
    tree = _tree_from_container(tree_container)
    tree.delete(*tree.get_children())
    for idx, row in enumerate(rows):
        values = [_valor(row, key) for key, _heading, _width in columns]
        tree.insert("", "end", iid=str(idx), values=values)


def _tree_from_container(container):
    for child in container.winfo_children():
        if isinstance(child, ttk.Treeview):
            return child
    raise RuntimeError("Tabla no encontrada")


def _mostrar_error(parent, mensaje, exc):
    detalle = str(exc)
    if isinstance(exc, RenderApiError) and exc.status:
        detalle = f"{detalle} ({exc.status})"
    messagebox.showerror("Administracion", f"{mensaje}\n\n{detalle}", parent=parent)


def _crear_no_autorizado(parent):
    frame = ttk.Frame(parent, padding=32)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    box = ttk.Frame(frame, padding=28)
    box.grid(row=0, column=0)
    ttk.Label(box, text="Administracion", font=("Segoe UI", 22, "bold")).pack(pady=(0, 12))
    ttk.Label(box, text="No autorizado.", font=("Segoe UI", 12)).pack()
    return frame
