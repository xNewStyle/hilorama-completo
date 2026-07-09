import tkinter as tk
from tkinter import messagebox, ttk

try:
    from ..services.auth_service import AuthService
except ImportError:
    from services.auth_service import AuthService


class LoginWindow(tk.Tk):
    def __init__(self, auth_service=None, modulo="desktop"):
        super().__init__()
        self.auth_service = auth_service or AuthService()
        self.modulo = modulo
        self.session = None

        self.title("Hilorama - Acceso")
        self.geometry("380x310")
        self.resizable(False, False)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

    def _build(self):
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Hilorama Desktop", font=("Segoe UI", 18, "bold")).pack(pady=(0, 18))

        self.usuario_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.licencia_var = tk.StringVar()

        self._campo(frame, "Usuario", self.usuario_var)
        self._campo(frame, "Contraseña", self.password_var, show="*")
        self._campo(frame, "Negocio/licencia", self.licencia_var)

        self.estado = ttk.Label(frame, text="", foreground="#B91C1C", wraplength=320)
        self.estado.pack(fill="x", pady=(8, 0))

        ttk.Button(frame, text="Entrar", command=self._login).pack(fill="x", pady=(16, 0))

    def _campo(self, parent, label, variable, show=None):
        ttk.Label(parent, text=label).pack(anchor="w")
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.pack(fill="x", pady=(2, 10))
        entry.bind("<Return>", lambda _event: self._login())

    def _login(self):
        usuario = self.usuario_var.get().strip()
        password = self.password_var.get()
        licencia = self.licencia_var.get().strip()
        if not usuario or not password:
            self.estado.configure(text="Ingrese usuario y contraseña.")
            return

        self.estado.configure(text="Validando acceso...")
        self.update_idletasks()
        try:
            self.session = self.auth_service.login(usuario, password, licencia, modulo=self.modulo)
        except Exception as exc:
            self.session = None
            self.estado.configure(text=str(exc))
            return
        self.destroy()

    def _cancelar(self):
        self.session = None
        self.destroy()


def solicitar_login(auth_service=None, modulo="desktop"):
    win = LoginWindow(auth_service=auth_service, modulo=modulo)
    win.mainloop()
    return win.session
