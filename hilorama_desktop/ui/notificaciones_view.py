"""Campana, panel compacto y vista completa de notificaciones Desktop."""

from __future__ import annotations

from datetime import datetime
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

try:
    from ..services import notificaciones_service as servicio
    from ..utils.logger import log_error, log_info
except ImportError:
    from services import notificaciones_service as servicio
    from utils.logger import log_error, log_info


class NotificationTheme:
    BG = "#F4F5F7"
    SURFACE = "#FFFFFF"
    SURFACE_SOFT = "#F8FAFC"
    BORDER = "#DCE2EA"
    TEXT = "#1F2937"
    MUTED = "#64748B"
    TEAL = "#0F766E"
    TEAL_HOVER = "#115E59"
    BLUE = "#2563EB"
    BLUE_HOVER = "#1D4ED8"
    URGENT = "#B42318"
    URGENT_BG = "#FEECEB"
    ATTENTION = "#B45309"
    ATTENTION_BG = "#FFF4E5"
    NORMAL = "#475569"
    NORMAL_BG = "#EEF2F6"
    OPPORTUNITY = "#0F766E"
    OPPORTUNITY_BG = "#E8F5F2"
    RADIUS = 6
    SPACE_1 = 4
    SPACE_2 = 8
    SPACE_3 = 12
    SPACE_4 = 16


PRIORITY_STYLES = {
    "URGENTE": (NotificationTheme.URGENT, NotificationTheme.URGENT_BG, "Urgente"),
    "ATENCION": (NotificationTheme.ATTENTION, NotificationTheme.ATTENTION_BG, "Atención"),
    "NORMAL": (NotificationTheme.NORMAL, NotificationTheme.NORMAL_BG, "Normal"),
}

FILTERS = (
    "Todas",
    "Urgentes",
    "Pagos",
    "Empaque",
    "Envíos",
    "Impresión",
    "Escaneo",
    "Inventario",
    "Dormidas",
    "VIP",
)

FILTER_CATEGORIES = {
    "Pagos": {"PENDIENTE_PAGO", "PAGADA_SIN_EMPAQUETAR"},
    "Empaque": {"PAGADA_SIN_EMPAQUETAR", "EMPAQUE_INCOMPLETO"},
    "Envíos": {"COMPLETA_SIN_GUIA", "GUIA_SIN_ENVIO"},
    "Impresión": {"IMPRESION_PENDIENTE", "IMPRESION_FALLIDA"},
    "Escaneo": {"ERROR_ESCAN"},
    "Inventario": {"INVENTARIO_BAJO"},
    "Dormidas": {"DORMIDA"},
    "VIP": {"VIP_RECUPERAR"},
}


def texto_badge(total: Any) -> str:
    try:
        cantidad = max(int(total or 0), 0)
    except (TypeError, ValueError):
        cantidad = 0
    if cantidad <= 0:
        return ""
    return "99+" if cantidad > 99 else str(cantidad)


