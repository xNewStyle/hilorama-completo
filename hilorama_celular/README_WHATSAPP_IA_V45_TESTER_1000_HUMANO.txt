README WHATSAPP IA V45 - TESTER HUMANO 1000

Esta version NO corrige la IA.
Agrega un tester nuevo con 1000 conversaciones humanas para encontrar fallos que no salen en los 150 casos anteriores.

Archivos nuevos:
- tools/whatsapp_ia_human_tester_v45.py
- tools/casos_tester_v45_dificiles_hilorama.json
- tools/casos_tester_v45_dificiles_hilorama.csv

Incluye pruebas de:
- manejas velluto? -> 429
- quieres pedido de velluto -> 429
- codigo suelto con contexto
- foto/tono antes de pedir sin agregar producto fantasma
- precio/stock sin convertir a pedido
- listas raras y numeros partidos
- mala escritura: kiero, sinco, trez, belluto, vellutto
- correcciones: quita, cambia, deja solo, mejor que sean
- hilos mixtos y accesorios en el mismo mensaje
- ojos de seguridad, nariz flock, ganchos 4.5/5, relleno
- pago, comprobante, envio, descuento y apartado
- numeros ambiguos: CP, dinero, telefono, mm, fechas

Comandos recomendados:

Primero 50:
python hilorama_celular/tools/whatsapp_ia_human_tester_v45.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.3

Luego 200:
python hilorama_celular/tools/whatsapp_ia_human_tester_v45.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 200 --sleep 0.3

Luego 500:
python hilorama_celular/tools/whatsapp_ia_human_tester_v45.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 500 --sleep 0.3

Finalmente 1000:
python hilorama_celular/tools/whatsapp_ia_human_tester_v45.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.3

Notas:
- Usa tester_mode=true y dry_run=true.
- No debe crear notas reales.
- El HTML muestra maximo 500 fallos, pero el CSV/JSON guarda todo.
- Si sale 10061 es porque el servidor local no esta prendido o el base-url esta mal.
