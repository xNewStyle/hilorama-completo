# Hilorama - WhatsApp IA / Simulador inicial

Esta versión agrega el primer paso del agente de ventas para WhatsApp sin depender todavía de Meta Cloud API.

Qué incluye:

1. Nueva sección dentro de Crear > IA / WhatsApp:
   - "Simulador WhatsApp IA real".
   - Pega un mensaje real de clienta y presiona "Probar agente Hilorama".
   - El sistema usa el parser real + OpenAI para generar respuesta sugerida.
   - No envía nada a WhatsApp todavía; solo copia la respuesta y agrega productos al carrito.

2. Nuevo endpoint:
   - POST /api/whatsapp-ia/simular
   - Reutiliza /api/parser-whatsapp internamente para que el simulador y WhatsApp real usen el mismo cerebro.

3. Nuevas tablas preparadas para la siguiente fase:
   - whatsapp_conversaciones
   - whatsapp_mensajes

4. Variables opcionales:
   - OPENAI_SALES_MODEL=gpt-4o-mini
   - OPENAI_TIMEOUT_SECONDS=90

Flujo recomendado:

1. Abrir Crear > IA / WhatsApp.
2. Seleccionar marca/hilo de contexto, por ejemplo KARINA / VELLUTO.
3. Pegar mensaje real de clienta.
4. Presionar "Probar agente Hilorama".
5. Revisar respuesta sugerida y productos detectados.
6. Copiar respuesta o agregar productos al carrito.
7. Cuando Meta libere la cuenta, conectamos Cloud API al mismo endpoint/motor, sin rehacer el agente.

