"""Heartbeat periodico contra el backend de licencias."""

import threading

try:
    from ..config import HEARTBEAT_INTERVAL_MS
    from ..api_client.render_api_client import RenderApiError
except ImportError:
    from config import HEARTBEAT_INTERVAL_MS
    from api_client.render_api_client import RenderApiError


class HeartbeatService:
    def __init__(self, root, auth_service, modulo_actual="desktop", on_blocked=None):
        self.root = root
        self.auth_service = auth_service
        self.modulo_actual = modulo_actual
        self.on_blocked = on_blocked
        self._running = False

    def set_module(self, modulo):
        self.modulo_actual = modulo

    def start(self):
        self._running = True
        self._schedule()

    def stop(self):
        self._running = False

    def _schedule(self):
        if self._running:
            self.root.after(HEARTBEAT_INTERVAL_MS, self._run_async)

    def _run_async(self):
        if not self._running:
            return
        threading.Thread(target=self._send, daemon=True).start()
        self._schedule()

    def _send(self):
        try:
            data = self.auth_service.heartbeat(modulo=self.modulo_actual)
        except RenderApiError:
            return

        if not data.get("permitido", True):
            mensaje = data.get("mensaje") or "El acceso fue bloqueado."
            if self.on_blocked:
                self.root.after(0, lambda: self.on_blocked(mensaje))
