WhatsApp IA - Memoria de conversación V14
=========================================

Qué agrega
----------
- Guarda contexto por conversación/cliente:
  * marca_actual
  * hilo_actual
  * ultima_intencion
  * ultimo_codigo
  * ultimo_color
  * pedido_en_proceso
  * dudas_pendientes
- Si la clienta primero pregunta por Velluto y después escribe "rojo 56", el agente usa Velluto como contexto.
- Si en medio de la conversación dice "y de Komfy Mini?", la memoria cambia a Komfy Mini.
- Agrega botones en el simulador:
  * Ver memoria
  * Nueva conversación / limpiar memoria

Cómo probar
-----------
1) Deja Marca: Todas / Hilo: Todos.
2) Mensaje 1:
   Hola, ¿cuánto cuesta el Velluto?
3) Presiona Probar agente Hilorama.
4) Mensaje 2:
   rojo 56
5) Presiona Probar agente Hilorama otra vez.

Respuesta esperada:
- Debe entender que "rojo 56" sigue siendo Velluto.
- Debe preguntar cantidad o mostrar el tono, según la intención.

Otro caso:
1) Hola, me interesa Alize Velluto. ¿Qué colores tienen disponibles?
2) y el 429?

Debe entender que 429 es tono/código de Velluto.

Para iniciar otra prueba limpia:
- Presiona "Nueva conversación / limpiar memoria".
