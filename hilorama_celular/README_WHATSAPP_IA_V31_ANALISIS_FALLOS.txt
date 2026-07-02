V31 - WhatsApp IA: corrección por reporte de tester masivo

Cambios aplicados a partir del CSV de fallos:

1. Respuestas más humanas y menos genéricas:
   - Pago sin comprobante ahora pide comprobante directamente.
   - Envío con CP y fallo de Envia conserva respuesta específica del CP.
   - Producto no manejado menciona opciones parecidas de forma natural.

2. Mejor entendimiento de pedidos/códigos:
   - Listas de códigos con contexto Velluto se agregan a lista/pedido.
   - Códigos cortos típicos de Komfy Mini (01, 06, 08, 14, 20, 99) se resuelven mejor.
   - Códigos típicos de Velluto se resuelven mejor si no hay contexto explícito.

3. Mejor manejo de colores:
   - Separé “blanco” y “hueso” para evitar confundir tonos.
   - Consultas como “Komfy Mini lila” o “Velluto blanco” responden disponibilidad.

4. Correcciones de pedido:
   - Mensajes como “quite el 60” ya se interpretan como corrección.
   - Responde “corrijo la cotización” en lugar de preguntar de qué hilo.

5. Tester masivo corregido:
   - El tester anterior marcaba falsos fallos porque “must_contain_any” exigía TODAS las palabras.
   - Ahora basta con que contenga al menos una de las palabras esperadas.
   - Se agregó tools/whatsapp_ia_mass_tester_v31.py.

Nota:
Esta versión sigue sin enviar automáticamente mensajes reales ni generar guías de Envia. El modo tester/dry_run se mantiene para no ensuciar la base real.
