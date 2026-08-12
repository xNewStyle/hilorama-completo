import unittest
from datetime import date, timedelta

from hilorama_backend.app import _cerrar_sesiones_previas_login, _cliente_permitido


class _ConexionGrabadora:
    def __init__(self):
        self.consultas = []

    def execute(self, consulta, parametros=None):
        self.consultas.append((" ".join(consulta.split()), parametros))
        return self


class AuthAccesoTest(unittest.TestCase):
    def test_super_admin_no_queda_fuera_por_fecha_vencida(self):
        permitido, estado, _mensaje = _cliente_permitido({
            "rol": "super_admin",
            "cliente_estado": "activo",
            "fecha_vencimiento": date.today() - timedelta(days=1),
        })
        self.assertTrue(permitido)
        self.assertEqual(estado, "activo")

    def test_super_admin_puede_administrar_cliente_marcado_vencido(self):
        permitido, estado, _mensaje = _cliente_permitido({
            "rol": "super_admin",
            "cliente_estado": "vencido",
            "fecha_vencimiento": date.today() - timedelta(days=1),
        })
        self.assertTrue(permitido)
        self.assertEqual(estado, "activo")

    def test_super_admin_respeta_bloqueo_explicito(self):
        for cliente_estado in ("suspendido", "bloqueado", "bloqueado_permanente"):
            with self.subTest(cliente_estado=cliente_estado):
                permitido, estado, _mensaje = _cliente_permitido({
                    "rol": "super_admin",
                    "cliente_estado": cliente_estado,
                })
                self.assertFalse(permitido)
                self.assertEqual(estado, cliente_estado)

    def test_usuario_normal_sigue_bloqueado_por_vencimiento(self):
        permitido, estado, mensaje = _cliente_permitido({
            "rol": "vendedor",
            "cliente_estado": "activo",
            "fecha_vencimiento": date.today() - timedelta(days=1),
        })
        self.assertFalse(permitido)
        self.assertEqual(estado, "vencido")
        self.assertEqual(mensaje, "Licencia vencida.")

    def test_nuevo_login_cierra_sesiones_viejas_y_la_previa_del_mismo_equipo(self):
        conn = _ConexionGrabadora()
        _cerrar_sesiones_previas_login(conn, 10, 20, "hash-equipo", 8)

        self.assertEqual(len(conn.consultas), 2)
        consulta_vencidas, parametros_vencidas = conn.consultas[0]
        consulta_equipo, parametros_equipo = conn.consultas[1]
        self.assertIn("created_at < NOW()", consulta_vencidas)
        self.assertEqual(parametros_vencidas, (10, 8))
        self.assertIn("usuario_id=%s", consulta_equipo)
        self.assertIn("device_id_hash=%s", consulta_equipo)
        self.assertEqual(parametros_equipo, (20, "hash-equipo"))


if __name__ == "__main__":
    unittest.main()
