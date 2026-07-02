V46 - Corrección de contexto humano y tester largo realista

Corrige fallos V45 donde:
- Después de “manejas Velluto?”, un código suelto como 429 ya se interpreta con el contexto de Velluto.
- “qué color es el 429”, “me dices del 429”, “stock del 429”, “el 429 cuánto sale” ya no se convierten en pedidos falsos.
- “tendrás Velluto” y “manejaz Velluto” ya se tratan como consulta de existencia, no como producto inventado.
- “ponme dos 429” y “el 429 dos” se interpretan como Velluto 429 x2 cuando ya hay intención de pedido.
- “cinco del negro y dos del blanco de Velluto” agrega Negro x5 y Blanco x2.

Incluye tester V46 con 1000 conversaciones largas y más humanas.

Comando sugerido:
python hilorama_celular/tools/whatsapp_ia_human_tester_v46.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.3
