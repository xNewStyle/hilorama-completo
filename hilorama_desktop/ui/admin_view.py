import threading
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from ..api_client.render_api_client import RenderApiClient, RenderApiError
    from ..services.auditoria_api_service import AuditoriaApiService
    from ..services.read_api_support import ApiReadError, PermissionDeniedError, RecordNotFoundError, SessionExpiredError
    from ..utils.logger import log_error, log_info
    from ..utils.presentation import EMPTY_VALUE, format_datetime_mexico, optional_text, safe_pretty_json
except ImportError:
    from api_client.render_api_client import RenderApiClient, RenderApiError
    from services.auditoria_api_service import AuditoriaApiService
    from services.read_api_support import ApiReadError, PermissionDeniedError, RecordNotFoundError, SessionExpiredError
    from utils.logger import log_error, log_info
    from utils.presentation import EMPTY_VALUE, format_datetime_mexico, optional_text, safe_pretty_json


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
    ("fecha_creacion", "Fecha", 180),
    ("modulo", "Modulo", 125),
    ("accion", "Accion", 185),
    ("resultado", "Resultado", 100),
    ("usuario", "Usuario", 140),
    ("entidad", "Entidad", 150),
    ("cliente", "Cliente", 185),
    ("descripcion", "Descripcion", 300),
)

