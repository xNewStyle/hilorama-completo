README WHATSAPP IA V41 - TESTER DIFICIL HUMANO

Esta carpeta agrega un nuevo tester V41 con 150 conversaciones nuevas y más difíciles.
No reemplaza al V40 estable: lo usa como base y agrega pruebas más pesadas.

OBJETIVO
- Probar saludos cortos donde la persona todavía va a escribir más.
- Evitar que 'Hola', 'Buenos días', 'Oye una pregunta' o 'mira' se coticen como producto.
- Probar listas raras de WhatsApp.
- Probar mala escritura: belluto, veluto, cotiisar, sinco, trez.
- Probar pedidos con distintos hilos en el mismo mensaje.
- Probar accesorios mezclados con hilos: relleno, ojos de seguridad, ganchos 4.5 mm.
- Probar quitar, agregar, corregir y no duplicar productos.
- Probar pagos, comprobantes, apartados, descuentos y envíos sin que la IA prometa de más.

ARCHIVOS NUEVOS
- tools/whatsapp_ia_human_tester_v41.py
- tools/casos_tester_v41_dificiles_hilorama.json
- tools/casos_tester_v41_dificiles_hilorama.csv

COMO PROBAR LOCAL
Desde tu carpeta del proyecto:

python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url http://127.0.0.1:5000 --pin TU_PIN --limit 30 --sleep 0.2

Luego sube dificultad:

python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url http://127.0.0.1:5000 --pin TU_PIN --limit 80 --sleep 0.2
python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url http://127.0.0.1:5000 --pin TU_PIN --limit 120 --sleep 0.2
python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url http://127.0.0.1:5000 --pin TU_PIN --limit 150 --sleep 0.2

COMO PROBAR EN RENDER

python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 30 --sleep 0.3

Si sale bien:

python hilorama_celular/tools/whatsapp_ia_human_tester_v41.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 150 --sleep 0.3

DONDE QUEDAN LOS REPORTES
En:

wa_tester_reports

Abre la carpeta:

explorer .\wa_tester_reports

IMPORTANTE SOBRE SALUDOS
El tester V41 incluye casos donde el cliente solo dice 'Hola', 'Buenos días', 'Oye una pregunta', 'mira', etc.
La IA no debe cotizar ni inventar productos en esos mensajes. Debe responder humano y permitir que el cliente siga escribiendo.
En la integración real de WhatsApp, lo ideal es esperar/bufferear varios segundos antes de responder cuando el mensaje sea solo saludo o incompleto.

SI FALLA MUCHO
No pasa nada. Este tester está hecho para romper la IA y encontrar errores finos.
Primero corrige las categorías más graves:
1. saludo_puro_debe_esperar
2. pedido_mala_escritura_cantidades_palabras
3. lista_extrana_whatsapp
4. accesorios_mm_bolsa_no_codigo_hilo
5. correcciones_quitar_poner_no_duplicar