def geometria_vista_completa(screen_width: Any, screen_height: Any) -> tuple[int, int, int, int]:
    """Mantiene la vista completa dentro de pantallas pequenas y Full HD."""
    ancho_pantalla = max(int(screen_width or 0), 1)
    alto_pantalla = max(int(screen_height or 0), 1)
    ancho = min(ancho_pantalla, max(640, min(1040, ancho_pantalla - 80)))
    alto = min(alto_pantalla, max(480, min(760, alto_pantalla - 100)))
    x = max(0, (ancho_pantalla - ancho) // 2)
    y = max(0, (alto_pantalla - alto) // 2)
    return ancho, alto, x, y


def geometria_panel(
    screen_width: Any,
    screen_height: Any,
    bell_x: Any,
    bell_y: Any,
    bell_width: Any,
    bell_height: Any,
) -> tuple[int, int, int, int]:
    """Mantiene el panel debajo de la campana siempre que haya altura suficiente."""
    screen_w = max(360, int(screen_width or 0))
    screen_h = max(520, int(screen_height or 0))
    width = min(520, max(screen_w - 24, 360))
    x = int(bell_x or 0) + int(bell_width or 0) - width
    x = max(8, min(x, screen_w - width - 8))
    y = int(bell_y or 0) + int(bell_height or 0) + 6
    disponible_debajo = screen_h - y - 8
    if disponible_debajo >= 520:
        height = min(680, disponible_debajo)
    else:
        height = min(680, max(screen_h - 16, 520))
        y = 8
    return width, height, x, y


def _lista_resumen(resumen: dict[str, Any], seccion: str) -> list[dict[str, Any]]:
    operacion = list((resumen.get("operacion") or {}).get("notificaciones") or [])
    oportunidades = list((resumen.get("oportunidades") or {}).get("notificaciones") or [])
    if str(seccion).startswith("Operación"):
        return operacion
    if str(seccion).startswith("Oportunidades"):
        return oportunidades
    return operacion + oportunidades


def filtrar_notificaciones(
    resumen: dict[str, Any],
    seccion="Todas",
    filtro="Todas",
    busqueda="",
    limite=None,
) -> list[dict[str, Any]]:
    avisos = _lista_resumen(resumen or {}, seccion)
    if filtro == "Urgentes":
        avisos = [aviso for aviso in avisos if aviso.get("prioridad") == "URGENTE"]
    elif filtro in FILTER_CATEGORIES:
        categorias = FILTER_CATEGORIES[filtro]
        avisos = [aviso for aviso in avisos if aviso.get("categoria") in categorias]

    consulta = str(busqueda or "").strip().lower()
    if consulta:
        def coincide(aviso):
            metadata = aviso.get("metadata") if isinstance(aviso.get("metadata"), dict) else {}
            campos = (
                aviso.get("titulo"),
                aviso.get("mensaje"),
                aviso.get("cliente_nombre"),
                aviso.get("folio"),
                aviso.get("categoria"),
                metadata.get("codigo"),
                metadata.get("marca"),
                metadata.get("hilo"),
            )
            return consulta in " ".join(str(valor or "") for valor in campos).lower()
        avisos = [aviso for aviso in avisos if coincide(aviso)]
    if limite is not None:
        avisos = avisos[:max(int(limite), 0)]
    return avisos


def _fecha_legible(valor: Any) -> str:
    if not valor:
        return "Sin datos todavía"
    texto = str(valor).strip().replace("Z", "+00:00")
    try:
        fecha = datetime.fromisoformat(texto)
        return fecha.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(valor)


def _firma_avisos(avisos: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            aviso.get("key"),
            aviso.get("prioridad"),
            aviso.get("titulo"),
            aviso.get("mensaje"),
            aviso.get("tiempo_transcurrido"),
        )
        for aviso in avisos
    )


class _Tooltip:
    def __init__(self, widget, texto):
        self.widget = widget
        self.texto = texto
        self._job = None
        self._win = None
        widget.bind("<Enter>", self._programar, add="+")
        widget.bind("<Leave>", self._ocultar, add="+")
        widget.bind("<FocusOut>", self._ocultar, add="+")

    def _programar(self, _event=None):
        self._cancelar()
        self._job = self.widget.after(450, self._mostrar)

    def _cancelar(self):
        if self._job:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _mostrar(self):
        if self._win or not self.widget.winfo_exists():
            return
        self._win = tk.Toplevel(self.widget)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        x = self.widget.winfo_rootx() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._win.geometry(f"+{x}+{y}")
        tk.Label(
            self._win,
            text=self.texto,
            bg="#111827",
            fg="white",
            padx=8,
            pady=4,
            font=("Segoe UI", 9),
        ).pack()

    def _ocultar(self, _event=None):
        self._cancelar()
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


class NotificationBellButton(tk.Canvas):
    """Boton accesible con icono vectorial ligero y badge estable."""

    def __init__(self, parent, command):
        super().__init__(
            parent,
            width=48,
            height=44,
            bg="#FFFFFF",
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.command = command
        self.total = 0
        self.urgentes = 0
        self._hover = False
        self.bind("<Button-1>", lambda _event: self.command())
        self.bind("<Return>", lambda _event: self.command())
        self.bind("<space>", lambda _event: self.command())
        self.bind("<Enter>", self._entrar)
        self.bind("<Leave>", self._salir)
        self.bind("<FocusIn>", lambda _event: self._dibujar())
        self.bind("<FocusOut>", lambda _event: self._dibujar())
        _Tooltip(self, "Notificaciones")
        self._dibujar()

    def set_counts(self, total, urgentes=0):
        self.total = max(int(total or 0), 0)
        self.urgentes = max(int(urgentes or 0), 0)
        self._dibujar()

    def _entrar(self, _event=None):
        self._hover = True
        self._dibujar()

    def _salir(self, _event=None):
        self._hover = False
        self._dibujar()

    def _dibujar(self):
        self.delete("all")
        fondo = "#F1F5F9" if self._hover else "#FFFFFF"
        self.configure(bg=fondo)
        if self.focus_get() is self:
            self.create_rectangle(2, 2, 46, 42, outline=NotificationTheme.BLUE, width=2)
        color = NotificationTheme.URGENT if self.urgentes else "#334155"
        self.create_arc(12, 8, 30, 30, start=15, extent=150, style="arc", outline=color, width=2)
        self.create_line(12.6, 20, 11, 28, 31, 28, 29.4, 20, fill=color, width=2, smooth=True)
        self.create_line(11, 28, 31, 28, fill=color, width=2)
        self.create_oval(19, 30, 23, 34, fill=color, outline=color)
        self.create_oval(19.5, 6, 22.5, 9, fill=color, outline=color)

        badge = texto_badge(self.total)
        if badge:
            ancho = 25 if badge == "99+" else (21 if len(badge) > 1 else 18)
            x2 = 46
            x1 = x2 - ancho
            badge_color = NotificationTheme.URGENT if self.urgentes else NotificationTheme.BLUE
            self.create_oval(x1, 2, x2, 20, fill=badge_color, outline="#FFFFFF", width=2)
            self.create_text(
                (x1 + x2) / 2,
                11,
                text=badge,
                fill="white",
                font=("Segoe UI", 7 if badge == "99+" else 8, "bold"),
            )


class PriorityBadge(ctk.CTkLabel):
    def __init__(self, parent, prioridad):
        color, fondo, texto = PRIORITY_STYLES.get(prioridad, PRIORITY_STYLES["NORMAL"])
        super().__init__(
            parent,
            text=texto,
            text_color=color,
            fg_color=fondo,
            corner_radius=NotificationTheme.RADIUS,
            font=("Segoe UI", 10, "bold"),
            height=24,
            width=70,
        )


class NotificationCard(ctk.CTkFrame):
    def __init__(self, parent, aviso, on_action, compact=True):
        super().__init__(
            parent,
            fg_color=NotificationTheme.SURFACE,
            border_width=1,
            border_color=NotificationTheme.BORDER,
            corner_radius=NotificationTheme.RADIUS,
        )
        self.aviso = aviso
        self.on_action = on_action
        self.compact = compact
        self.grid_columnconfigure(1, weight=1)
        color, _, _ = PRIORITY_STYLES.get(aviso.get("prioridad"), PRIORITY_STYLES["NORMAL"])
        if aviso.get("seccion") == "OPORTUNIDADES" and aviso.get("prioridad") == "NORMAL":
            color = NotificationTheme.OPPORTUNITY
        ctk.CTkFrame(self, width=4, fg_color=color, corner_radius=2).grid(
            row=0, column=0, rowspan=5, sticky="ns", padx=(0, 0), pady=0
        )

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.grid(row=0, column=1, sticky="ew", padx=12, pady=(10, 3))
        cabecera.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            cabecera,
            text=aviso.get("titulo") or "Notificación",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
            justify="left",
            wraplength=300 if compact else 550,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        PriorityBadge(cabecera, aviso.get("prioridad") or "NORMAL").grid(row=0, column=1, sticky="e")

        contexto = self._contexto()
        if contexto:
            ctk.CTkLabel(
                self,
                text=contexto,
                text_color=NotificationTheme.MUTED,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
                justify="left",
                wraplength=410 if compact else 650,
            ).grid(row=1, column=1, sticky="ew", padx=12, pady=(0, 2))

        ctk.CTkLabel(
            self,
            text=aviso.get("mensaje") or "",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 11),
            anchor="w",
            justify="left",
            wraplength=410 if compact else 650,
        ).grid(row=2, column=1, sticky="ew", padx=12, pady=(0, 4))

        referencia = aviso.get("tiempo_transcurrido") or _fecha_legible(aviso.get("fecha_referencia"))
        ctk.CTkLabel(
            self,
            text=referencia,
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=3, column=1, sticky="ew", padx=12, pady=(0, 6))

        acciones = ctk.CTkFrame(self, fg_color="transparent")
        acciones.grid(row=4, column=1, sticky="ew", padx=12, pady=(0, 10))
        acciones.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            acciones,
            text=aviso.get("accion_texto") or "Abrir",
            command=lambda: self.on_action(self.aviso, self.aviso.get("accion")),
            height=32,
            corner_radius=NotificationTheme.RADIUS,
            fg_color=NotificationTheme.TEAL if aviso.get("seccion") == "OPORTUNIDADES" else NotificationTheme.BLUE,
            hover_color=NotificationTheme.TEAL_HOVER if aviso.get("seccion") == "OPORTUNIDADES" else NotificationTheme.BLUE_HOVER,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")

        secundarias = aviso.get("acciones_secundarias") or []
        if secundarias:
            btn_menu = ctk.CTkButton(
                acciones,
                text="⋯",
                width=34,
                height=32,
                corner_radius=NotificationTheme.RADIUS,
                fg_color=NotificationTheme.SURFACE_SOFT,
                hover_color="#E2E8F0",
                text_color=NotificationTheme.TEXT,
                font=("Segoe UI", 16, "bold"),
                command=lambda: self._abrir_menu(btn_menu),
            )
            btn_menu.grid(row=0, column=1, sticky="e")
            _Tooltip(btn_menu, "Más acciones")

    def _contexto(self):
        partes = []
        if self.aviso.get("cliente_nombre"):
            partes.append(str(self.aviso["cliente_nombre"]))
        if self.aviso.get("folio"):
            partes.append(f"Venta {self.aviso['folio']}")
        metadata = self.aviso.get("metadata") or {}
        if metadata.get("codigo") and not self.aviso.get("folio"):
            partes.append(f"Código {metadata['codigo']}")
        return " · ".join(partes)

    def _abrir_menu(self, button):
        menu = tk.Menu(self, tearoff=False, font=("Segoe UI", 10))
        for secundaria in self.aviso.get("acciones_secundarias") or []:
            accion = secundaria.get("accion")
            texto = secundaria.get("texto") or "Abrir"
            menu.add_command(
                label=texto,
                command=lambda accion=accion: self.on_action(self.aviso, accion),
            )
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()


class NotificationEmptyState(ctk.CTkFrame):
    def __init__(self, parent, texto):
        super().__init__(parent, fg_color="transparent")
        ctk.CTkLabel(
            self,
            text=texto,
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 12),
            justify="center",
            wraplength=360,
        ).pack(fill="x", padx=24, pady=36)


