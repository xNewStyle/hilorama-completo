V52 - IA WhatsApp + envío por pedido acumulado

Cambios principales:
1. El pedido_en_proceso de WhatsApp ahora se acumula por conversación.
   Antes, si la clienta pedía 35 Velluto y luego agregaba 5 más, la memoria podía quedarse solo con el último mensaje.

2. Cuando la clienta pregunta "cuánto sería con envío" y ya existe lista/pedido en la conversación,
   el agente usa ese pedido acumulado para calcular el peso volumétrico.

3. El cálculo toma productos.volumetrico desde almacén.
   Si un producto real no tiene volumétrico configurado, manda revisión manual para no cobrar mal.

4. El mensaje al cliente puede incluir:
   - tramo de kg volumétricos
   - subtotal de productos
   - costo de envío por paquetería
   - total productos + envío

5. Si el pedido pasa de ENVIA_MAX_AUTO_VOLUMETRIC_KG, por defecto 15 kg volumétricos,
   no da precio automático y manda alerta para revisión manual.

6. Se agregó tester V52 con casos de envío dentro del hilo:
   python hilorama_celular/tools/whatsapp_ia_human_tester_v52.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.3

Rutas útiles:
- /api/envios/debug-tablas?pin=TU_PIN
- /api/envios/debug-volumetrico?nota_id=COT-XXX&pin=TU_PIN
- /api/envios/debug-whatsapp-contexto?pin=TU_PIN
- /api/envios/cotizar?cp=97000&nota_id=COT-XXX&pin=TU_PIN

Variables importantes:
ENVIA_MAX_AUTO_VOLUMETRIC_KG=15
ENVIA_PUBLIC_PRICE_TABLE_JSON={...}  opcional si quieres forzar la tabla desde Render
