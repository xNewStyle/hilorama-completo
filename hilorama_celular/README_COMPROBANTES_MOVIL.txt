Cambios de esta versión:

1. Comprobantes de pago adaptados a móvil:
   - En detalle de nota aparece sección "Comprobante de pago".
   - Permite tocar para elegir imagen o arrastrarla sobre la zona.
   - Guarda la imagen optimizada en la base de datos como data:image/jpeg;base64.
   - El comprobante se incluye en el PDF de venta premium cuando se abre desde móvil.

2. Flujo como PC:
   - Al convertir cotización a venta o confirmar pago, valida datos completos del cliente.
   - Si faltan datos, abre formulario móvil y después permite continuar.
   - Reglas de cliente completo: nombre, teléfono de 10 dígitos, calle, número exterior, colonia, CP, estado y municipio.

3. Datos de cliente:
   - Agrega edición móvil de cliente.
   - El código postal puede autocompletar estado, municipio y colonias usando cp_offline.json.

4. Almacén:
   - Conserva producto_id en carrito/items para descontar el producto exacto.
   - Evita equivocarse cuando hay códigos repetidos en distintos hilos/marcas.

5. Pagos:
   - Guarda método de pago, monto pagado, referencia y comprobante.
   - Mantiene historial básico en tabla pagos.
