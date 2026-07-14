"""Pruebas puras para la deteccion de la campana de notificaciones."""

from datetime import datetime, timedelta
import unittest

from hilorama_backend.services.notificaciones_service import (
    construir_notificaciones_operacion,
    construir_oportunidades_venta,
    construir_resumen_notificaciones,
)


AHORA = datetime(2026, 7, 13, 12, 0, 0)


def _nota(nota_id, estado, horas=1, **extra):
    nota = {
        "id": nota_id,
        "estado": estado,
        "cliente_id": extra.pop("cliente_id", 10),
        "cliente_nombre": extra.pop("cliente_nombre", "María López"),
        "fecha": AHORA - timedelta(hours=horas),
        "fecha_pago": AHORA - timedelta(hours=horas) if estado == "PAGADA" else None,
        "fecha_asignacion": AHORA - timedelta(hours=horas),
        "fecha_finalizacion": AHORA - timedelta(hours=horas) if estado == "COMPLETA" else None,
        "piezas_totales": 10,
        "piezas_empacadas": 0,
        "envio": {"tipo": "PAQUETERIA"},
    }
    nota.update(extra)
    return nota


def _metrica(cliente_id, segmento="ACTIVA", proxima="2026-07-16", **extra):
    metrica = {
        "cliente_id": cliente_id,
        "nombre": f"Clienta {cliente_id}",
        "telefono": f"555000{cliente_id:04d}",
        "segmento": segmento,
        "ultima_compra": "2026-06-26",
        "dias_desde_ultima_compra": 17,
        "frecuencia_promedio_dias": 20,
        "proxima_compra_estimada": proxima,
        "numero_compras": 4,
        "ticket_promedio": 700,
        "total_comprado": 2800,
    }
    metrica.update(extra)
    return metrica


