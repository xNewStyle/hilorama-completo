"""Cliente HTTP pequeno para el backend de Render."""

import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

try:
    from ..config import RENDER_API_BASE_URL
except ImportError:
    from config import RENDER_API_BASE_URL


class RenderApiError(Exception):
    def __init__(self, message, status=None, path=None, base_url=None):
        super().__init__(message)
        self.status = status
        self.path = path
        self.base_url = base_url


class RenderApiClient:
    def __init__(self, base_url=None, timeout=10):
        self.base_url = (base_url or RENDER_API_BASE_URL).rstrip("/")
        self.timeout = timeout

    def post(self, path, payload, token=None):
        return self._request("POST", path, payload=payload, token=token)

    def get(self, path, params=None, token=None):
        if params:
            query = urlencode(params, doseq=True)
            separator = "&" if "?" in path else "?"
            path = f"{path}{separator}{query}"
        return self._request("GET", path, token=token)

    def patch(self, path, payload, token=None):
        return self._request("PATCH", path, payload=payload, token=token)

    def delete(self, path, payload=None, token=None):
        return self._request("DELETE", path, payload=payload, token=token)

    def admin_listar_clientes(self, token=None):
        return self.get("/api/admin/clientes", token=token)

    def admin_crear_cliente(self, data, token=None):
        return self.post("/api/admin/clientes", data, token=token)

    def admin_actualizar_cliente(self, cliente_id, data, token=None):
        return self.patch(f"/api/admin/clientes/{cliente_id}", data, token=token)

    def admin_listar_usuarios_cliente(self, cliente_id, token=None):
        return self.get(f"/api/admin/clientes/{cliente_id}/usuarios", token=token)

    def admin_crear_usuario_cliente(self, cliente_id, data, token=None):
        return self.post(f"/api/admin/clientes/{cliente_id}/usuarios", data, token=token)

    def admin_reset_password_usuario(self, usuario_id, data, token=None):
        return self.post(f"/api/admin/usuarios/{usuario_id}/reset-password", data, token=token)

    def admin_activar_usuario(self, usuario_id, token=None):
        return self.post(f"/api/admin/usuarios/{usuario_id}/activar", {}, token=token)

    def admin_desactivar_usuario(self, usuario_id, token=None):
        return self.post(f"/api/admin/usuarios/{usuario_id}/desactivar", {}, token=token)

    def admin_suspender_cliente(self, cliente_id, token=None):
        return self.post(f"/api/admin/clientes/{cliente_id}/suspender", {}, token=token)

    def admin_bloquear_cliente(self, cliente_id, token=None):
        return self.post(f"/api/admin/clientes/{cliente_id}/bloquear", {}, token=token)

    def admin_reactivar_cliente(self, cliente_id, token=None):
        return self.post(f"/api/admin/clientes/{cliente_id}/reactivar", {}, token=token)

    def admin_sesiones_activas(self, token=None):
        return self.get("/api/admin/sesiones-activas", token=token)

    def admin_auditoria(self, params=None, token=None):
        return self.get("/api/admin/auditoria-general", params=params, token=token)

    def admin_auditoria_detalle(self, auditoria_id, token=None):
        return self.get(f"/api/admin/auditoria/{auditoria_id}", token=token)

    def listar_productos(self, params=None, token=None):
        return self.get("/api/productos", params=params, token=token)

    def obtener_producto(self, producto_id, token=None):
        return self.get(f"/api/productos/{producto_id}", token=token)

    def obtener_producto_por_codigo(self, codigo, token=None):
        codigo_url = quote(str(codigo or ""), safe="")
        return self.get(f"/api/productos/codigo/{codigo_url}", token=token)

    def listar_marcas(self, token=None):
        return self.get("/api/marcas", token=token)

    def listar_hilos(self, marca=None, token=None):
        params = {"marca": marca} if marca else None
        return self.get("/api/hilos", params=params, token=token)

    def obtener_resumen_almacen(self, token=None):
        return self.get("/api/almacen/resumen", token=token)

    def listar_movimientos_almacen(self, params=None, token=None):
        return self.get("/api/almacen/movimientos", params=params, token=token)

    def listar_movimientos_producto_almacen(self, producto_id, params=None, token=None):
        producto_url = quote(str(producto_id or ""), safe="")
        return self.get(
            f"/api/almacen/productos/{producto_url}/movimientos",
            params=params,
            token=token,
        )

    def obtener_movimiento_almacen(self, movimiento_id, token=None):
        movimiento_url = quote(str(movimiento_id or ""), safe="")
        return self.get(f"/api/almacen/movimientos/{movimiento_url}", token=token)

    def listar_precios(self, params=None, token=None):
        return self.get("/api/precios", params=params, token=token)

    def obtener_precios_marca(self, marca, token=None):
        marca_url = quote(str(marca or ""), safe="")
        return self.get(f"/api/precios/marca/{marca_url}", token=token)

    def obtener_precio_producto(self, marca=None, hilo=None, codigo=None, token=None):
        params = {}
        if marca:
            params["marca"] = marca
        if hilo:
            params["hilo"] = hilo
        if codigo:
            params["codigo"] = codigo
        return self.get("/api/precios/producto", params=params or None, token=token)

    def crear_producto_almacen(self, data, token=None):
        return self.post("/api/almacen/productos", data, token=token)

    def actualizar_producto_almacen(self, producto_id, data, token=None):
        return self.patch(f"/api/almacen/productos/{producto_id}", data, token=token)

    def actualizar_stock_producto_almacen(self, producto_id, data, token=None):
        return self.patch(f"/api/almacen/productos/{producto_id}/stock", data, token=token)

    def actualizar_tipo_producto_almacen(self, producto_id, data, token=None):
        return self.post(f"/api/almacen/productos/{producto_id}/tipo", data, token=token)

    def anular_producto_almacen(self, producto_id, data, token=None):
        return self.post(f"/api/almacen/productos/{producto_id}/anular", data, token=token)

    def actualizar_precio_marca_almacen(self, marca, data, token=None):
        marca_url = quote(str(marca or ""), safe="")
        return self.patch(f"/api/almacen/precios/marca/{marca_url}", data, token=token)

    def actualizar_precio_hilo_almacen(self, data, token=None):
        return self.patch("/api/almacen/precios/hilo", data, token=token)

    def actualizar_volumetrico_hilo_almacen(self, data, token=None):
        return self.patch("/api/almacen/volumetrico/hilo", data, token=token)

    def actualizar_volumetrico_multiple_almacen(self, data, token=None):
        return self.patch("/api/almacen/volumetrico/multiple", data, token=token)

    def listar_clientes(self, params=None, token=None):
        return self.get("/api/clientes", params=params, token=token)

    def crear_cliente(self, data, token=None):
        return self.post("/api/clientes", data, token=token)

    def actualizar_cliente(self, cliente_id, data, token=None):
        return self.patch(f"/api/clientes/{cliente_id}", data, token=token)

    def obtener_cliente(self, cliente_id, token=None):
        return self.get(f"/api/clientes/{cliente_id}", token=token)

    def buscar_clientes(self, params=None, token=None):
        return self.get("/api/clientes/buscar", params=params, token=token)

    def get_clientes_analytics_resumen(self, desde=None, hasta=None, q=None, segmento=None, token=None):
        params = _params_clientes_analytics(desde=desde, hasta=hasta, q=q, segmento=segmento)
        return self.get("/api/clientes/analytics/resumen", params=params or None, token=token)

    def get_clientes_analytics_ranking(
        self,
        desde=None,
        hasta=None,
        q=None,
        segmento=None,
        orden="total_comprado",
        limit=100,
        token=None,
    ):
        params = _params_clientes_analytics(desde=desde, hasta=hasta, q=q, segmento=segmento)
        params["orden"] = orden or "total_comprado"
        params["limit"] = limit or 100
        return self.get("/api/clientes/analytics/ranking", params=params, token=token)

    def get_cliente_analytics(self, cliente_id, token=None):
        return self.get(f"/api/clientes/{cliente_id}/analytics", token=token)

    def get_cliente_historial_compras(self, cliente_id, token=None):
        return self.get(f"/api/clientes/{cliente_id}/historial-compras", token=token)

    def get_clientes_analytics_graficas(self, desde=None, hasta=None, q=None, segmento=None, token=None):
        params = _params_clientes_analytics(desde=desde, hasta=hasta, q=q, segmento=segmento)
        return self.get("/api/clientes/analytics/graficas", params=params or None, token=token)

    def listar_notas(self, params=None, token=None):
        return self.get("/api/notas", params=params, token=token)

    def obtener_nota(self, nota_id, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.get(f"/api/notas/{nota_url}", token=token)

    def obtener_items_nota(self, nota_id, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.get(f"/api/notas/{nota_url}/items", token=token)

    def obtener_pagos_nota(self, nota_id, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.get(f"/api/notas/{nota_url}/pagos", token=token)

    def obtener_detalle_completo_nota(self, nota_id, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.get(f"/api/notas/{nota_url}/detalle-completo", token=token)

    def marcar_nota_pagada(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.patch(f"/api/notas/{nota_url}/pago", data, token=token)

    def convertir_nota_a_venta(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.post(f"/api/notas/{nota_url}/convertir-a-venta", data, token=token)

    def anular_nota(self, nota_id, data=None, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.post(f"/api/notas/{nota_url}/anular", data or {}, token=token)

    def guardar_comprobante_nota(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.post(f"/api/notas/{nota_url}/comprobante", data, token=token)

    def obtener_comprobante_nota(self, nota_id, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.get(f"/api/notas/{nota_url}/comprobante", token=token)

    def registrar_pago(self, data, token=None):
        return self.post("/api/pagos", data, token=token)

    def listar_pagos(self, params=None, token=None):
        return self.get("/api/pagos", params=params, token=token)

    def crear_nota(self, data, token=None):
        return self.post("/api/notas", data, token=token)

    def actualizar_nota(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.patch(f"/api/notas/{nota_url}", data, token=token)

    def actualizar_nota_admin(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.patch(f"/api/notas/{nota_url}/admin", data, token=token)

    def ajustar_items_nota_pagada_admin(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.post(f"/api/notas/{nota_url}/admin-ajustar-items", data, token=token)

    def actualizar_items_nota(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.patch(f"/api/notas/{nota_url}/items", data, token=token)

    def listar_pedidos(self, params=None, token=None):
        return self.get("/api/pedidos", params=params, token=token)

    def crear_pedido(self, data, token=None):
        return self.post("/api/pedidos", data, token=token)

    def obtener_pedido_activo(self, token=None):
        return self.get("/api/pedidos/activo", token=token)

    def activar_pedido(self, data, token=None):
        return self.post("/api/pedidos/activo", data, token=token)

    def limpiar_pedido_activo(self, token=None):
        return self.delete("/api/pedidos/activo", token=token)

    def listar_empacadores(self, params=None, token=None):
        return self.get("/api/empacadores", params=params, token=token)

    def listar_notas_asignacion_empacador(self, params=None, token=None):
        return self.get("/api/notas/asignacion-empacador", params=params, token=token)

    def asignar_notas_empacador(self, data, token=None):
        return self.post("/api/notas/asignar-empacador", data, token=token)

    def desasignar_notas_empacador(self, data, token=None):
        return self.post("/api/notas/desasignar-empacador", data, token=token)

    def listar_envios_notas(self, params=None, token=None):
        return self.get("/api/envios/notas", params=params, token=token)

    def actualizar_envio_nota(self, nota_id, data, token=None):
        nota_url = quote(str(nota_id or ""), safe="")
        return self.patch(f"/api/envios/notas/{nota_url}", data, token=token)

    def reporte_dashboard_empacadores(self, params=None, token=None):
        return self.get("/api/reportes/dashboard-empacadores", params=params, token=token)

    def reporte_errores_scan(self, params=None, token=None):
        return self.get("/api/reportes/errores-scan", params=params, token=token)

    def reporte_ranking_empacadores(self, params=None, token=None):
        return self.get("/api/reportes/ranking-empacadores", params=params, token=token)

    def reporte_dashboard_ventas(self, params=None, token=None):
        return self.get("/api/reportes/dashboard-ventas", params=params, token=token)

    def reporte_estadisticas_almacen(self, params=None, token=None):
        return self.get("/api/reportes/estadisticas-almacen", params=params, token=token)

    def _request(self, method, path, payload=None, token=None):
        if not self.base_url:
            raise RenderApiError("Falta HILORAMA_RENDER_API_BASE_URL.", path=path, base_url=self.base_url)

        data = None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                parsed = json.loads(body)
                detail = parsed.get("error") or parsed.get("mensaje")
            except Exception:
                detail = None
            raise RenderApiError(
                detail or "Solicitud rechazada",
                status=exc.code,
                path=path,
                base_url=self.base_url,
            ) from exc
        except urllib.error.URLError as exc:
            raise RenderApiError(
                "Backend no disponible.",
                path=path,
                base_url=self.base_url,
            ) from exc
        except Exception as exc:
            raise RenderApiError(
                f"No se pudo conectar con el backend: {exc}",
                path=path,
                base_url=self.base_url,
            ) from exc


def _params_clientes_analytics(desde=None, hasta=None, q=None, segmento=None):
    valores = {
        "desde": desde,
        "hasta": hasta,
        "q": q,
        "segmento": segmento,
    }
    return {
        clave: str(valor).strip()
        for clave, valor in valores.items()
        if valor not in (None, "") and str(valor).strip()
    }
