WhatsApp IA - Cerebro comercial V6

Esta versión corrige los fallos detectados en las pruebas reales del simulador:

1. Ya no mezcla hilos.
   - Si la clienta dice Komfy Mini, busca dentro de KOMFY MINI.
   - No debe agarrar Velluto negro ni Kairo rojo escolar cuando el pedido es de Komfy Mini.

2. Consultas no se convierten en pedidos.
   - "¿Cuánto cuesta el Velluto?" responde precio.
   - "¿Tienen Velluto blanco y negro?" responde disponibilidad y pregunta cantidad.
   - "¿Manejan Komfy Mini?" responde que sí y pregunta color/código.
   - No agrega productos al carrito si no hay pedido claro.

3. Combos y paquetes no se agregan como productos falsos.
   - Combo de 20 Velluto: responde que puede escoger colores y pide lista.
   - Paquete de 40 Velluto: responde que puede ir con colores a elegir y envío gratis si aplica en promo.

4. Códigos existentes sí se agregan directo.
   - "Dame 2 del 56, 4 del 532 y 1 del 429" agrega esos códigos.

5. Números ambiguos preguntan.
   - "Dame 2 4" pregunta si son 2 piezas del código 4 o los códigos 2 y 4.

6. Productos que no manejas.
   - "La Abuelita" responde que no se maneja y ofrece alternativas según proyecto.

7. Lista compacta.
   - "Dame 55 56 429" se interpreta como 1 de cada código.
   - "16 550" se interpreta como 16 piezas del código 550.

Archivos cambiados:
- app.py

Sugerencia de prueba:
Deja Marca = Todas e Hilo = Todos y prueba:
- Hola, ¿cuánto cuesta el Velluto?
- Buen día, ¿tienen Velluto blanco y negro?
- Dame 2 del 56, 4 del 532 y 1 del 429.
- Me interesa el combo de 20 Velluto, ¿puedo escoger colores?
- Quiero el paquete de 40 piezas de Velluto, ¿me sale con envío gratis?
- Hola, ¿manejan Komfy Mini?
- Quiero 3 Komfy Mini negro, 2 rosa y 1 rojo escolar.
- ¿Manejan estambre La Abuelita?
- Busco algo parecido a La Abuelita, ¿qué me recomiendas?
- Dame 2 4