USUARIO_COLUMNS = (
    ("id", "ID", 70),
    ("nombre", "Nombre", 180),
    ("usuario", "Usuario", 160),
    ("rol", "Rol", 130),
    ("activo", "Activo", 90),
    ("ultimo_login", "Ultimo login", 170),
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

ROLES_USUARIO_CLIENTE = (
    "admin_cliente",
    "vendedor",
    "almacen",
    "solo_lectura",
)


def crear_vista_admin(parent, auth_service=None, session=None):
    if not _es_super_admin(session):
        log_info("hilorama_desktop", "Intento de abrir Administracion sin rol super_admin")
        return _crear_no_autorizado(parent)

    api = getattr(auth_service, "api", None) or RenderApiClient()
    return AdminView(parent, api, session, auth_service=auth_service)


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
        for key in ("data", "items", "clientes", "usuarios", "sesiones", "auditoria"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _valor(row, key):
    value = row.get(key, "") if isinstance(row, dict) else ""
    if key in {"fecha_creacion", "created_at", "updated_at", "ultimo_login", "ultimo_heartbeat"}:
        return format_datetime_mexico(value)
    return optional_text(value, default="")


class AdminView(ttk.Frame):
    def __init__(self, parent, api, session, auth_service=None):
        super().__init__(parent, padding=10)
        self.api = api
        self.session = session or {}
        self.auth_service = auth_service
        self.auditoria_service = AuditoriaApiService(api_client=api, session_provider=lambda: self.session)
        self.clientes = []
        self.usuarios_cliente = []
        self.sesiones = []
        self.auditoria = []
        self.auditoria_pagination = {"page": 1, "per_page": 50, "total": 0, "pages": 0}
        self._auditoria_loading = False

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
        tab.rowconfigure(2, weight=1)
        self.tabs.add(tab, text="Clientes")

        self.tree_clientes = _crear_tree(tab, CLIENTE_COLUMNS)
        self.tree_clientes.grid(row=0, column=0, sticky="nsew")
        _tree_from_container(self.tree_clientes).bind("<<TreeviewSelect>>", self._al_seleccionar_cliente)

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

        usuarios_box = ttk.LabelFrame(tab, text="Usuarios de acceso", padding=8)
        usuarios_box.columnconfigure(0, weight=1)
        usuarios_box.rowconfigure(0, weight=1)
        usuarios_box.grid(row=2, column=0, sticky="nsew", pady=(12, 0))

        self.tree_usuarios = _crear_tree(usuarios_box, USUARIO_COLUMNS)
        self.tree_usuarios.grid(row=0, column=0, sticky="nsew")

        acciones_usuarios = ttk.Frame(usuarios_box)
        acciones_usuarios.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        botones_usuarios = [
            ("Actualizar usuarios", self.cargar_usuarios_cliente),
            ("Crear usuario", self.crear_usuario_cliente),
            ("Restablecer contrasena", self.reset_password_usuario),
            ("Activar/desactivar", self.toggle_usuario_activo),
        ]
        for texto, comando in botones_usuarios:
            ttk.Button(acciones_usuarios, text=texto, command=comando).pack(side="left", padx=(0, 6))

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
        tab.rowconfigure(1, weight=1)
        self.tabs.add(tab, text="Auditoria")

        filtros = ttk.LabelFrame(tab, text="Filtros", padding=8)
        filtros.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.auditoria_vars = {
            "texto": tk.StringVar(),
            "modulo": tk.StringVar(),
            "accion": tk.StringVar(),
            "resultado": tk.StringVar(),
            "usuario": tk.StringVar(),
            "cliente": tk.StringVar(),
            "entidad": tk.StringVar(),
            "desde": tk.StringVar(),
            "hasta": tk.StringVar(),
        }
        campos = (
            ("Texto", "texto", 0, 0),
            ("Modulo", "modulo", 0, 2),
            ("Accion", "accion", 0, 4),
            ("Resultado", "resultado", 0, 6),
            ("Usuario", "usuario", 1, 0),
            ("Cliente", "cliente", 1, 2),
            ("Entidad", "entidad", 1, 4),
            ("Desde AAAA-MM-DD", "desde", 1, 6),
            ("Hasta AAAA-MM-DD", "hasta", 2, 0),
        )
        for label, key, row, column in campos:
            ttk.Label(filtros, text=label).grid(row=row, column=column, sticky="w", padx=(0, 3), pady=3)
            entry = ttk.Entry(filtros, textvariable=self.auditoria_vars[key], width=18)
            entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=3)
            if key in {"texto", "hasta"}:
                entry.bind("<Return>", lambda _event: self.cargar_auditoria(reset=True), add="+")

        self.tree_auditoria = _crear_tree(tab, AUDITORIA_COLUMNS)
        self.tree_auditoria.grid(row=1, column=0, sticky="nsew")
        _tree_from_container(self.tree_auditoria).bind("<Double-1>", self.ver_detalle_auditoria)

        acciones = ttk.Frame(tab)
        acciones.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.auditoria_status = tk.StringVar(value="")
        ttk.Label(acciones, textvariable=self.auditoria_status).pack(side="left")
        self.auditoria_buttons = [
            ttk.Button(acciones, text="Actualizar", command=lambda: self.cargar_auditoria(reset=True)),
            ttk.Button(acciones, text="Limpiar filtros", command=self.limpiar_filtros_auditoria),
            ttk.Button(acciones, text="Anterior", command=lambda: self.cambiar_pagina_auditoria(-1)),
            ttk.Button(acciones, text="Siguiente", command=lambda: self.cambiar_pagina_auditoria(1)),
            ttk.Button(acciones, text="Ver detalle", command=self.ver_detalle_auditoria),
        ]
        for button in self.auditoria_buttons:
            button.pack(side="right", padx=(6, 0))

    def cargar_clientes(self):
        try:
            log_info("hilorama_desktop", "Cargando clientes admin")
            self.clientes = _lista(self.api.admin_listar_clientes(token=_token(self.session)))
            _llenar_tree(self.tree_clientes, CLIENTE_COLUMNS, self.clientes)
            self.usuarios_cliente = []
            _llenar_tree(self.tree_usuarios, USUARIO_COLUMNS, self.usuarios_cliente)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar clientes admin", exc)
            _mostrar_error(self, "No se pudieron cargar los clientes.", exc)

    def _al_seleccionar_cliente(self, _event=None):
        self.cargar_usuarios_cliente()

    def cargar_usuarios_cliente(self):
        cliente = self._cliente_seleccionado()
        if not cliente:
            self.usuarios_cliente = []
            _llenar_tree(self.tree_usuarios, USUARIO_COLUMNS, self.usuarios_cliente)
            return
        cliente_id = cliente.get("id")
        try:
            log_info("hilorama_desktop", f"Cargando usuarios admin cliente id={cliente_id}")
            self.usuarios_cliente = _lista(
                self.api.admin_listar_usuarios_cliente(cliente_id, token=_token(self.session))
            )
            _llenar_tree(self.tree_usuarios, USUARIO_COLUMNS, self.usuarios_cliente)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar usuarios de cliente", exc)
            _mostrar_error(self, "No se pudieron cargar los usuarios de acceso.", exc)

    def cargar_sesiones(self):
        try:
            log_info("hilorama_desktop", "Cargando sesiones activas admin")
            self.sesiones = _lista(self.api.admin_sesiones_activas(token=_token(self.session)))
            _llenar_tree(self.tree_sesiones, SESION_COLUMNS, self.sesiones)
        except Exception as exc:
            log_error("hilorama_desktop", "Error al cargar sesiones activas admin", exc)
            _mostrar_error(self, "No se pudieron cargar las sesiones activas.", exc)

    def cargar_auditoria(self, reset=True):
        if self._auditoria_loading or not self.winfo_exists():
            return
        if reset:
            self.auditoria_pagination.update({"page": 1, "per_page": 50})
        filtros = {
            key: variable.get().strip()
            for key, variable in self.auditoria_vars.items()
            if variable.get().strip()
        }
        filtros.update({
            "page": self.auditoria_pagination.get("page", 1),
            "per_page": self.auditoria_pagination.get("per_page", 50),
        })
        self._auditoria_loading = True
        self._set_auditoria_loading(True)

        def worker():
            try:
                result = self.auditoria_service.listar_auditoria(filtros)
            except Exception as exc:
                self._safe_after(lambda error=exc: self._finalizar_error_auditoria(error))
                return
            self._safe_after(lambda: self._finalizar_carga_auditoria(result))

        threading.Thread(target=worker, name="auditoria-general", daemon=True).start()

    def limpiar_filtros_auditoria(self):
        for variable in self.auditoria_vars.values():
            variable.set("")
        self.cargar_auditoria(reset=True)

    def cambiar_pagina_auditoria(self, delta):
        current = int(self.auditoria_pagination.get("page") or 1)
        pages = int(self.auditoria_pagination.get("pages") or 0)
        target = max(1, min(pages or 1, current + delta))
        if target != current:
            self.auditoria_pagination["page"] = target
            self.cargar_auditoria(reset=False)

    def ver_detalle_auditoria(self, _event=None):
        tree = _tree_from_container(self.tree_auditoria)
        selected = tree.focus()
        if not selected:
            messagebox.showwarning("Auditoria", "Seleccione un registro de auditoria.", parent=self)
            return
        try:
            row = dict(self.auditoria[int(selected)])
            auditoria_id = row["id"]
        except (IndexError, TypeError, ValueError, KeyError):
            messagebox.showwarning("Auditoria", "No se pudo identificar el registro.", parent=self)
            return

        window = tk.Toplevel(self)
        window.title("Detalle de auditoria")
        window.geometry("860x660")
        window.minsize(650, 460)
        window.transient(self.winfo_toplevel())
        text = tk.Text(window, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        text.pack(fill="both", expand=True)
        _render_auditoria_detail(text, row)

        def worker():
            try:
                detail = self.auditoria_service.obtener_auditoria(auditoria_id)
            except Exception as exc:
                self._safe_after(lambda error=exc: _mostrar_error_lectura(window, error))
                return
            self._safe_after(lambda: _render_auditoria_detail(text, detail))

        threading.Thread(target=worker, name="detalle-auditoria", daemon=True).start()

    def _finalizar_carga_auditoria(self, response):
        if not self.winfo_exists():
            return
        self._auditoria_loading = False
        self._set_auditoria_loading(False)
        self.auditoria = [dict(row or {}) for row in response.get("items") or response.get("auditoria") or []]
        self.auditoria_pagination = dict(response.get("pagination") or self.auditoria_pagination)
        for row in self.auditoria:
            row["entidad"] = " / ".join(
                value for value in (optional_text(row.get("entidad_tipo"), ""), optional_text(row.get("entidad_id"), "")) if value
            )
            row["cliente"] = optional_text(row.get("nombre_negocio") or row.get("cliente_sistema_id"), default="")
        _llenar_tree(self.tree_auditoria, AUDITORIA_COLUMNS, self.auditoria)
        total = int(self.auditoria_pagination.get("total") or 0)
        page = int(self.auditoria_pagination.get("page") or 1)
        pages = int(self.auditoria_pagination.get("pages") or 0)
        self.auditoria_status.set(
            "No hay registros de auditoria." if not self.auditoria else f"Pagina {page} de {pages or 1} | {total} registros"
        )
        self._actualizar_botones_auditoria()

    def _finalizar_error_auditoria(self, exc):
        if not self.winfo_exists():
            return
        self._auditoria_loading = False
        self._set_auditoria_loading(False)
        self.auditoria_status.set("No se pudo cargar la auditoria.")
        _mostrar_error_lectura(self, exc)

    def _set_auditoria_loading(self, loading):
        if not self.winfo_exists():
            return
        state = "disabled" if loading else "normal"
        for button in self.auditoria_buttons:
            button.configure(state=state)
        if loading:
            self.auditoria_status.set("Cargando auditoria...")

    def _actualizar_botones_auditoria(self):
        if self._auditoria_loading:
            return
        page = int(self.auditoria_pagination.get("page") or 1)
        pages = int(self.auditoria_pagination.get("pages") or 0)
        self.auditoria_buttons[2].configure(state="normal" if page > 1 else "disabled")
        self.auditoria_buttons[3].configure(state="normal" if pages and page < pages else "disabled")
        self.auditoria_buttons[4].configure(state="normal" if self.auditoria else "disabled")

    def _safe_after(self, callback):
        try:
            if self.winfo_exists():
                self.after(0, lambda: callback() if self.winfo_exists() else None)
        except tk.TclError:
            pass

    def crear_cliente(self):
        self._abrir_form_cliente("Crear cliente", None)

    def editar_cliente(self):
        cliente = self._cliente_seleccionado()
        if not cliente:
            messagebox.showwarning("Administracion", "Seleccione un cliente.", parent=self)
            return
        self._abrir_form_cliente("Editar cliente", cliente)

    def crear_usuario_cliente(self):
        cliente = self._cliente_seleccionado()
        if not cliente:
            messagebox.showwarning("Administracion", "Seleccione un cliente.", parent=self)
            return
        self._abrir_form_usuario(cliente)

    def reset_password_usuario(self):
        usuario = self._usuario_seleccionado()
        if not usuario:
            messagebox.showwarning("Administracion", "Seleccione un usuario.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title("Restablecer contrasena")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=f"Usuario: {_valor(usuario, 'usuario')}").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        password = tk.StringVar()
        confirmar = tk.StringVar()
        ttk.Label(frame, text="Nueva contrasena temporal").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=password, show="*", width=36).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Confirmar contrasena").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=confirmar, show="*", width=36).grid(row=2, column=1, sticky="ew", pady=4)

        acciones = ttk.Frame(frame)
        acciones.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def guardar():
            nueva = password.get()
            if nueva != confirmar.get():
                messagebox.showwarning("Administracion", "Las contrasenas no coinciden.", parent=win)
                return
            if len(nueva) < 6:
                messagebox.showwarning("Administracion", "La contrasena debe tener al menos 6 caracteres.", parent=win)
                return
            if not messagebox.askyesno(
                "Administracion",
                "Desea restablecer la contrasena de este usuario?",
                parent=win,
            ):
                return
            try:
                self.api.admin_reset_password_usuario(
                    usuario["id"],
                    {"nueva_password_temporal": nueva},
                    token=_token(self.session),
                )
                messagebox.showinfo(
                    "Administracion",
                    "Contrasena restablecida. Entregue la nueva contrasena temporal al cliente.",
                    parent=win,
                )
                win.destroy()
                self.cargar_usuarios_cliente()
            except Exception as exc:
                log_error("hilorama_desktop", "Error al restablecer contrasena de usuario", exc)
                _mostrar_error(win, "No se pudo restablecer la contrasena.", exc)

        ttk.Button(acciones, text="Cancelar", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(acciones, text="Restablecer", command=guardar).pack(side="right")

    def toggle_usuario_activo(self):
        usuario = self._usuario_seleccionado()
        if not usuario:
            messagebox.showwarning("Administracion", "Seleccione un usuario.", parent=self)
            return
        activo = _bool_row(usuario.get("activo"))
        accion = "desactivar" if activo else "activar"
        if not messagebox.askyesno(
            "Administracion",
            f"Desea {accion} el usuario {_valor(usuario, 'usuario')}?",
            parent=self,
        ):
            return
        try:
            if activo:
                self.api.admin_desactivar_usuario(usuario["id"], token=_token(self.session))
            else:
                self.api.admin_activar_usuario(usuario["id"], token=_token(self.session))
            messagebox.showinfo("Administracion", "Accion aplicada.", parent=self)
            self.cargar_usuarios_cliente()
            self.cargar_sesiones()
        except Exception as exc:
            log_error("hilorama_desktop", f"Error al {accion} usuario", exc)
            _mostrar_error(self, f"No se pudo {accion} el usuario.", exc)

    def _abrir_form_usuario(self, cliente):
        win = tk.Toplevel(self)
        win.title("Crear usuario")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"Cliente: {_valor(cliente, 'nombre_negocio') or _valor(cliente, 'contacto')}",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        nombre = tk.StringVar()
        username = tk.StringVar()
        password = tk.StringVar()
        confirmar = tk.StringVar()
        rol = tk.StringVar(value="vendedor")
        activo = tk.BooleanVar(value=True)

        campos = [
            ("Nombre", nombre, False),
            ("Usuario", username, False),
            ("Contrasena temporal", password, True),
            ("Confirmar contrasena", confirmar, True),
        ]
        for idx, (etiqueta, variable, oculto) in enumerate(campos, start=1):
            ttk.Label(frame, text=etiqueta).grid(row=idx, column=0, sticky="w", pady=4)
            ttk.Entry(
                frame,
                textvariable=variable,
                show="*" if oculto else "",
                width=38,
            ).grid(row=idx, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text="Rol").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            frame,
            textvariable=rol,
            values=ROLES_USUARIO_CLIENTE,
            state="readonly",
            width=35,
        ).grid(row=5, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(frame, text="Activo", variable=activo).grid(row=6, column=1, sticky="w", pady=(4, 10))

        acciones = ttk.Frame(frame)
        acciones.grid(row=7, column=0, columnspan=2, sticky="e")

        def guardar():
            if not nombre.get().strip() or not username.get().strip():
                messagebox.showwarning("Administracion", "Nombre y usuario son obligatorios.", parent=win)
                return
            if password.get() != confirmar.get():
                messagebox.showwarning("Administracion", "Las contrasenas no coinciden.", parent=win)
                return
            if len(password.get()) < 6:
                messagebox.showwarning("Administracion", "La contrasena debe tener al menos 6 caracteres.", parent=win)
                return

            data = {
                "nombre": nombre.get().strip(),
                "username": username.get().strip(),
                "password_temporal": password.get(),
                "rol": rol.get(),
                "activo": bool(activo.get()),
            }
            try:
                self.api.admin_crear_usuario_cliente(cliente["id"], data, token=_token(self.session))
                messagebox.showinfo(
                    "Administracion",
                    "Usuario creado correctamente.\nEntregue estas credenciales al cliente.",
                    parent=win,
                )
                win.destroy()
                self.cargar_usuarios_cliente()
            except Exception as exc:
                log_error("hilorama_desktop", "Error al crear usuario de cliente", exc)
                _mostrar_error(win, "No se pudo crear el usuario.", exc)

        ttk.Button(acciones, text="Cancelar", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(acciones, text="Crear usuario", command=guardar).pack(side="right")

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

    def _usuario_seleccionado(self):
        tree = _tree_from_container(self.tree_usuarios)
        sel = tree.focus()
        if not sel:
            return None
        idx = int(sel)
        if idx < 0 or idx >= len(self.usuarios_cliente):
            return None
        return self.usuarios_cliente[idx]


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


def _bool_row(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "t", "si", "sí", "yes", "activo"}


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


def _render_auditoria_detail(text_widget, row):
    try:
        if not text_widget.winfo_exists():
            return
    except tk.TclError:
        return
    data = dict(row or {})
    entidad = " / ".join(
        value for value in (optional_text(data.get("entidad_tipo"), ""), optional_text(data.get("entidad_id"), "")) if value
    ) or EMPTY_VALUE
    cliente = data.get("nombre_negocio") or data.get("cliente_sistema_id")
    lines = (
        f"ID: {optional_text(data.get('id'))}",
        f"Fecha: {format_datetime_mexico(data.get('fecha_creacion'))}",
        f"Modulo: {optional_text(data.get('modulo'))}",
        f"Accion: {optional_text(data.get('accion'))}",
        f"Resultado: {optional_text(data.get('resultado'))}",
        f"Usuario: {optional_text(data.get('usuario') or data.get('usuario_nombre'))}",
        f"Cliente: {optional_text(cliente)}",
        f"Entidad: {entidad}",
        f"Descripcion: {optional_text(data.get('descripcion'))}",
        f"Request ID: {optional_text(data.get('request_id'))}",
        f"IP: {optional_text(data.get('ip'))}",
        f"Dispositivo: {optional_text(data.get('device_id'))}",
        f"User agent: {optional_text(data.get('user_agent'))}",
        f"Codigo de error: {optional_text(data.get('codigo_error'))}",
        "",
        "Datos anteriores redactados:",
        safe_pretty_json(data.get("datos_anteriores_json")),
        "",
        "Datos nuevos redactados:",
        safe_pretty_json(data.get("datos_nuevos_json")),
    )
    text_widget.configure(state="normal")
    text_widget.delete("1.0", tk.END)
    text_widget.insert("1.0", "\n".join(lines))
    text_widget.configure(state="disabled")


def _mostrar_error_lectura(parent, exc):
    try:
        if hasattr(parent, "winfo_exists") and not parent.winfo_exists():
            return
    except tk.TclError:
        return
    if isinstance(exc, SessionExpiredError):
        current = parent
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            handler = getattr(current, "manejar_sesion_expirada", None)
            if callable(handler):
                handler(str(exc))
                return
            current = getattr(current, "master", None)
    if isinstance(exc, PermissionDeniedError):
        messagebox.showwarning("Administracion", str(exc), parent=parent)
        return
    if isinstance(exc, RecordNotFoundError):
        messagebox.showinfo("Administracion", str(exc), parent=parent)
        return
    if isinstance(exc, ApiReadError):
        messagebox.showerror("Administracion", str(exc), parent=parent)
        return
    log_error("hilorama_desktop", "Error inesperado de lectura en Administracion", exc)
    messagebox.showerror("Administracion", "No se pudo completar la consulta.", parent=parent)


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
