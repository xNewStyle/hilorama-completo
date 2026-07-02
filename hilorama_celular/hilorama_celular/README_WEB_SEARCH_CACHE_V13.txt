WhatsApp IA V13 - Búsqueda en internet + copia en Biblioteca IA

Qué hace:
- Cuando el agente no encuentra una respuesta segura en almacén ni Biblioteca IA, puede consultar internet.
- La respuesta encontrada se guarda automáticamente en ia_recursos con categoría internet_cache.
- La siguiente vez que pregunten algo parecido, usa la copia guardada antes de volver a buscar.

Seguridad:
- NO usa internet para precios, stock, pagos, comprobantes, datos del cliente ni costos de envío internos.
- Esas respuestas deben salir del almacén, reglas o Biblioteca IA.
- Internet se usa para dudas generales o productos externos: qué es un material, para qué sirve, alternativas, texturas, equivalencias, etc.

Variables opcionales en Render:
OPENAI_WEB_SEARCH_ENABLED=1
OPENAI_WEB_MODEL=gpt-4o-mini

Endpoint manual opcional:
POST /api/whatsapp-ia/buscar-internet
Body: {"texto":"¿Qué es estambre La Abuelita?"}

Cache:
GET /api/ia/web-cache

Recomendación:
Revisa periódicamente los recursos categoría internet_cache desde Biblioteca IA y corrige textos que quieras dejar como respuesta oficial.
