import os
import unittest
from unittest.mock import patch

import impresion_etiquetas as etiquetas
import main_ventas


class _SocketFalso:
    def __init__(self, error_conexion=None, error_envio=None):
        self.error_conexion = error_conexion
        self.error_envio = error_envio
        self.timeout = None
        self.destino = None
        self.datos = None
        self.cerrado = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, destino):
        self.destino = destino
        if self.error_conexion:
            raise self.error_conexion

    def sendall(self, datos):
        if self.error_envio:
            raise self.error_envio
        self.datos = bytes(datos)

    def close(self):
        self.cerrado = True


class ImpresionEtiquetasTests(unittest.TestCase):
    def test_genera_etiqueta_ficticia_tspl_no_vacia(self):
        cliente = {
            "nombre": "CLIENTE FICTICIO",
            "telefono": "0000000000",
            "direccion": {
                "calle": "CALLE DE PRUEBA",
                "numero_ext": "1",
                "colonia": "PRUEBAS",
                "municipio": "PRUEBAS",
                "estado": "PRUEBAS",
                "codigo_postal": "00000",
            },
        }
        datos = etiquetas.etiqueta_destinatario(
            cliente,
            "PRUEBA-LOCAL",
            envio={"tipo": "PAQUETERIA FICTICIA"},
        )
        self.assertGreater(len(datos), 0)
        self.assertTrue(datos.startswith(b"SIZE "))
        self.assertTrue(datos.endswith(b"PRINT 1,1\n"))

    def test_envia_todos_los_bytes_y_cierra_conexion(self):
        socket_falso = _SocketFalso()
        with patch.object(etiquetas.socket, "socket", return_value=socket_falso):
            resultado = etiquetas.enviar_a_impresora(b"TSPL-FICTICIO")
        self.assertEqual(resultado.bytes_enviados, len(b"TSPL-FICTICIO"))
        self.assertTrue(resultado.sendall_completo)
        self.assertTrue(resultado.socket_cerrado)
        self.assertGreaterEqual(resultado.tiempo_conexion_ms, 0)
        self.assertGreaterEqual(resultado.tiempo_envio_ms, 0)
        self.assertEqual(socket_falso.datos, b"TSPL-FICTICIO")
        self.assertTrue(socket_falso.cerrado)

    def test_rechazo_de_conexion_es_error_controlado(self):
        socket_falso = _SocketFalso(error_conexion=ConnectionRefusedError(10061, "rechazada"))
        with patch.object(etiquetas.socket, "socket", return_value=socket_falso):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "rechazo la conexion") as error:
                etiquetas.enviar_a_impresora(b"TSPL-FICTICIO")
        self.assertEqual(error.exception.etapa, "conexion")
        self.assertEqual(error.exception.tipo, "conexion_rechazada")
        self.assertTrue(socket_falso.cerrado)

    def test_timeout_es_error_controlado(self):
        socket_falso = _SocketFalso(error_conexion=etiquetas.socket.timeout("timeout"))
        with patch.object(etiquetas.socket, "socket", return_value=socket_falso):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "no respondio a tiempo"):
                etiquetas.enviar_a_impresora(b"TSPL-FICTICIO")

    def test_error_de_red_es_controlado(self):
        socket_falso = _SocketFalso(error_conexion=OSError("sin red"))
        with patch.object(etiquetas.socket, "socket", return_value=socket_falso):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "No se pudo comunicar"):
                etiquetas.enviar_a_impresora(b"TSPL-FICTICIO")

    def test_conexion_perdida_durante_sendall_no_declara_exito(self):
        socket_falso = _SocketFalso(error_envio=BrokenPipeError("conexion perdida"))
        with patch.object(etiquetas.socket, "socket", return_value=socket_falso):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "se perdio durante el envio") as error:
                etiquetas.enviar_a_impresora(b"TSPL-FICTICIO")
        self.assertEqual(error.exception.etapa, "envio")
        self.assertEqual(error.exception.tipo, "conexion_perdida")
        self.assertTrue(socket_falso.cerrado)

    def test_rechaza_archivo_vacio_o_tipo_invalido(self):
        for valor in (b"", None, "texto"):
            with self.subTest(valor=valor):
                with self.assertRaises(etiquetas.ImpresionError):
                    etiquetas.enviar_a_impresora(valor)

    def test_configuracion_local_admite_override(self):
        variables = {
            "HILORAMA_PRINTER_IP": "127.0.0.1",
            "HILORAMA_PRINTER_PORT": "19100",
            "HILORAMA_PRINTER_TIMEOUT": "3",
        }
        with patch.dict(os.environ, variables, clear=False):
            self.assertEqual(etiquetas._configuracion_impresora(), ("127.0.0.1", 19100, 3.0))

    def test_ip_y_puerto_invalidos_se_rechazan_antes_de_conectar(self):
        with patch.dict(os.environ, {"HILORAMA_PRINTER_IP": "999.1.1.1"}, clear=False):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "IP configurada") as error:
                etiquetas.enviar_a_impresora(b"TSPL")
        self.assertEqual(error.exception.tipo, "ip_invalida")

        variables = {
            "HILORAMA_PRINTER_IP": "127.0.0.1",
            "HILORAMA_PRINTER_PORT": "70000",
        }
        with patch.dict(os.environ, variables, clear=False):
            with self.assertRaisesRegex(etiquetas.ImpresionError, "puerto configurado") as error:
                etiquetas.enviar_a_impresora(b"TSPL")
        self.assertEqual(error.exception.tipo, "puerto_invalido")

    def test_desktop_muestra_error_y_no_declara_exito(self):
        error = etiquetas.ImpresionError(
            "impresora no disponible",
            etapa="conexion",
            tipo="conexion_rechazada",
        )
        with patch.object(etiquetas, "enviar_a_impresora", side_effect=error):
            with patch.object(main_ventas.messagebox, "showerror") as mostrar:
                with patch("hilorama_desktop.utils.logger.log_error"):
                    resultado = main_ventas._enviar_etiqueta_segura(b"TSPL", "prueba")
        self.assertFalse(resultado)
        mostrar.assert_called_once()

    def test_dos_clics_rapidos_bloquean_el_segundo(self):
        main_ventas._impresion_lock.acquire()
        try:
            with patch.object(main_ventas.messagebox, "showwarning") as mostrar:
                with patch("hilorama_desktop.utils.logger.log_info"):
                    resultado = main_ventas._enviar_etiqueta_segura(b"TSPL", "prueba")
        finally:
            main_ventas._impresion_lock.release()
        self.assertFalse(resultado)
        mostrar.assert_called_once()

    def test_reintento_manual_funciona_despues_de_fallo_sin_reintento_automatico(self):
        error = etiquetas.ImpresionError(
            "impresora no disponible",
            etapa="conexion",
            tipo="conexion_rechazada",
        )
        exito = etiquetas.ResultadoImpresion(4, 1.0, 1.0, True, True)
        with patch.object(
            etiquetas,
            "enviar_a_impresora",
            side_effect=[error, exito],
        ) as enviar:
            with patch.object(main_ventas.messagebox, "showerror"):
                with patch("hilorama_desktop.utils.logger.log_error"):
                    with patch("hilorama_desktop.utils.logger.log_info"):
                        primero = main_ventas._enviar_etiqueta_segura(b"TSPL", "prueba")
                        segundo = main_ventas._enviar_etiqueta_segura(b"TSPL", "prueba")
        self.assertFalse(primero)
        self.assertTrue(segundo)
        self.assertEqual(enviar.call_count, 2)


if __name__ == "__main__":
    unittest.main()
