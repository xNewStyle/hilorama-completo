WhatsApp IA - Cerebro comercial Hilorama V3

Cambios principales:

1. El agente ya no depende de seleccionar marca/hilo manualmente.
   Detecta hilos y marcas desde el texto usando el almacén real.

2. Maneja consultas de catálogo reales:
   - "Me interesa Alize Velluto, qué colores tienen disponibles"
   - "Y de Komfy Mini?"
   - "Maneja Karina?"
   - "Maneja La Abuelita?"

3. Responde más humano y no como parser técnico.
   Evita frases como "producto exacto no lo veo" cuando sí hay contexto claro.

4. Usa el almacén como fuente de verdad:
   - Si el hilo existe, lo reconoce.
   - Si el código existe, lo agrega directo.
   - Si el tono es ambiguo, sugiere opciones reales del almacén.

5. Mejora listas largas:
   - Separa "y 3 negros", "y un rojo", etc.
   - Mantiene contexto por hilo en líneas como "40 de Komfy Mini".
   - Respeta cancelaciones tipo "pensándolo mejor quítame el Komfy".

6. Consultas de envío/pago:
   - Si preguntan por envíos, pide CP.
   - Si mandan comprobante, pide imagen y confirma revisión.

7. Para productos que no manejas, sugiere similares por textura sin inventar.
   Ejemplo: La Abuelita -> sugiere Kurumi o Komfy Mini según proyecto.

Notas:
- La búsqueda en línea real todavía no está conectada. Esta versión usa diccionario interno + almacén.
- Para conectar búsqueda web real después habría que agregar una API externa de búsqueda o un catálogo de equivalencias propio.
