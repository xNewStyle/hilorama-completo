V26 - WhatsApp IA entendimiento conversacional

Cambios:
- Entiende mensajes humanos por pausas: primero "quiero cotizar un pedido de Velluto" y después la lista.
- Interpreta "5 del 55 y 10 del 60" como 5 piezas del código 55 y 10 piezas del código 60.
- Ignora totales como "son 15 madejas" para no tomarlos como código 15.
- Mantiene la memoria de hilo para que el segundo mensaje use el contexto anterior.
- Agrega WA_MESSAGE_BUFFER_SECONDS para futura integración WhatsApp real.
- Silencia /favicon.ico para evitar 500 innecesarios en logs.

Variables opcionales:
WA_MESSAGE_BUFFER_SECONDS=35
WA_CONTEXT_STRONG_MINUTES=30
