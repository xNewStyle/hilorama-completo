# WhatsApp IA V12 - Precio desde almacén

Corrección:
- El agente de WhatsApp IA ahora prioriza el precio guardado directamente en productos.precio, que es el precio de venta del almacén.
- Solo usa la tabla precios.venta como respaldo si el producto no tiene precio propio.
- Esto evita que preguntas como "¿cuánto cuesta el Velluto?" respondan con un precio global viejo o incorrecto.

Regla nueva:
1. Precio de venta del producto/almacén: productos.precio
2. Respaldo: precios.venta
3. Si no hay precio, pregunta o deja en revisión.

Prueba:
- Hola, ¿cuánto cuesta el Velluto?
- ¿Cuánto cuesta Komfy Mini?
- Dame 2 del 56

