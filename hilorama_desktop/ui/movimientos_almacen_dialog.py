"""Dialogos de consulta de movimientos de almacen por API."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

try:
    from ..services.movimientos_api_service import MovimientosApiService
    from ..services.read_api_support import ApiReadError, PermissionDeniedError, RecordNotFoundError, SessionExpiredError
    from ..utils.logger import log_error, log_info
    from ..utils.presentation import (
        EMPTY_VALUE,
        format_datetime_mexico,
        format_support_identifier,
        optional_text,
        redact_sensitive_data,
        safe_pretty_json,
    )
except ImportError:
    from services.movimientos_api_service import MovimientosApiService
    from services.read_api_support import ApiReadError, PermissionDeniedError, RecordNotFoundError, SessionExpiredError
    from utils.logger import log_error, log_info
    from utils.presentation import (
        EMPTY_VALUE,
        format_datetime_mexico,
        format_support_identifier,
        optional_text,
        redact_sensitive_data,
        safe_pretty_json,
    )


DEFAULT_PER_PAGE = 50
MOVIMIENTO_COLUMNS = (
    ("fecha", "Fecha", 165),
    ("producto", "Producto/codigo", 135),
    ("tipo", "Tipo", 145),
    ("stock_anterior", "Stock anterior", 105),
    ("cantidad", "Cantidad", 85),
    ("stock_nuevo", "Stock nuevo", 100),
    ("motivo", "Motivo", 260),
    ("referencia", "Referencia", 160),
    ("usuario", "Usuario", 135),
)
FILTER_FIELDS = ("q", "producto", "codigo", "marca", "hilo", "color", "tipo", "usuario", "referencia", "desde", "hasta")
TIPOS_MOVIMIENTO = (
    "",
    "ENTRADA_MANUAL",
    "SALIDA_MANUAL",
    "AJUSTE_POSITIVO",
    "AJUSTE_NEGATIVO",
    "VENTA",
    "CANCELACION_VENTA",
    "DEVOLUCION",
    "STOCK_INICIAL",
    "CORRECCION",
    "OTRO",
)


def build_movimientos_filters(values: dict[str, Any], page: int = 1, per_page: int = DEFAULT_PER_PAGE) -> dict[str, Any]:
    """Construye filtros permitidos sin pasar datos de cliente al backend."""
    params = {
        key: str(values.get(key) or "").strip()
        for key in FILTER_FIELDS
        if str(values.get(key) or "").strip()
    }
    params["page"] = int(page)
    params["per_page"] = int(per_page)
    return params


def widget_is_alive(widget) -> bool:
    try:
        return bool(widget) and bool(widget.winfo_exists())
    except Exception:
        return False


def safe_after(widget, delay_ms: int, callback):
    """Agenda callback solo si la ventana continua viva al ejecutarse."""
    if not widget_is_alive(widget):
        return None

    def run_if_alive():
        if widget_is_alive(widget):
            callback()

    try:
        return widget.after(delay_ms, run_if_alive)
    except Exception:
        return None


def handle_session_expired(widget, message: str) -> bool:
    """Encuentra la ventana Desktop aun cuando el error venga de un Toplevel."""
    current = widget
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        handler = getattr(current, "manejar_sesion_expirada", None)
        if callable(handler):
            handler(message)
            return True
        current = getattr(current, "master", None)
    return False


def abrir_movimientos_almacen(parent, service=None):
    """Abre un unico visor por ventana principal y lo enfoca si ya existe."""
    owner = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent
    existente = getattr(owner, "_hilorama_movimientos_dialog", None)
    if existente and existente.is_open:
        existente.focus()
        return existente
    dialog = MovimientosAlmacenDialog(owner, service=service)
    setattr(owner, "_hilorama_movimientos_dialog", dialog)
    return dialog


class MovimientosAlmacenDialog:
    def __init__(self, parent, service=None):
        self.parent = parent
        self.service = service or MovimientosApiService()
        self.window = tk.Toplevel(parent)
        self.window.title("Movimientos de almacen")
        self.window.geometry("1420x780")
        self.window.minsize(1040, 620)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.page = 1
        self.per_page = DEFAULT_PER_PAGE
        self.pagination = {"page": 1, "per_page": self.per_page, "total": 0, "pages": 0}
        self.rows: list[dict[str, Any]] = []
        self._loading = False
        self._closed = False
        self._detail_windows: dict[str, MovimientoDetalleDialog] = {}
        self.filter_vars = {key: tk.StringVar() for key in FILTER_FIELDS}

        self._build()
        self.load(reset=True)

    @property
    def is_open(self) -> bool:
        return not self._closed and widget_is_alive(self.window)

    def focus(self):
        if self.is_open:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for detail in list(self._detail_windows.values()):
            detail.close()
        self._detail_windows.clear()
        if widget_is_alive(self.window):
            self.window.destroy()

    def _build(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        filtros = ttk.LabelFrame(self.window, text="Filtros", padding=8)
        filtros.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        for column in range(8):
            filtros.columnconfigure(column, weight=1 if column % 2 else 0)

        fields = (
            ("Buscar", "q", 0, 0),
            ("Producto / ID", "producto", 0, 2),
            ("Codigo", "codigo", 0, 4),
            ("Marca", "marca", 0, 6),
            ("Hilo", "hilo", 1, 0),
            ("Color", "color", 1, 2),
            ("Tipo", "tipo", 1, 4),
            ("Usuario", "usuario", 1, 6),
            ("Referencia", "referencia", 2, 0),
            ("Desde AAAA-MM-DD", "desde", 2, 2),
            ("Hasta AAAA-MM-DD", "hasta", 2, 4),
        )
        for label, key, row, column in fields:
            ttk.Label(filtros, text=label).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=3)
            if key == "tipo":
                control = ttk.Combobox(filtros, textvariable=self.filter_vars[key], values=TIPOS_MOVIMIENTO, state="readonly", width=20)
            else:
                control = ttk.Entry(filtros, textvariable=self.filter_vars[key], width=22)
            control.grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=3)
            if key in {"q", "hasta"}:
                control.bind("<Return>", lambda _event: self.load(reset=True), add="+")

        table_frame = ttk.Frame(self.window, padding=(10, 0, 10, 0))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=[key for key, _label, _width in MOVIMIENTO_COLUMNS], show="headings")
        for key, label, width in MOVIMIENTO_COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", self.open_detail)

        footer = ttk.Frame(self.window, padding=10)
        footer.grid(row=2, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="Cargando movimientos...")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        self.refresh_button = ttk.Button(footer, text="Actualizar", command=lambda: self.load(reset=True))
        self.clear_button = ttk.Button(footer, text="Limpiar filtros", command=self.clear_filters)
        self.previous_button = ttk.Button(footer, text="Anterior", command=lambda: self.change_page(-1))
        self.next_button = ttk.Button(footer, text="Siguiente", command=lambda: self.change_page(1))
        self.detail_button = ttk.Button(footer, text="Ver detalle", command=self.open_detail)
        for button in (self.refresh_button, self.clear_button, self.previous_button, self.next_button, self.detail_button):
            button.pack(side="right", padx=(6, 0))

    def clear_filters(self):
        for variable in self.filter_vars.values():
            variable.set("")
        self.load(reset=True)

    def change_page(self, delta: int):
        current = int(self.pagination.get("page") or self.page)
        pages = int(self.pagination.get("pages") or 0)
        target = max(1, min(pages or 1, current + delta))
        if target != current:
            self.page = target
            self.load(reset=False)

    def load(self, reset: bool = False):
        if self._loading or not self.is_open:
            return
        if reset:
            self.page = 1
        try:
            params = build_movimientos_filters(
                {key: variable.get() for key, variable in self.filter_vars.items()},
                page=self.page,
                per_page=self.per_page,
            )
        except (TypeError, ValueError) as exc:
            self._show_read_error(exc)
            return

        self._loading = True
        self._set_loading(True)

        def worker():
            try:
                result = self.service.listar_movimientos(params)
            except Exception as exc:
                safe_after(self.window, 0, lambda error=exc: self._finish_error(error))
                return
            safe_after(self.window, 0, lambda: self._finish_load(result))

        threading.Thread(target=worker, name="movimientos-almacen", daemon=True).start()

    def _finish_load(self, response: dict):
        if not self.is_open:
            return
        self._loading = False
        self._set_loading(False)
        self.rows = [dict(row or {}) for row in response.get("items") or response.get("movimientos") or []]
        self.pagination = dict(response.get("pagination") or {})
        self.page = int(self.pagination.get("page") or self.page)
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(index), values=_movement_values(row))
        total = int(self.pagination.get("total") or 0)
        pages = int(self.pagination.get("pages") or 0)
        if not self.rows:
            self.status_var.set("No hay movimientos con los filtros seleccionados.")
        else:
            self.status_var.set(f"Pagina {self.page} de {pages or 1} | {total} movimientos")
        self._update_page_buttons()

    def _finish_error(self, exc: Exception):
        if not self.is_open:
            return
        self._loading = False
        self._set_loading(False)
        self.status_var.set("No se pudieron cargar los movimientos.")
        self._show_read_error(exc)

    def _set_loading(self, loading: bool):
        if not self.is_open:
            return
        state = "disabled" if loading else "normal"
        for button in (self.refresh_button, self.clear_button, self.previous_button, self.next_button, self.detail_button):
            button.configure(state=state)
        if loading:
            self.status_var.set("Cargando movimientos...")

    def _update_page_buttons(self):
        if self._loading or not self.is_open:
            return
        current = int(self.pagination.get("page") or self.page)
        pages = int(self.pagination.get("pages") or 0)
        self.previous_button.configure(state="normal" if current > 1 else "disabled")
        self.next_button.configure(state="normal" if pages and current < pages else "disabled")
        self.detail_button.configure(state="normal" if self.rows else "disabled")

    def open_detail(self, _event=None):
        if not self.is_open:
            return
        selected = self.tree.focus()
        if not selected:
            messagebox.showwarning("Movimientos", "Seleccione un movimiento.", parent=self.window)
            return
        try:
            row = self.rows[int(selected)]
        except (IndexError, TypeError, ValueError):
            messagebox.showwarning("Movimientos", "No se pudo identificar el movimiento.", parent=self.window)
            return
        movement_id = row.get("id")
        key = str(movement_id or selected)
        existing = self._detail_windows.get(key)
        if existing and existing.is_open:
            existing.focus()
            return
        dialog = MovimientoDetalleDialog(self.window, self.service, row, on_close=lambda: self._detail_windows.pop(key, None))
        self._detail_windows[key] = dialog

    def _show_read_error(self, exc: Exception):
        if isinstance(exc, SessionExpiredError):
            if handle_session_expired(self.window, str(exc)):
                return
        if isinstance(exc, PermissionDeniedError):
            messagebox.showwarning("Movimientos", str(exc), parent=self.window)
            return
        if isinstance(exc, RecordNotFoundError):
            messagebox.showinfo("Movimientos", str(exc), parent=self.window)
            return
        if isinstance(exc, ApiReadError):
            messagebox.showerror("Movimientos", str(exc), parent=self.window)
            return
        log_error("hilorama_desktop", "Error inesperado en vista Movimientos", exc)
        messagebox.showerror("Movimientos", "Ocurrio un error al consultar movimientos.", parent=self.window)


class MovimientoDetalleDialog:
    def __init__(self, parent, service: MovimientosApiService, row: dict, on_close=None):
        self.parent = parent
        self.service = service
        self.row = dict(row or {})
        self.on_close = on_close
        self._closed = False
        self.window = tk.Toplevel(parent)
        self.window.title("Detalle de movimiento")
        self.window.geometry("820x650")
        self.window.minsize(650, 480)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.text = tk.Text(self.window, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        self.text.pack(fill="both", expand=True)
        self._render(self.row)
        self._load_detail_async()

    @property
    def is_open(self):
        return not self._closed and widget_is_alive(self.window)

    def focus(self):
        if self.is_open:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if widget_is_alive(self.window):
            self.window.destroy()
        if callable(self.on_close):
            self.on_close()

    def _load_detail_async(self):
        movement_id = self.row.get("id")
        if not movement_id:
            return

        def worker():
            try:
                detail = self.service.obtener_movimiento(movement_id)
            except Exception as exc:
                safe_after(self.window, 0, lambda error=exc: self._show_error(error))
                return
            safe_after(self.window, 0, lambda: self._render(detail))

        threading.Thread(target=worker, name="detalle-movimiento", daemon=True).start()

    def _render(self, movement: dict):
        if not self.is_open:
            return
        self.row = dict(movement or self.row)
        metadata = redact_sensitive_data(self.row.get("metadata_json") or {})
        if not isinstance(metadata, dict):
            metadata = {"valor": metadata}
        reference_type = optional_text(self.row.get("referencia_tipo"))
        reference_id = optional_text(self.row.get("referencia_id"))
        note_id = metadata.get("nota_id") or (self.row.get("referencia_id") if str(self.row.get("referencia_tipo") or "").upper() == "NOTA" else None)
        client = metadata.get("cliente") or metadata.get("cliente_nombre") or self.row.get("cliente_sistema_id")
        branch = metadata.get("sucursal") or metadata.get("sucursal_nombre")
        lines = (
            f"ID: {optional_text(self.row.get('id'))}",
            f"Fecha: {format_datetime_mexico(self.row.get('fecha'))}",
            f"Producto ID: {optional_text(self.row.get('producto_id'))}",
            f"Codigo: {optional_text(self.row.get('codigo'))}",
            f"Marca / hilo / color: {optional_text(self.row.get('marca'))} / {optional_text(self.row.get('hilo'))} / {optional_text(self.row.get('color'))}",
            f"Tipo: {optional_text(self.row.get('tipo'))}",
            f"Stock anterior: {optional_text(self.row.get('stock_anterior'))}",
            f"Cantidad: {optional_text(self.row.get('cantidad'))}",
            f"Stock nuevo: {optional_text(self.row.get('stock_nuevo'))}",
            f"Motivo: {optional_text(self.row.get('motivo'))}",
            f"Nota ID: {optional_text(note_id)}",
            f"Referencia: {reference_type} / {reference_id}",
            f"Usuario: {optional_text(self.row.get('usuario'))}",
            f"Cliente: {optional_text(client)}",
            f"Sucursal: {optional_text(branch)}",
            f"Dispositivo: {optional_text(self.row.get('device_id'))}",
            f"Identificador de idempotencia: {format_support_identifier(self.row.get('idempotency_key'))}",
            "",
            "Metadatos redactados:",
            safe_pretty_json(metadata),
        )
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")

    def _show_error(self, exc: Exception):
        if not self.is_open:
            return
        if isinstance(exc, SessionExpiredError):
            if handle_session_expired(self.window, str(exc)):
                return
        if isinstance(exc, ApiReadError):
            messagebox.showerror("Detalle de movimiento", str(exc), parent=self.window)
            return
        log_error("hilorama_desktop", "Error inesperado al cargar detalle de movimiento", exc)


def _movement_values(row: dict) -> tuple[str, ...]:
    reference = " / ".join(
        value for value in (optional_text(row.get("referencia_tipo"), ""), optional_text(row.get("referencia_id"), "")) if value
    ) or EMPTY_VALUE
    return (
        format_datetime_mexico(row.get("fecha")),
        optional_text(row.get("producto_id") or row.get("codigo")),
        optional_text(row.get("tipo")),
        optional_text(row.get("stock_anterior")),
        optional_text(row.get("cantidad")),
        optional_text(row.get("stock_nuevo")),
        optional_text(row.get("motivo")),
        reference,
        optional_text(row.get("usuario")),
    )
