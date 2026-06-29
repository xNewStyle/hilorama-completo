WhatsApp IA V15 - Cierre amable diferido

Qué agrega:
- Si la clienta solo dice "gracias", "muchas gracias", "muy amable", etc., el agente NO responde inmediatamente.
- Programa un mensaje de cierre para 5 minutos después.
- Si la clienta escribe algo más antes de los 5 minutos, se cancela el cierre y se procesa el nuevo mensaje normal.
- Si el mensaje trae pedido o seguimiento, por ejemplo "gracias, me surte 3 blancos", no se considera cierre: se procesa como pedido.

Mensaje predeterminado:
A sus órdenes 😊 cualquier cosa no dude en escribirme, con gusto le atiendo.

Variables opcionales en Render:
WA_CIERRE_GRACIAS_MINUTOS=5
WA_CIERRE_GRACIAS_TEXTO=A sus órdenes 😊 cualquier cosa no dude en escribirme, con gusto le atiendo.

Endpoints nuevos:
GET /api/whatsapp-ia/cierres-pendientes
POST /api/whatsapp-ia/cierre-marcar-enviado

Cuando conectemos WhatsApp Cloud API, esos cierres pendientes se podrán enviar automáticamente con una tarea programada o al revisar la cola de mensajes.
