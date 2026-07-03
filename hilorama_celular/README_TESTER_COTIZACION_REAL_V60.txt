V60 - Tester de cotizaciones reales largas + envío volumétrico

Este tester genera conversaciones humanas pesadas para WhatsApp IA:

- Usa productos reales del almacén desde /api/productos.
- Genera cotizaciones largas de 20 a 80 renglones.
- Incluye listas tipo WhatsApp en varios mensajes.
- Mezcla Velluto, Komfy, otros hilos y accesorios si existen en inventario.
- Pide envío con código postal al final de la conversación.
- Revisa que la IA use el pedido acumulado, no solo el último mensaje.
- Revisa /api/envios/debug-volumetrico para validar el tramo de envío.
- Incluye reglas críticas:
  * 35 Vellutos deben caer en tramo de 5 kg volumétricos.
  * Más de 35 Vellutos debe subir a 10 kg volumétricos.
  * Hasta 105 Vellutos debe poder quedar dentro de 15 kg si la tabla lo permite.
  * Más de 15 kg volumétricos debe mandar a revisión manual.
  * 34 Vellutos + 2 Komfy Mini debe seguir en tramo de 5 kg si está bien configurado.

Uso recomendado:

1) Prueba corta:
python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 10 --sleep 0.3

2) Prueba media:
python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.3

3) Prueba completa:
python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.3

Si quieres que todas las listas sean todavía más largas:
python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --lineas-min 50 --lineas-max 80 --sleep 0.3

Reportes:
wa_tester_reports/wa_quote_real_test_report_v60_*.html
wa_tester_reports/wa_quote_real_test_failures_v60_*.csv
wa_tester_reports/wa_quote_real_test_conversaciones_v60_*.csv
wa_tester_reports/wa_quote_real_test_results_v60_*.json

Importante:
- No compartas el PIN en capturas.
- El tester usa tester_mode=true y dry_run=true.
- Si el sitio no regresa tester_mode=true, se detiene.
