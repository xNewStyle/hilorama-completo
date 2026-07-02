# WhatsApp IA cerebro comercial V5

Corrige pruebas reales del simulador:

- Komfy Mini ya no debe mezclarse con Velluto, Kairo u otros hilos cuando la clienta dice "Komfy Mini".
- Si existen hilos parecidos como KOMFY y KOMFY MINI, se prefiere KOMFY MINI cuando el mensaje menciona Mini.
- Kurumi se detecta por familia de hilo desde el almacén.
- Combos/paquetes con envío primero responden sobre el paquete, no solo piden código postal.
- Pedidos como "Quiero 3 Komfy Mini negro, 2 rosa y 1 rojo escolar" se resuelven dentro de Komfy Mini.
- "Rosa" prioriza tonos que realmente contienen ROSA antes que Fucsia.
- "Rojo escolar" prioriza coincidencia exacta.

Pruebas recomendadas:

1. Hola, ¿manejan Komfy Mini?
2. Quiero 3 Komfy Mini negro, 2 rosa y 1 rojo escolar.
3. Hola, ¿manejan Kurumi?
4. Me puedes mandar disponibilidad de Kurumi, por favor.
5. Quiero el paquete de 40 piezas de Velluto, ¿me sale con envío gratis?
6. Me interesa el combo de 20 Velluto, ¿puedo escoger colores?