class NotificacionesOperacionTests(unittest.TestCase):
    def test_estados_operativos_generan_categorias_correctas(self):
        notas = [
            _nota("VP-1", "VENTA_PENDIENTE", 25),
            _nota("COT-1", "COTIZACION", 30),
            _nota("PAG-1", "PAGADA", 10),
            _nota("PROC-1", "EN_PROCESO", 3, piezas_empacadas=2),
            _nota("INC-1", "INCOMPLETA", 5, piezas_empacadas=6),
            _nota("COMP-1", "COMPLETA", 5),
            _nota("GUIA-1", "COMPLETA", 13, guia="ABC123"),
            _nota("ENV-1", "ENVIADO", 20, guia="XYZ"),
            _nota("ANU-1", "ANULADA", 20),
            _nota("ARCH-1", "ARCHIVADA", 20),
        ]
        avisos = construir_notificaciones_operacion(notas, ahora=AHORA)
        categorias_por_nota = {}
        for aviso in avisos:
            categorias_por_nota.setdefault(aviso.get("nota_id"), set()).add(aviso["categoria"])

        self.assertIn("PENDIENTE_PAGO", categorias_por_nota["VP-1"])
        self.assertEqual(next(a for a in avisos if a["key"] == "pendiente_pago:VP-1")["prioridad"], "URGENTE")
        self.assertNotIn("COT-1", categorias_por_nota)
        self.assertIn("PAGADA_SIN_EMPAQUETAR", categorias_por_nota["PAG-1"])
        self.assertIn("EMPAQUE_INCOMPLETO", categorias_por_nota["PROC-1"])
        self.assertIn("EMPAQUE_INCOMPLETO", categorias_por_nota["INC-1"])
        self.assertIn("COMPLETA_SIN_GUIA", categorias_por_nota["COMP-1"])
        self.assertIn("GUIA_SIN_ENVIO", categorias_por_nota["GUIA-1"])
        self.assertNotIn("ENV-1", categorias_por_nota)
        self.assertNotIn("ANU-1", categorias_por_nota)
        self.assertNotIn("ARCH-1", categorias_por_nota)

    def test_recoleccion_local_no_exige_guia(self):
        nota = _nota("LOCAL-1", "COMPLETA", 10, envio={"tipo": "RECOLECCION LOCAL"})
        avisos = construir_notificaciones_operacion([nota], ahora=AHORA)
        self.assertFalse(any(a["categoria"] == "COMPLETA_SIN_GUIA" for a in avisos))

    def test_impresion_stock_y_error_scan_reutilizan_estado_existente(self):
        impresiones = [
            {"id": 1, "nota_id": "N-1", "estado": "PENDIENTE", "estado_nota": "COMPLETA", "creado_en": AHORA},
            {"id": 2, "nota_id": "N-2", "estado": "IMPRESO", "estado_nota": "COMPLETA", "creado_en": AHORA},
        ]
        errores = [
            {"id": 3, "nota_id": "N-3", "estado_nota": "INCOMPLETA", "codigo": "429", "fecha": AHORA},
            {"id": 4, "nota_id": "N-4", "estado_nota": "ENVIADO", "codigo": "430", "fecha": AHORA},
        ]
        productos = [
            {"id": 7, "estado": "RESURTIR", "stock": 4, "codigo": "429", "marca": "Velluto"},
            {"id": 8, "estado": "OK", "stock": 80, "codigo": "500", "marca": "Velluto"},
        ]
        avisos = construir_notificaciones_operacion([], impresiones, errores, productos, ahora=AHORA)
        keys = {aviso["key"] for aviso in avisos}
        self.assertIn("impresion:1", keys)
        self.assertNotIn("impresion:2", keys)
        self.assertIn("error_scan:3", keys)
        self.assertNotIn("error_scan:4", keys)
        self.assertIn("inventario_bajo:7", keys)
        self.assertNotIn("inventario_bajo:8", keys)

    def test_inconsistencias_confiables_se_reportan_sin_corregir(self):
        pagada = _nota("PAG-SF", "PAGADA", 3, fecha_pago=None)
        completa = _nota("COMP-SF", "COMPLETA", 3, fecha_finalizacion=None, piezas_empacadas=4)
        avisos = construir_notificaciones_operacion([pagada, completa], ahora=AHORA)
        keys = {aviso["key"] for aviso in avisos}
        self.assertIn("inconsistencia:pagada_sin_fecha:PAG-SF", keys)
        self.assertIn("inconsistencia:completa_sin_fecha:COMP-SF", keys)
        self.assertIn("inconsistencia:completa_con_piezas_pendientes:COMP-SF", keys)

    def test_resolver_estado_elimina_aviso_y_la_llave_es_estable(self):
        nota = _nota("ESTABLE-1", "VENTA_PENDIENTE", 15)
        primera = construir_notificaciones_operacion([nota], ahora=AHORA)
        segunda = construir_notificaciones_operacion([nota], ahora=AHORA + timedelta(minutes=2))
        self.assertEqual(primera[0]["key"], segunda[0]["key"])
        nota["estado"] = "ENVIADO"
        nota["guia"] = "G-1"
        resuelta = construir_notificaciones_operacion([nota], ahora=AHORA)
        self.assertFalse(any(a["key"] == "pendiente_pago:ESTABLE-1" for a in resuelta))


