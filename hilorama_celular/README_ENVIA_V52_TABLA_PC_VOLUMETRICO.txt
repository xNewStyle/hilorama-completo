V52 - Envíos Hilorama desde tabla del programa de computadora

Qué corrige:
- Lee envios_config.json del programa de PC.
- Respeta los tramos 50/100/150 del programa, que equivalen a 5/10/15 kg volumétricos comerciales.
- Para notas/carritos reales usa productos.volumetrico * cantidad.
- Ya no convierte todo a kg directos ni usa 5/10/15 si la tabla real está en 50/100/150.
- Si pasa de 150 unidades volumétricas (~15 kg) manda revisión manual.
- Si un producto real no trae volumétrico configurado, manda revisión manual.
- Envia.com queda solo para validar zona/reexpedición; el precio público sale de tabla Hilorama.

Pruebas después de Render:
/api/envios/debug-tablas?pin=TU_PIN
/api/envios/debug-volumetrico?velluto=35&pin=TU_PIN
/api/envios/debug-volumetrico?items=[{"codigo":"55","cantidad":35}]&pin=TU_PIN
/api/envios/cotizar?cp=97000&nota_id=COT-XXX&pin=TU_PIN

Importante:
Si debug-tablas muestra productos_con_volumetrico=0, el código está bien pero falta sincronizar el campo volumetrico en la base de Render.
