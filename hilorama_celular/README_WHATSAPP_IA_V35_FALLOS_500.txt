# WhatsApp IA V35 - corrección de fallos del tester 500 casos

Resultado analizado: 500 casos, 494 aprobados, 6 fallos.

Correcciones aplicadas:

1. Camel en Velluto
   - Antes: la consulta "¿Tiene Belluto camel?" podía responder Arena 530.
   - Ahora: camel se trata como color exacto y se prioriza Velluto 429 Camel si existe en almacén.

2. Pedidos de Komfy Mini sin stock
   - Antes: si todos los tonos de un pedido estaban sin stock, respondía solo líneas de agotado y el tester lo marcaba como respuesta incompleta.
   - Ahora: agrega una introducción humana: "Le revisé su pedido para cotización 😊" y después muestra los tonos no disponibles.

3. Tester V35
   - Se agrega tools/whatsapp_ia_mass_tester_v35.py para repetir pruebas grandes sin tocar memoria real.

No se cambió la regla de no usar apartados.
No se habilita envío automático real.
