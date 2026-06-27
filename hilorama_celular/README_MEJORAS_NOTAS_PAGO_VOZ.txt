Versión móvil mejorada

Cambios principales:
- Edición de notas: interfaz menos encimada en celular, barra de guardado ya no flota encima del contenido y el modo edición muestra aviso claro.
- Más rápido: al guardar, convertir o pagar ya no recarga todo el catálogo; solo refresca resumen y notas.
- Método de pago: al marcar pagada permite elegir método, monto y referencia. Se guarda en notas como metodo_pago, monto_pagado y referencia_pago.
- Almacén correcto: los items guardan producto_id para descontar el producto exacto cuando hay códigos repetidos por marca/hilo/color.
- Descuento de stock: convertir cotización a venta descuenta almacén; pagar directo una cotización también descuenta una sola vez. Pagar una venta pendiente no descuenta otra vez.
- Movimientos de almacén: registra SALIDA_STOCK y AJUSTE_STOCK en movimientos_almacen, compatible con el historial del programa de PC.
- Almacén móvil: botones rápidos +1, -1, editar stock exacto y editar color, con historial desplegable.
- Dictado por voz: ahora intenta mantenerse escuchando frases largas y solo finaliza al presionar Terminar dictado.

Render recomendado:
Start Command:
gunicorn --timeout 180 --workers 1 --log-level info app:app
