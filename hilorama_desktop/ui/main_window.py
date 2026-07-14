import tkinter as tk
import queue
import time
import threading
from tkinter import messagebox, ttk

try:
    from tkinterdnd2 import TkinterDnD
    BaseTk = TkinterDnD.Tk
except Exception:
    BaseTk = tk.Tk

try:
    from ..config import APP_NAME, APP_VERSION
    from ..services.heartbeat_service import HeartbeatService
    from ..utils.logger import log_error, log_info
    from .admin_view import crear_vista_admin
    from .almacen_view import crear_vista_almacen
    from .notificaciones_view import NotificationBellController
    from .ventas_view import crear_vista_ventas
except ImportError:  # Permite compilar/ejecutar main.py como script.
    from config import APP_NAME, APP_VERSION
    from services.heartbeat_service import HeartbeatService
    from utils.logger import log_error, log_info
    from ui.admin_view import crear_vista_admin
    from ui.almacen_view import crear_vista_almacen
    from ui.notificaciones_view import NotificationBellController
    from ui.ventas_view import crear_vista_ventas


class HiloramaDesktopApp(BaseTk):
    def __init__(self, auth_service=None, session=None):
        super().__init__()
        self.auth_service = auth_service
        self.session = session
        self.heartbeat = None
        self._session_expiration_in_progress = False
        self.views_cache = {}
        self.current_view = None
        self.current_module = None
        self.notification_controller = None
        self._startup_at = time.perf_counter()
        self.report_callback_exception = self._manejar_error_tkinter

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.configure(bg="#F4F5F7")
        self._configurar_tamano_inicial()

        self._build_shell()
        self.mostrar_inicio()
        if self.notification_controller:
            self.notification_controller.start()
        self._iniciar_heartbeat()
        self._log_tiempo("arranque Desktop", self._startup_at)
        self.after(1500, self._iniciar_revision_actualizaciones)
        self.protocol("WM_DELETE_WINDOW", self._cerrar_aplicacion)

    def _configurar_tamano_inicial(self):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        ancho = max(1024, min(1500, screen_width - 40))
        alto = max(700, min(900, screen_height - 80))
        x = max(0, (screen_width - ancho) // 2)
        y = max(0, (screen_height - alto) // 2)

        self.geometry(f"{ancho}x{alto}+{x}+{y}")
        self.minsize(min(1280, ancho), min(720, alto))
        try:
            self.state("zoomed")
        except tk.TclError:
            log_info("hilorama_desktop", "state('zoomed') no disponible, intentando fallback")
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                log_info("hilorama_desktop", "attributes('-zoomed') no disponible")
                pass

    def _build_shell(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg="#202938", width=180)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        title = tk.Label(
            sidebar,
            text="Hilorama\nDesktop",
            bg="#202938",
            fg="white",
            font=("Segoe UI", 16, "bold"),
            justify="left",
        )
        title.pack(fill="x", padx=14, pady=(22, 16))

        botones = [
            ("Almacen", self.mostrar_almacen),
            ("Ventas", self.mostrar_ventas),
            ("Clientes", self.mostrar_clientes),
            ("Reportes", lambda: self.mostrar_pendiente("Reportes")),
            ("Configuracion", lambda: self.mostrar_pendiente("Configuracion")),
        ]
        if self._es_super_admin():
            botones.append(("Administracion", self.mostrar_admin))

        for texto, comando in botones:
            btn = tk.Button(
                sidebar,
                text=texto,
                command=comando,
                anchor="w",
                bg="#2F3A4B",
                fg="white",
                activebackground="#3B4A60",
                activeforeground="white",
                relief="flat",
                font=("Segoe UI", 12),
                padx=14,
                pady=10,
            )
            btn.pack(fill="x", padx=10, pady=5)

        tk.Frame(sidebar, bg="#202938").pack(fill="both", expand=True)
        btn_logout = tk.Button(
            sidebar,
            text="Cerrar sesion",
            command=self.cerrar_sesion,
            anchor="w",
            bg="#5B2630",
            fg="white",
            activebackground="#71313D",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 12),
            padx=14,
            pady=10,
        )
        btn_logout.pack(fill="x", padx=10, pady=(8, 16))

        workspace = tk.Frame(self, bg="#F4F5F7")
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(1, weight=1)

        topbar = tk.Frame(workspace, bg="white", height=56, bd=0, highlightthickness=1, highlightbackground="#E2E8F0")
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.columnconfigure(0, weight=1)
        self.module_title_var = tk.StringVar(value="Inicio")
        tk.Label(
            topbar,
            textvariable=self.module_title_var,
            bg="white",
            fg="#1F2937",
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="nsew", padx=(18, 10))
        topbar_actions = tk.Frame(topbar, bg="white")
        topbar_actions.grid(row=0, column=1, sticky="e", padx=(4, 12), pady=5)
        self.notification_controller = NotificationBellController(
            self,
            topbar_actions,
            self._navegar_notificacion,
        )
        self.notification_controller.bell.pack(side="right")

        self.content = ttk.Frame(workspace, padding=2)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

    def _limpiar_content(self):
        for child in self.content.winfo_children():
            child.destroy()
        self.views_cache.clear()
        self.current_view = None
        self.current_module = None

    def _set_view(self, view):
        if self.current_view is not None:
            try:
                if self.current_view.winfo_exists():
                    self.current_view.grid_remove()
            except tk.TclError as exc:
                log_error("hilorama_desktop", "Error al ocultar la vista actual", exc)
                pass
        view.grid(row=0, column=0, sticky="nsew")
        self.current_view = view

    def mostrar_inicio(self):
        self._mostrar_modulo(
            "inicio",
            lambda parent: _crear_placeholder(parent, "Inicio", "Seleccione un modulo del menu principal."),
        )

    def mostrar_almacen(self):
        self._mostrar_modulo("almacen", crear_vista_almacen)

    def mostrar_ventas(self):
        self._mostrar_modulo("ventas", crear_vista_ventas)

    def mostrar_clientes(self):
        """Monta siempre el CRM comercial embebido del cliente Desktop."""
        self._mostrar_modulo("clientes", self._crear_vista_clientes_api)

    def _crear_vista_clientes_api(self, parent):
        """Import diferido: Clientes API no arrastra base local al iniciar Desktop."""
        try:
            from .clientes_crm_view import ClientesCRMView
        except ImportError:
            from ui.clientes_crm_view import ClientesCRMView
        return ClientesCRMView(parent, editar_cliente_callback=self._editar_cliente_desde_crm)

    @staticmethod
    def _editar_cliente_desde_crm(cliente_id, parent, on_guardar=None):
        # El editor existente ya usa clientes.py, que consulta API en este modo.
        from ver_clientes import editar_cliente_por_id
        return editar_cliente_por_id(cliente_id, parent, on_guardar=on_guardar)

    def mostrar_admin(self):
        self._mostrar_modulo(
            "administracion",
            lambda parent: crear_vista_admin(parent, self.auth_service, self.session),
        )

    def mostrar_pendiente(self, modulo):
        nombre = modulo.lower()
        self._mostrar_modulo(
            nombre,
            lambda parent: _crear_placeholder(parent, modulo, "Modulo pendiente de integrar."),
        )

    def _mostrar_modulo(self, nombre, factory):
        log_info("hilorama_desktop", f"Cambiando a modulo: {nombre}")
        self._set_modulo_actual(nombre)

        if nombre in self.views_cache:
            inicio = time.perf_counter()
            self._set_view(self.views_cache[nombre])
            self.current_module = nombre
            self._log_tiempo(f"mostrar {nombre} desde cache", inicio)
            return

        loading = _crear_placeholder(self.content, "Cargando modulo...", "Preparando la vista.")
        self._set_view(loading)
        self.update_idletasks()

        inicio = time.perf_counter()
        try:
            view = factory(self.content)
        except Exception as exc:
            log_error(nombre, f"Error al abrir modulo {nombre}", exc)
            view = _crear_error_modulo(self.content, nombre, exc)

        loading.destroy()
        self.views_cache[nombre] = view
        self._set_view(view)
        self.current_module = nombre
        self._log_tiempo(f"abrir {nombre}", inicio)

    def limpiar_cache_modulo(self, nombre=None):
        if nombre is None:
            nombres = list(self.views_cache)
        else:
            nombres = [nombre]

        for item in nombres:
            view = self.views_cache.pop(item, None)
            if view is not None and view.winfo_exists():
                log_info("hilorama_desktop", f"Limpiando cache de modulo: {item}")
                view.destroy()
            if self.current_module == item:
                self.current_view = None
                self.current_module = None

    def _log_tiempo(self, etiqueta, inicio):
        duracion = time.perf_counter() - inicio
        log_info("hilorama_desktop", f"{etiqueta}: {duracion:.2f}s")

    def _set_modulo_actual(self, modulo):
        titulos = {
            "inicio": "Inicio",
            "almacen": "Almacén",
            "ventas": "Ventas",
            "clientes": "Clientes",
            "reportes": "Reportes",
            "configuracion": "Configuración",
            "administracion": "Administración",
        }
        if hasattr(self, "module_title_var"):
            self.module_title_var.set(titulos.get(modulo, str(modulo or "").title()))
        if self.heartbeat:
            self.heartbeat.set_module(modulo)

    def _navegar_notificacion(self, aviso, accion):
        accion = str(accion or "").strip().upper()
        if accion in {"ABRIR_CLIENTE", "VER_PRODUCTOS_FRECUENTES", "VER_HISTORIAL_CLIENTE"}:
            self._abrir_cliente_notificacion(
                aviso.get("cliente_id") or aviso.get("destino_id"),
                abrir_historial=accion == "VER_HISTORIAL_CLIENTE",
            )
            return
        if accion in {"ABRIR_PRODUCTO", "ABRIR_ALMACEN"}:
            self._abrir_producto_notificacion(aviso)
            return
        if accion == "ABRIR_ENVIOS":
            self._abrir_panel_ventas_notificacion("abrir_panel_envios")
            return
        if accion in {"ABRIR_ASIGNACION", "ABRIR_PEDIDO"}:
            self._abrir_panel_ventas_notificacion("abrir_panel_asignacion")
            return
        if accion == "ABRIR_REPORTE_ESCANEO":
            self._abrir_panel_ventas_notificacion("abrir_panel_errores")
            return
        if accion == "ABRIR_IMPRESION":
            self._abrir_venta_notificacion(aviso.get("nota_id"), imprimir=True)
            return
        if accion == "ABRIR_VENTA":
            self._abrir_venta_notificacion(aviso.get("nota_id") or aviso.get("destino_id"))
            return
        log_info("hilorama_desktop", f"Accion de notificacion sin navegador: {accion or 'vacia'}")

    def _abrir_cliente_notificacion(self, cliente_id, abrir_historial=False):
        if cliente_id in (None, ""):
            return
        self.mostrar_clientes()

        def seleccionar():
            view = self.views_cache.get("clientes")
            if view is not None and hasattr(view, "seleccionar_cliente"):
                view.seleccionar_cliente(cliente_id, abrir_historial=abrir_historial)

        self.after(60, seleccionar)

    def _abrir_producto_notificacion(self, aviso):
        self.mostrar_almacen()
        metadata = aviso.get("metadata") if isinstance(aviso.get("metadata"), dict) else {}
        producto_id = aviso.get("producto_id") or aviso.get("destino_id")
        codigo = metadata.get("codigo")

        def enfocar():
            try:
                import almacen_colores
                almacen_colores.enfocar_producto(producto_id=producto_id, codigo=codigo)
            except Exception as exc:
                log_error("almacen", "No se pudo enfocar el producto de la notificacion", exc)

        self.after(100, enfocar)

    def _abrir_panel_ventas_notificacion(self, nombre_funcion):
        self.mostrar_ventas()

        def abrir():
            try:
                import main_ventas
                funcion = getattr(main_ventas, nombre_funcion)
                funcion()
            except Exception as exc:
                log_error("ventas", f"No se pudo abrir {nombre_funcion} desde la campana", exc)
                messagebox.showerror(
                    "Notificaciones",
                    "No se pudo abrir la pantalla solicitada. Revisa los logs.",
                    parent=self,
                )

        self.after(100, abrir)

    def _abrir_venta_notificacion(self, nota_id, imprimir=False):
        if nota_id in (None, ""):
            return
        self.mostrar_ventas()
        resultados = queue.Queue()

        def worker():
            try:
                from ..services.notas_api_service import obtener_detalle_completo_nota
            except ImportError:
                from services.notas_api_service import obtener_detalle_completo_nota
            try:
                resultados.put((obtener_detalle_completo_nota(nota_id), None))
            except Exception as exc:
                resultados.put((None, exc))

        def procesar():
            try:
                nota, error = resultados.get_nowait()
            except queue.Empty:
                if self.winfo_exists():
                    self.after(50, procesar)
                return
            if error:
                log_error("ventas", f"No se pudo abrir la venta {nota_id} desde la campana", error)
                messagebox.showerror(
                    "Notificaciones",
                    "No se pudo cargar la venta seleccionada.",
                    parent=self,
                )
                return
            try:
                if imprimir:
                    import main_ventas
                    main_ventas.abrir_opciones_impresion(nota)
                else:
                    from ver_cotizaciones import mostrar_detalle_nota
                    mostrar_detalle_nota(nota, self)
            except Exception as exc:
                log_error("ventas", f"No se pudo mostrar la venta {nota_id}", exc)
                messagebox.showerror(
                    "Notificaciones",
                    "No se pudo abrir el detalle solicitado.",
                    parent=self,
                )

        threading.Thread(target=worker, daemon=True, name=f"notificacion-nota-{nota_id}").start()
        self.after(50, procesar)

    def _es_super_admin(self):
        usuario = (self.session or {}).get("usuario") or {}
        permisos = (self.session or {}).get("permisos") or []
        return usuario.get("rol") == "super_admin" or "super_admin" in permisos

    def cerrar_sesion(self):
        confirmar = messagebox.askyesno(
            "Cerrar sesion",
            "Desea cerrar la sesion de Hilorama en esta computadora?",
            parent=self,
        )
        if not confirmar:
            return

        if self.heartbeat:
            self.heartbeat.stop()
            self.heartbeat = None
        if self.notification_controller:
            self.notification_controller.shutdown()

        try:
            if self.auth_service:
                self.auth_service.logout()
            else:
                self._borrar_sesion_local()
            log_info("hilorama_desktop", "Sesion cerrada por el usuario")
        except Exception as exc:
            log_error("hilorama_desktop", "Fallo logout remoto; borrando sesion local", exc)
            try:
                self._borrar_sesion_local()
            except Exception as clear_exc:
                log_error("hilorama_desktop", "No se pudo borrar la sesion local", clear_exc)
                messagebox.showerror(
                    "Cerrar sesion",
                    "No se pudo borrar la sesion local. Revise logs.",
                    parent=self,
                )
                return

        messagebox.showinfo(
            "Cerrar sesion",
            "Sesion cerrada. Abra Hilorama nuevamente para iniciar sesion.",
            parent=self,
        )
        self.destroy()

    def _cerrar_aplicacion(self):
        if self.heartbeat:
            self.heartbeat.stop()
            self.heartbeat = None
        if self.notification_controller:
            self.notification_controller.shutdown()
        self.destroy()

    def manejar_sesion_expirada(self, mensaje="La sesion expiro. Inicia sesion nuevamente."):
        """Cierra la aplicacion de forma controlada cuando una lectura recibe HTTP 401."""
        if self._session_expiration_in_progress:
            return
        self._session_expiration_in_progress = True
        log_info("hilorama_desktop", "Sesion expirada detectada desde una consulta API")
        if self.heartbeat:
            self.heartbeat.stop()
            self.heartbeat = None
        if self.notification_controller:
            self.notification_controller.shutdown()
        try:
            self._borrar_sesion_local()
        except Exception as exc:
            log_error("hilorama_desktop", "No se pudo borrar la sesion expirada local", exc)
        try:
            messagebox.showerror("Sesion expirada", mensaje, parent=self)
        finally:
            if self.winfo_exists():
                self.destroy()

    def _borrar_sesion_local(self):
        store = getattr(self.auth_service, "store", None) if self.auth_service else None
        if store:
            store.clear()
            return

        try:
            from ..security.local_secure_store import LocalSecureStore
        except ImportError:
            from security.local_secure_store import LocalSecureStore
        LocalSecureStore().clear()

    def _iniciar_heartbeat(self):
        if not self.auth_service:
            return
        self.heartbeat = HeartbeatService(
            self,
            self.auth_service,
            modulo_actual="inicio",
            on_blocked=self._bloquear_por_licencia,
        )
        self.heartbeat.start()
        log_info("hilorama_desktop", "Heartbeat iniciado")

    def _bloquear_por_licencia(self, mensaje):
        log_error("hilorama_desktop", f"Acceso bloqueado por licencia: {mensaje}")
        if self.heartbeat:
            self.heartbeat.stop()
        if self.notification_controller:
            self.notification_controller.shutdown()
        messagebox.showerror("Acceso bloqueado", mensaje, parent=self)
        self.destroy()

    def _iniciar_revision_actualizaciones(self):
        thread = threading.Thread(target=self._revisar_actualizaciones_worker, daemon=True)
        thread.start()

    def _revisar_actualizaciones_worker(self):
        try:
            from ..updater.update_checker import check_for_update
        except ImportError:
            from updater.update_checker import check_for_update

        result = check_for_update()
        if result.update_available and result.manifest:
            self.after(0, lambda: self._mostrar_actualizacion_disponible(result))

    def _mostrar_actualizacion_disponible(self, result):
        manifest = result.manifest
        if not manifest:
            return

        win = tk.Toplevel(self)
        win.title("Actualizacion disponible")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Actualizacion disponible",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frame,
            text=(
                "Hay una nueva version de Hilorama Desktop disponible.\n"
                f"Version actual: {result.current_version}\n"
                f"Version nueva: {manifest.latest_version}"
            ),
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        if manifest.mandatory:
            ttk.Label(
                frame,
                text="Esta actualizacion esta marcada como obligatoria.",
                foreground="#8A3A00",
            ).pack(anchor="w", pady=(0, 8))

        if manifest.notes:
            ttk.Label(frame, text="Notas:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            notas = "\n".join(f"- {item}" for item in manifest.notes[:8])
            ttk.Label(frame, text=notas, justify="left", wraplength=460).pack(anchor="w", pady=(2, 10))

        status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status, wraplength=460).pack(anchor="w", pady=(0, 8))

        acciones = ttk.Frame(frame)
        acciones.pack(fill="x", pady=(4, 0))

        btn_despues = ttk.Button(acciones, text="Despues", command=win.destroy)
        btn_despues.pack(side="right", padx=(6, 0))
        btn_actualizar = ttk.Button(
            acciones,
            text="Actualizar ahora",
            command=lambda: self._descargar_actualizacion_async(manifest, win, status, btn_actualizar),
        )
        btn_actualizar.pack(side="right")

    def _descargar_actualizacion_async(self, manifest, win, status, button):
        button.configure(state="disabled")
        status.set("Descargando actualizacion...")

        def worker():
            try:
                from ..updater.update_downloader import download_update
                from ..updater.apply_update import prepare_windows_update
            except ImportError:
                from updater.update_downloader import download_update
                from updater.apply_update import prepare_windows_update

            result = download_update(manifest.download_url, manifest.sha256)
            if not result.ok:
                self.after(0, lambda: self._mostrar_error_descarga(status, button, result.error))
                return

            try:
                prepared = prepare_windows_update(result.file_path, dry_run=True)
            except Exception as exc:
                log_error("hilorama_desktop", "No se pudo preparar aplicacion de actualizacion", exc)
                self.after(0, lambda: self._mostrar_error_descarga(status, button, str(exc)))
                return

            self.after(0, lambda: self._mostrar_actualizacion_preparada(win, prepared))

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_error_descarga(self, status, button, error):
        status.set(f"No se pudo actualizar: {error}")
        button.configure(state="normal")

    def _mostrar_actualizacion_preparada(self, win, prepared):
        messagebox.showinfo(
            "Actualizacion descargada",
            (
                "La actualizacion se descargo y el checksum fue validado.\n\n"
                "En esta fase se preparo el reemplazo en modo seguro/dry-run.\n"
                f"Archivo: {prepared.get('downloaded_file')}"
            ),
            parent=win,
        )
        win.destroy()

    def _manejar_error_tkinter(self, exc_type, exc_value, exc_traceback):
        log_error(
            "errores",
            "Error inesperado en Tkinter",
            (exc_type, exc_value, exc_traceback),
        )
        try:
            messagebox.showerror(
                "Hilorama Desktop",
                "Ocurrió un error. Se guardó el detalle en logs.",
                parent=self,
            )
        except tk.TclError:
            pass


def _crear_placeholder(parent, titulo, mensaje):
    frame = ttk.Frame(parent, padding=32)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    box = ttk.Frame(frame, padding=28)
    box.grid(row=0, column=0)

    ttk.Label(box, text=titulo, font=("Segoe UI", 22, "bold")).pack(pady=(0, 12))
    ttk.Label(box, text=mensaje, font=("Segoe UI", 12)).pack()
    return frame


def _crear_error_modulo(parent, modulo, exc):
    frame = ttk.Frame(parent, padding=32)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    box = ttk.Frame(frame, padding=28)
    box.grid(row=0, column=0)

    ttk.Label(box, text=modulo.title(), font=("Segoe UI", 22, "bold")).pack(pady=(0, 12))
    ttk.Label(box, text="No se pudo abrir este modulo.", font=("Segoe UI", 12)).pack(pady=(0, 8))
    ttk.Label(
        box,
        text=str(exc),
        font=("Segoe UI", 10),
        foreground="#6B7280",
        wraplength=560,
        justify="center",
    ).pack()
    return frame


def run_app(auth_service=None, session=None):
    app = HiloramaDesktopApp(auth_service=auth_service, session=session)
    app.mainloop()
