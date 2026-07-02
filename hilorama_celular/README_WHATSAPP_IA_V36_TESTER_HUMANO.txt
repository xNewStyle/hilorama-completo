Hilorama WhatsApp IA - V36 Tester conversacional humano

Esta versión NO cambia todavía el motor de la IA.
Agrega un tester más difícil y humano para encontrar fallos nuevos.

Archivo agregado:
- hilorama_celular/tools/whatsapp_ia_human_tester_v36.py

Qué prueba:
- Conversaciones completas de varios mensajes.
- Mensajes cortados como WhatsApp real.
- Faltas de ortografía: belluto, komfi, pwdido, cotisar, buenas trades.
- Preguntas de catálogo: qué más manejan, qué marcas tienen, qué hilos tienen.
- Preguntas de accesorios: agujas, ganchos, crochet, ojos de seguridad, marcadores.
- Pedidos mixtos y seguimiento.
- Envío después del pedido.
- Pago y comprobante.
- Descuentos que NO debe aprobar sola la IA.
- Correcciones largas: quitar, cambiar cantidades, agregar otro producto.

Se basa en tu almacén actual porque intenta leer:
- /api/catalogo/marcas
- /api/catalogo/hilos
- /api/productos?limit=300

Reportes que genera:
- wa_human_test_report_v36_*.html
- wa_human_test_failures_v36_*.csv
- wa_human_test_conversaciones_v36_*.csv
- wa_human_test_results_v36_*.json

El archivo más cómodo para revisar qué preguntó y qué respondió es:
- wa_human_test_conversaciones_v36_*.csv

Comando recomendado primero:

cd "C:\Users\jorge\OneDrive\Escritorio\Hilorama\hilorama_celular"
python tools\whatsapp_ia_human_tester_v36.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.2

Si sale bien:

python tools\whatsapp_ia_human_tester_v36.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.2

Después:

python tools\whatsapp_ia_human_tester_v36.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 200 --sleep 0.2

No empieces directo con 1000 porque este tester manda varios mensajes por conversación.
Ejemplo: 200 conversaciones pueden convertirse en más de 600 mensajes al endpoint.

Si salen fallos, mandar:
- wa_human_test_failures_v36_*.csv
- y si quieres que vea todas las conversaciones, wa_human_test_conversaciones_v36_*.csv

Notas:
- Usa tester_mode=true y dry_run=true.
- No debe guardar conversaciones falsas.
- No debe generar notas reales.
- No debe crear decisiones pendientes reales.
- Si el servidor no regresa tester_mode=true, el script se detiene.
