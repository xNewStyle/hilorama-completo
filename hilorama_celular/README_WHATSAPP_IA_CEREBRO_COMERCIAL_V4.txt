WhatsApp IA V4 - Cerebro comercial por almacén

Cambios:
- El parser devuelve respuesta_preferida al simulador para evitar que OpenAI invente cuando ya hay respuesta comercial.
- Consultas sin cantidad ya no agregan productos por accidente.
- Combo/paquete 10/20/40 se responde como pregunta comercial, no como producto de carrito.
- Detección más fuerte de Velluto, Komfy Mini y Kurumi aunque los selectores estén en Todas/Todos.
- Preguntas como "cuánto cuesta Velluto", "manejan Komfy Mini", "disponibilidad de Kurumi" usan el almacén.
- La Abuelita se contesta como producto externo no manejado y se ofrecen alternativas.
- Para pedidos con Komfy Mini se filtra el hilo correcto antes de buscar colores.

Pruebas recomendadas:
- Hola, ¿cuánto cuesta el Velluto?
- Hola, ¿manejan Komfy Mini?
- Quiero 3 Komfy Mini negro, 2 rosa y 1 rojo escolar.
- Hola, ¿manejan Kurumi?
- Me interesa el combo de 20 Velluto, ¿puedo escoger colores?
- Quiero el paquete de 40 piezas de Velluto, ¿me sale con envío gratis?
- ¿Manejan estambre La Abuelita?
- Busco algo parecido a La Abuelita, ¿qué me recomiendas?
