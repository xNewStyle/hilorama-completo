V28 - WhatsApp IA respuestas humanas y tester

Qué corrige:
- ¿Manejan Komfy Mini? ya responde como vendedor: sí manejamos y ofrece gama o tono.
- ¿Tienen Velluto blanco? ya consulta almacén y responde disponibilidad real.
- Mensajes como "me aparta 2 del 429, 3 del 532 y 1 del 56" respetan memoria de Velluto y no preguntan por otros hilos si el contexto está claro.
- Limpia mejor frases humanas: "tienen", "manejan", "busco", "necesito", etc., para quedarse con el color real.
- Preguntas internas o técnicas ya se convierten a frases más humanas y empáticas.
- Cuando una lista trae productos válidos y dudas, muestra lo que sí entendió y pide confirmar solo lo faltante.
- Mejora búsqueda de color explícito: blanco, rojo, hueso, azul cielo, etc.
- Evita tomar "blanco que no se vea tan amarillo" como amarillo/canario.

Qué sigue faltando para que quede todavía mejor:
- Un historial real por conversación con buffer automático al conectar WhatsApp Cloud API.
- Más alias de colores reales por hilo usando tu almacén completo.
- Un catálogo de sinónimos por producto: por ejemplo "rojo escolar", "rosa bb", "piel", "cielo".
- Pruebas automáticas conectadas a una copia real del almacén, no solo a catálogo de ejemplo.
- Una pantalla de evaluación donde pegues conversación y el sistema diga: intención, contexto, productos, confianza y respuesta final.

Archivo de pruebas:
- test_whatsapp_ia_v28.py

Cómo probar localmente:
python test_whatsapp_ia_v28.py

Pruebas recomendadas en simulador:
1. ¿Manejan Komfy Mini?
2. ¿Tienen Velluto blanco?
3. me puede poner 3 del rojo
4. Me aparta 2 del 429, 3 del 532 y 1 del 56
5. quiero un blanco que no se vea tan amarillo
6. hola buenas tardes quiero cotizar un pedido de velluto son 15 madejas\n5 del 55 y 10 del 60
7. ¿Qué colores tiene de Komfy Mini disponibles?
8. cuanto sale el envío?
9. ya quedó el pago
10. manejan la abuelita?