class NotificacionesOportunidadesTests(unittest.TestCase):
    def test_proxima_atrasada_dormida_vip_y_recurrente(self):
        metricas = [
            _metrica(1, "ACTIVA", "2026-07-16"),
            _metrica(2, "ACTIVA", "2026-07-09"),
            _metrica(3, "DORMIDA", None, dias_desde_ultima_compra=90),
            _metrica(4, "VIP", "2026-07-25"),
            _metrica(5, "VIP", "2026-07-12"),
            _metrica(6, "FRECUENTE", "2026-07-10"),
        ]
        avisos = construir_oportunidades_venta(metricas, ahora=AHORA)
        categorias = {aviso["cliente_id"]: aviso["categoria"] for aviso in avisos}
        self.assertEqual(categorias[1], "PROXIMA_COMPRA")
        self.assertEqual(categorias[2], "ATRASADA")
        self.assertEqual(categorias[3], "DORMIDA")
        self.assertNotIn(4, categorias)
        self.assertEqual(categorias[5], "VIP_RECUPERAR")
        self.assertEqual(categorias[6], "RECURRENTE_ATRASADA")
        self.assertTrue(all(aviso["prioridad"] != "URGENTE" for aviso in avisos))

    def test_exclusiones_y_controles_temporales(self):
        sin_telefono = _metrica(10, telefono="")
        pendiente = _metrica(11)
        inactiva = _metrica(12)
        pospuesta = _metrica(13)
        avisos = construir_oportunidades_venta(
            [sin_telefono, pendiente, inactiva, pospuesta],
            clientes=[{"id": 12, "activo": False}],
            cliente_ids_con_pendiente=[11],
            controles=[{
                "cliente_id": 13,
                "categoria": "PROXIMA_COMPRA",
                "pospuesto_hasta": AHORA + timedelta(days=3),
            }],
            ahora=AHORA,
        )
        self.assertEqual(avisos, [])

    def test_ocultamiento_30_dias_excluye_hasta_su_vencimiento(self):
        metrica = _metrica(14)
        ocultada = construir_oportunidades_venta(
            [metrica],
            controles=[{
                "cliente_id": 14,
                "categoria": "PROXIMA_COMPRA",
                "oculto_hasta": AHORA + timedelta(days=30),
            }],
            ahora=AHORA,
        )
        visible = construir_oportunidades_venta(
            [metrica],
            controles=[{
                "cliente_id": 14,
                "categoria": "PROXIMA_COMPRA",
                "oculto_hasta": AHORA - timedelta(seconds=1),
            }],
            ahora=AHORA,
        )
        self.assertEqual(ocultada, [])
        self.assertEqual(len(visible), 1)

    def test_compra_posterior_invalida_control_temporal_anterior(self):
        metrica = _metrica(14, ultima_compra="2026-07-13")
        avisos = construir_oportunidades_venta(
            [metrica],
            controles=[{
                "cliente_id": 14,
                "categoria": "PROXIMA_COMPRA",
                "pospuesto_hasta": AHORA + timedelta(days=3),
                "fecha_accion": AHORA - timedelta(days=1),
            }],
            ahora=AHORA,
        )
        self.assertEqual(len(avisos), 1)

    def test_vip_atrasada_genera_oportunidad_concreta_y_cliente_id(self):
        avisos = construir_oportunidades_venta([
            _metrica(15, "VIP", "2026-05-01", dias_desde_ultima_compra=73),
        ], ahora=AHORA)
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]["categoria"], "VIP_RECUPERAR")
        self.assertEqual(avisos[0]["cliente_id"], 15)
        self.assertEqual(avisos[0]["destino_id"], 15)

    def test_cliente_que_acaba_de_comprar_no_es_oportunidad(self):
        metrica = _metrica(
            16,
            "ACTIVA",
            "2026-08-10",
            ultima_compra="2026-07-13",
            dias_desde_ultima_compra=0,
        )
        self.assertEqual(construir_oportunidades_venta([metrica], ahora=AHORA), [])

    def test_un_cliente_solo_genera_una_tarjeta_agrupada(self):
        metrica = _metrica(20, "DORMIDA", "2026-06-01", dias_desde_ultima_compra=80)
        avisos = construir_oportunidades_venta([metrica, dict(metrica)], ahora=AHORA)
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]["cliente_id"], 20)
        self.assertIn("mensaje_sugerido", avisos[0]["metadata"])

    def test_resumen_coincide_con_elementos(self):
        operacion = construir_notificaciones_operacion([_nota("VP", "VENTA_PENDIENTE", 30)], ahora=AHORA)
        oportunidades = construir_oportunidades_venta([_metrica(30)], ahora=AHORA)
        resumen = construir_resumen_notificaciones(operacion, oportunidades, ahora=AHORA)
        self.assertEqual(resumen["total"], len(operacion) + len(oportunidades))
        self.assertEqual(resumen["operacion"]["total"], len(operacion))
        self.assertEqual(resumen["oportunidades"]["total"], len(oportunidades))


if __name__ == "__main__":
    unittest.main()