class NotificationLoadingState(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        for ancho in (0.92, 0.78, 0.86):
            bloque = ctk.CTkFrame(
                self,
                height=70,
                fg_color="#E8EDF3",
                corner_radius=NotificationTheme.RADIUS,
            )
            bloque.pack(fill="x", padx=8, pady=5)
            bloque.pack_propagate(False)
            ctk.CTkFrame(
                bloque,
                height=10,
                width=int(360 * ancho),
                fg_color="#D7DEE8",
                corner_radius=4,
            ).pack(anchor="w", padx=12, pady=(14, 6))


class NotificationContent(ctk.CTkFrame):
    """Contenido reutilizado por el panel compacto y la vista completa."""

    def __init__(self, parent, on_action, compact=True, on_retry=None):
        super().__init__(parent, fg_color=NotificationTheme.BG, corner_radius=0)
        self.on_action = on_action
        self.on_retry = on_retry
        self.compact = compact
        self.resumen = servicio.resumen_vacio()
        self.loading = True
        self.error = None
        self._firma_render = None
        self._search_job = None
        self.seccion_var = tk.StringVar(value="Todas")
        self.filtro_var = tk.StringVar(value="Todas")
        self.busqueda_var = tk.StringVar()
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.segmentos = ctk.CTkSegmentedButton(
            self,
            values=["Todas", "Operación", "Oportunidades"],
            variable=self.seccion_var,
            command=lambda _valor: self.render(force=True),
            height=34,
            corner_radius=NotificationTheme.RADIUS,
            fg_color="#E8EDF3",
            selected_color=NotificationTheme.TEAL,
            selected_hover_color=NotificationTheme.TEAL_HOVER,
            unselected_color="#E8EDF3",
            unselected_hover_color="#DCE3EB",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 11, "bold"),
        )
        self.segmentos.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))

        self.resumen_label = ctk.CTkLabel(
            self,
            text="Urgentes 0 · Atención 0 · Normales 0",
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self.resumen_label.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        tools.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            tools,
            text="Buscar",
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, padx=(0, 6))
        self.search = ctk.CTkEntry(
            tools,
            textvariable=self.busqueda_var,
            placeholder_text="Buscar cliente, folio, producto o código",
            height=34,
            corner_radius=NotificationTheme.RADIUS,
            border_color=NotificationTheme.BORDER,
            font=("Segoe UI", 11),
        )
        self.search.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.busqueda_var.trace_add("write", self._programar_busqueda)
        self.filter = ctk.CTkComboBox(
            tools,
            values=list(FILTERS),
            variable=self.filtro_var,
            command=lambda _valor: self.render(force=True),
            width=132 if self.compact else 170,
            height=34,
            corner_radius=NotificationTheme.RADIUS,
            border_color=NotificationTheme.BORDER,
            button_color="#CBD5E1",
            button_hover_color="#B8C4D2",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 10),
        )
        self.filter.grid(row=0, column=2, sticky="e")

        self.error_frame = ctk.CTkFrame(
            self,
            fg_color="#FFF7ED",
            border_width=1,
            border_color="#FED7AA",
            corner_radius=NotificationTheme.RADIUS,
        )
        self.error_label = ctk.CTkLabel(
            self.error_frame,
            text="No fue posible actualizar las notificaciones.",
            text_color="#9A3412",
            font=("Segoe UI", 10),
            anchor="w",
        )
        self.error_label.pack(side="left", fill="x", expand=True, padx=10, pady=6)
        if self.on_retry:
            ctk.CTkButton(
                self.error_frame,
                text="Reintentar",
                command=self.on_retry,
                width=82,
                height=28,
                corner_radius=NotificationTheme.RADIUS,
                fg_color="transparent",
                hover_color="#FFEDD5",
                text_color="#9A3412",
                border_width=1,
                border_color="#FDBA74",
                font=("Segoe UI", 10, "bold"),
            ).pack(side="right", padx=(0, 8), pady=4)

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color="#CBD5E1",
            scrollbar_button_hover_color="#94A3B8",
        )
        self.scroll.grid(row=4, column=0, sticky="nsew", padx=(6, 2), pady=(0, 6))

    def _programar_busqueda(self, *_args):
        if self._search_job:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(140, lambda: self.render(force=True))

    def set_data(self, resumen, loading=False, error=None):
        self.resumen = resumen or servicio.resumen_vacio()
        self.loading = bool(loading)
        self.error = error
        self.render(force=False)

    def render(self, force=False):
        avisos = filtrar_notificaciones(
            self.resumen,
            seccion=self.seccion_var.get(),
            filtro=self.filtro_var.get(),
            busqueda=self.busqueda_var.get(),
            limite=20 if self.compact else None,
        )
        firma = (
            self.loading,
            bool(self.error),
            self.seccion_var.get(),
            self.filtro_var.get(),
            self.busqueda_var.get().strip().lower(),
            _firma_avisos(avisos),
        )
        self._actualizar_resumen()
        self._actualizar_error()
        if not force and firma == self._firma_render:
            return
        self._firma_render = firma
        for child in self.scroll.winfo_children():
            child.destroy()

        total_previo = int(self.resumen.get("total") or 0)
        if self.loading and total_previo == 0:
            NotificationLoadingState(self.scroll).pack(fill="x", padx=3, pady=3)
            return
        if not avisos:
            if self.busqueda_var.get().strip() or self.filtro_var.get() != "Todas":
                texto = "No encontramos avisos con este filtro."
            elif self.seccion_var.get().startswith("Oportunidades"):
                texto = "No hay oportunidades comerciales nuevas por ahora."
            else:
                texto = "No tienes pendientes en este momento."
            NotificationEmptyState(self.scroll, texto).pack(fill="x", padx=3, pady=3)
            return
        for aviso in avisos:
            NotificationCard(self.scroll, aviso, self.on_action, compact=self.compact).pack(
                fill="x", padx=3, pady=5
            )
        if self.compact:
            total_filtrado = len(filtrar_notificaciones(
                self.resumen,
                seccion=self.seccion_var.get(),
                filtro=self.filtro_var.get(),
                busqueda=self.busqueda_var.get(),
            ))
            if total_filtrado > 20:
                ctk.CTkLabel(
                    self.scroll,
                    text=f"Se muestran 20 de {total_filtrado} avisos. Usa Ver todas para continuar.",
                    text_color=NotificationTheme.MUTED,
                    font=("Segoe UI", 10),
                ).pack(fill="x", padx=8, pady=8)

    def _actualizar_resumen(self):
        self.resumen_label.configure(
            text=(
                f"Urgentes {self.resumen.get('urgentes', 0)}  ·  "
                f"Atención {self.resumen.get('atencion', 0)}  ·  "
                f"Normales {self.resumen.get('normales', 0)}"
            )
        )
        operacion = (self.resumen.get("operacion") or {}).get("total", 0)
        oportunidades = (self.resumen.get("oportunidades") or {}).get("total", 0)
        self.segmentos.configure(values=[
            f"Todas {self.resumen.get('total', 0)}",
            f"Operación {operacion}",
            f"Oportunidades {oportunidades}",
        ])
        actual = self.seccion_var.get()
        if actual.startswith("Operación"):
            self.seccion_var.set(f"Operación {operacion}")
        elif actual.startswith("Oportunidades"):
            self.seccion_var.set(f"Oportunidades {oportunidades}")
        else:
            self.seccion_var.set(f"Todas {self.resumen.get('total', 0)}")

    def _actualizar_error(self):
        if self.error:
            self.error_label.configure(text=str(self.error))
            self.error_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 6))
        else:
            self.error_frame.grid_remove()


