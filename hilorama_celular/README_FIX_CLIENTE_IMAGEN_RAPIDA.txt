Cambios de esta versión:

1) Corrige el error al guardar datos del cliente desde pago/comprobante:
   - Antes el móvil podía intentar PUT /api/clientes/COT-xxxxx.
   - Ahora usa el cliente_id real.
   - Además el backend acepta COT-xxxxx como respaldo y busca el cliente de esa nota.

2) Analizador de imágenes más rápido:
   - La imagen se comprime en el celular antes de subirla.
   - En modo rápido se manda imagen más ligera y catálogo reducido a la IA.
   - Se desactiva OCR local salvo diagnóstico admin.
   - Se mantiene botón admin de análisis preciso con ?admin=1.

3) Limpieza de caché PWA:
   - Se subió versión de cache de service worker para que el celular tome el nuevo index.html.
