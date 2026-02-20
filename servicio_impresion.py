# servicio_impresion.py

import time
import requests
from impresion_etiquetas import etiqueta_destinatario, etiqueta_remitente

API_URL = "https://hilorama-completo.onrender.com"
PRINT_KEY = "MI_CLAVE_DE_IMPRESION_LOCAL"


def obtener_datos_nota(nota_id):
    try:
        res = requests.get(
            f"{API_URL}/notas/{nota_id}/datos-impresion",
            timeout=10
        )
        if res.status_code != 200:
            print(f"Error obteniendo datos nota {nota_id}")
            return None
        return res.json()
    except Exception as e:
        print("Error datos nota:", e)
        return None


def procesar_cola():
    print("🖨 Servicio de impresión iniciado...")
    
    while True:
        try:
            res = requests.get(
                f"{API_URL}/cola-impresion",
                headers={"X-PRINT-KEY": PRINT_KEY},
                timeout=10
            )

            if res.status_code != 200:
                print("Error consultando cola:", res.text)
                time.sleep(5)
                continue

            tareas = res.json()

            if not tareas:
                time.sleep(3)
                continue

            for tarea in tareas:
                nota_id = tarea["nota_id"]
                tipo = tarea["tipo"]

                print(f"📦 Procesando nota {nota_id} - {tipo}")

                datos = obtener_datos_nota(nota_id)
                if not datos:
                    continue

                cliente = datos["cliente"]
                envio = datos.get("envio")
                mis_datos = datos.get("remitente")

                try:
                    if tipo == "destinatario":
                        etiqueta_destinatario(cliente, nota_id, envio)

                    elif tipo == "remitente":
                        etiqueta_remitente(nota_id, mis_datos)

                    elif tipo == "ambas":
                        etiqueta_remitente(nota_id, mis_datos)
                        etiqueta_destinatario(cliente, nota_id, envio)

                    # marcar como impresa
                    requests.post(
                        f"{API_URL}/cola-impresion/{tarea['id']}/completar",
                        headers={"X-PRINT-KEY": PRINT_KEY},
                        timeout=10
                    )

                    print(f"✅ Nota {nota_id} impresa correctamente")

                except Exception as e:
                    print(f"❌ Error imprimiendo nota {nota_id}:", e)

        except Exception as e:
            print("Error general servicio:", e)

        time.sleep(3)


if __name__ == "__main__":
    procesar_cola()