class NotificationPanel(ctk.CTkToplevel):
    WIDTH = 520
    HEIGHT = 680

    def __init__(self, controller):
        super().__init__(controller.root)
        self.controller = controller
        self.overrideredirect(True)
        self.transient(controller.root)
        self.configure(fg_color=NotificationTheme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.bind("<Escape>", lambda _event: self.close())
        self._outside_binding = None
        self._build()
        self._position()
        self.after(20, self._activar_cierre_exterior)
        self.focus_force()

    def _build(self):
        header = ctk.CTkFrame(
            self,
            fg_color=NotificationTheme.SURFACE,
            corner_radius=0,
            border_width=1,
            border_color=NotificationTheme.BORDER,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Notificaciones",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 17, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        self.total_label = ctk.CTkLabel(
            header,
            text="0 asuntos requieren atención",
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 10),
            anchor="w",
        )
        self.total_label.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 2))
        self.updated_label = ctk.CTkLabel(
            header,
            text="Sin datos todavía",
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.updated_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 9))
        self.refresh_button = ctk.CTkButton(
            header,
            text="Actualizar",
            width=84,
            height=30,
            corner_radius=NotificationTheme.RADIUS,
            fg_color=NotificationTheme.SURFACE_SOFT,
            hover_color="#E2E8F0",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 10, "bold"),
            command=lambda: self.controller.refresh(incluir_oportunidades=True),
        )
        self.refresh_button.grid(row=0, column=1, rowspan=3, padx=(4, 4), pady=10)
        close_button = ctk.CTkButton(
            header,
            text="×",
            width=32,
            height=30,
            corner_radius=NotificationTheme.RADIUS,
            fg_color="transparent",
            hover_color="#E2E8F0",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 18),
            command=self.close,
        )
        close_button.grid(row=0, column=2, rowspan=3, padx=(0, 10), pady=10)
        _Tooltip(close_button, "Cerrar")

        self.content = NotificationContent(
            self,
            self.controller.handle_action,
            compact=True,
            on_retry=lambda: self.controller.refresh(incluir_oportunidades=True),
        )
        self.content.grid(row=1, column=0, sticky="nsew")
        footer = ctk.CTkFrame(self, fg_color=NotificationTheme.SURFACE, corner_radius=0)
        footer.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(
            footer,
            text="Ver todas",
            command=self.controller.open_full_view,
            height=34,
            corner_radius=NotificationTheme.RADIUS,
            fg_color="transparent",
            hover_color="#E2E8F0",
            text_color=NotificationTheme.BLUE,
            font=("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=12, pady=7)

    def _position(self):
        self.update_idletasks()
        bell = self.controller.bell
        width, height, x, y = geometria_panel(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            bell.winfo_rootx(),
            bell.winfo_rooty(),
            bell.winfo_width(),
            bell.winfo_height(),
        )
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _activar_cierre_exterior(self):
        if not self.winfo_exists():
            return
        self._outside_binding = self.controller.root.bind("<Button-1>", self._click_root, add="+")

    def _click_root(self, event):
        if not self.winfo_exists():
            return
        x, y = event.x_root, event.y_root
        dentro_panel = (
            self.winfo_rootx() <= x <= self.winfo_rootx() + self.winfo_width()
            and self.winfo_rooty() <= y <= self.winfo_rooty() + self.winfo_height()
        )
        bell = self.controller.bell
        dentro_bell = (
            bell.winfo_rootx() <= x <= bell.winfo_rootx() + bell.winfo_width()
            and bell.winfo_rooty() <= y <= bell.winfo_rooty() + bell.winfo_height()
        )
        if not dentro_panel and not dentro_bell:
            self.close()

    def update_data(self, resumen, loading=False, error=None):
        if not self.winfo_exists():
            return
        total = int(resumen.get("total") or 0)
        self.total_label.configure(text=f"{total} asuntos requieren atención" if total != 1 else "1 asunto requiere atención")
        self.updated_label.configure(text=f"Actualizado: {_fecha_legible(resumen.get('generado_en'))}")
        self.refresh_button.configure(state="disabled" if loading else "normal", text="Actualizando..." if loading else "Actualizar")
        self.content.set_data(resumen, loading=loading, error=error)

    def close(self):
        if self._outside_binding:
            try:
                self.controller.root.unbind("<Button-1>", self._outside_binding)
            except tk.TclError:
                pass
            self._outside_binding = None
        self.controller.panel = None
        try:
            self.destroy()
        except tk.TclError:
            pass


class NotificationsFullView(ctk.CTkToplevel):
    def __init__(self, controller):
        super().__init__(controller.root)
        self.controller = controller
        self.title("Todas las notificaciones")
        ancho, alto, x, y = geometria_vista_completa(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
        )
        self.geometry(f"{ancho}x{alto}+{x}+{y}")
        self.minsize(min(820, ancho), min(580, alto))
        self.configure(fg_color=NotificationTheme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.bind("<Escape>", lambda _event: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)

        header = ctk.CTkFrame(self, fg_color=NotificationTheme.SURFACE, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Todas las notificaciones",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=14)
        self.refresh_button = ctk.CTkButton(
            header,
            text="Actualizar",
            command=lambda: controller.refresh(incluir_oportunidades=True),
            width=100,
            height=34,
            corner_radius=NotificationTheme.RADIUS,
        )
        self.refresh_button.grid(row=0, column=1, padx=20, pady=12)
        self.content = NotificationContent(
            self,
            controller.handle_action,
            compact=False,
            on_retry=lambda: controller.refresh(incluir_oportunidades=True),
        )
        self.content.grid(row=1, column=0, sticky="nsew")

    def update_data(self, resumen, loading=False, error=None):
        if self.winfo_exists():
            self.refresh_button.configure(state="disabled" if loading else "normal")
            self.content.set_data(resumen, loading=loading, error=error)

    def close(self):
        self.controller.full_view = None
        try:
            self.destroy()
        except tk.TclError:
            pass


class MessageDraftWindow(ctk.CTkToplevel):
    def __init__(self, parent, aviso):
        super().__init__(parent)
        self.title("Preparar mensaje")
        self.geometry("680x430")
        self.minsize(560, 360)
        self.transient(parent.winfo_toplevel())
        self.configure(fg_color=NotificationTheme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        ctk.CTkLabel(
            self,
            text=f"Mensaje para {aviso.get('cliente_nombre') or 'la clienta'}",
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(
            self,
            text="Revísalo y edítalo antes de usarlo. Hilorama no lo enviará automáticamente.",
            text_color=NotificationTheme.MUTED,
            font=("Segoe UI", 11),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.textbox = ctk.CTkTextbox(
            self,
            corner_radius=NotificationTheme.RADIUS,
            border_width=1,
            border_color=NotificationTheme.BORDER,
            fg_color=NotificationTheme.SURFACE,
            text_color=NotificationTheme.TEXT,
            font=("Segoe UI", 12),
            wrap="word",
        )
        self.textbox.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        self.textbox.insert("1.0", servicio.preparar_mensaje(aviso))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            actions,
            text="Cerrar",
            command=self.destroy,
            fg_color="#64748B",
            hover_color="#475569",
            corner_radius=NotificationTheme.RADIUS,
        ).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="Copiar mensaje",
            command=self._copiar,
            fg_color=NotificationTheme.TEAL,
            hover_color=NotificationTheme.TEAL_HOVER,
            corner_radius=NotificationTheme.RADIUS,
        ).grid(row=0, column=2, padx=(8, 0))

    def _copiar(self):
        texto = self.textbox.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.update_idletasks()


class NotificationBellController:
    REFRESH_MS = 180_000
    OPPORTUNITIES_REFRESH_SECONDS = 86_400

    def __init__(self, root, parent, on_navigation: Callable[[dict[str, Any], str], None]):
        self.root = root
        self.on_navigation = on_navigation
        self.bell = NotificationBellButton(parent, self.toggle_panel)
        self.panel: NotificationPanel | None = None
        self.full_view: NotificationsFullView | None = None
        self.resumen = servicio.obtener_ultimo_resumen()
        self.error = None
        self._refreshing = False
        self._pending_refresh = False
        self._pending_opportunities = False
        self._event_include_opportunities = False
        self._periodic_job = None
        self._event_job = None
        self._poll_job = None
        self._startup_job = None
        self._followup_job = None
        self._stopped = False
        self._last_opportunities_refresh = 0.0
        self._lock = threading.Lock()
        self._resultados = queue.Queue()
        servicio.registrar_listener_notificaciones(self._on_service_event)
        self._apply_counts()

    def start(self):
        self._poll_job = self.root.after(60, self._procesar_resultados)
        self._startup_job = self.root.after(
            250,
            lambda: self.refresh(incluir_oportunidades=True),
        )
        self._schedule_periodic()

    def shutdown(self):
        self._stopped = True
        servicio.quitar_listener_notificaciones(self._on_service_event)
        servicio.invalidar_cache_sesion()
        for job in (
            self._startup_job,
            self._periodic_job,
            self._event_job,
            self._poll_job,
            self._followup_job,
        ):
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        if self.panel:
            self.panel.close()
        if self.full_view:
            self.full_view.close()

    def _schedule_periodic(self):
        if self._stopped:
            return
        self._periodic_job = self.root.after(self.REFRESH_MS, self._periodic_refresh)

    def _periodic_refresh(self):
        self._periodic_job = None
        incluir = time.time() - self._last_opportunities_refresh >= self.OPPORTUNITIES_REFRESH_SECONDS
        self.refresh(incluir_oportunidades=incluir)
        self._schedule_periodic()

    def _on_service_event(self, incluir_oportunidades=False):
        if self._stopped:
            return
        self._resultados.put(("evento", bool(incluir_oportunidades)))

    def _debounce_event(self, incluir_oportunidades):
        self._event_include_opportunities = (
            self._event_include_opportunities or incluir_oportunidades
        )
        if self._event_job:
            try:
                self.root.after_cancel(self._event_job)
            except tk.TclError:
                pass
        self._event_job = self.root.after(450, self._run_event_refresh)

    def _run_event_refresh(self):
        self._event_job = None
        incluir = self._event_include_opportunities
        self._event_include_opportunities = False
        self.refresh(incluir_oportunidades=incluir)

    def refresh(self, incluir_oportunidades=False):
        if self._stopped:
            return False
        with self._lock:
            if self._refreshing:
                self._pending_refresh = True
                self._pending_opportunities = self._pending_opportunities or incluir_oportunidades
                return False
            self._refreshing = True
        self.error = None
        self._update_views(loading=True)

        def worker():
            try:
                data = servicio.obtener_resumen(incluir_oportunidades=incluir_oportunidades)
            except Exception as exc:
                log_error("hilorama_desktop", "No se pudieron actualizar las notificaciones", exc)
                self._resultados.put(("refresh", None, exc, incluir_oportunidades))
                return
            self._resultados.put(("refresh", data, None, incluir_oportunidades))

        threading.Thread(target=worker, daemon=True, name="hilorama-notificaciones").start()
        return True

    def _procesar_resultados(self):
        if self._stopped:
            return
        while True:
            try:
                resultado = self._resultados.get_nowait()
            except queue.Empty:
                break
            tipo = resultado[0]
            if tipo == "evento":
                self._debounce_event(resultado[1])
            elif tipo == "refresh":
                self._finish_refresh(resultado[1], resultado[2], resultado[3])
            elif tipo == "control_error":
                messagebox.showerror(
                    "Oportunidades",
                    "No se pudo guardar el recordatorio. Revisa la conexión e inténtalo de nuevo.",
                    parent=self.root,
                )
            elif tipo == "control_ok":
                self.refresh(incluir_oportunidades=True)
        if not self._stopped:
            self._poll_job = self.root.after(60, self._procesar_resultados)

    def _finish_refresh(self, data, error, incluyo_oportunidades):
        if self._stopped:
            return
        if data is not None:
            self.resumen = data
            self.error = None
            if incluyo_oportunidades:
                self._last_opportunities_refresh = time.time()
            log_info("hilorama_desktop", f"Campana actualizada: {data.get('total', 0)} avisos")
        else:
            self.error = "No fue posible actualizar las notificaciones. Usa Actualizar para reintentar."
        with self._lock:
            self._refreshing = False
            pending = self._pending_refresh
            pending_opportunities = self._pending_opportunities
            self._pending_refresh = False
            self._pending_opportunities = False
        self._apply_counts()
        self._update_views(loading=False)
        if pending:
            self._followup_job = self.root.after(
                120,
                lambda: self.refresh(incluir_oportunidades=pending_opportunities),
            )

    def _apply_counts(self):
        self.bell.set_counts(self.resumen.get("total", 0), self.resumen.get("urgentes", 0))

    def _update_views(self, loading=False):
        if self.panel and self.panel.winfo_exists():
            self.panel.update_data(self.resumen, loading=loading, error=self.error)
        if self.full_view and self.full_view.winfo_exists():
            self.full_view.update_data(self.resumen, loading=loading, error=self.error)

    def toggle_panel(self):
        if self.panel and self.panel.winfo_exists():
            self.panel.close()
            return
        self.panel = NotificationPanel(self)
        self.panel.update_data(self.resumen, loading=self._refreshing, error=self.error)
        self.refresh(incluir_oportunidades=False)

    def open_full_view(self):
        if self.panel:
            self.panel.close()
        if self.full_view and self.full_view.winfo_exists():
            self.full_view.lift()
            self.full_view.focus_force()
            return
        self.full_view = NotificationsFullView(self)
        self.full_view.update_data(self.resumen, loading=self._refreshing, error=self.error)
        self.refresh(incluir_oportunidades=False)

    def handle_action(self, aviso, accion):
        accion = str(accion or "").upper()
        if accion in {"PREPARAR_MENSAJE", "PREPARAR_RECORDATORIO_PAGO"}:
            MessageDraftWindow(self.root, aviso)
            return
        if accion in {"RECORDAR_3", "RECORDAR_7", "OCULTAR_30"}:
            self._controlar_oportunidad(aviso, accion)
            return
        if self.panel:
            self.panel.close()
        self.on_navigation(aviso, accion)

    def _controlar_oportunidad(self, aviso, accion):
        if accion == "OCULTAR_30" and not messagebox.askyesno(
            "Ocultar oportunidad",
            "Esta oportunidad dejará de aparecer durante 30 días. ¿Deseas continuar?",
            parent=self.root,
        ):
            return
        cliente_id = aviso.get("cliente_id")
        categoria = aviso.get("categoria")
        if not cliente_id or not categoria:
            return

        def worker():
            try:
                servicio.controlar_oportunidad(cliente_id, categoria, accion)
            except Exception as exc:
                log_error("hilorama_desktop", "No se pudo guardar el recordatorio", exc)
                self._resultados.put(("control_error",))
                return
            self._resultados.put(("control_ok",))

        threading.Thread(target=worker, daemon=True, name="hilorama-oportunidad-control").start()
