V51 - Envíos por volumétrico desde almacén

Qué cambia:
1. Para pedidos reales, el peso volumétrico se toma de productos.volumetrico.
2. Ya no se adivina el volumétrico por nombre del producto cuando hay carrito o nota real.
3. Si un producto real no tiene volumétrico configurado, el agente manda el envío a revisión manual para no cobrar mal.
4. La tabla de precios de envío se intenta leer en este orden:
   - ENVIA_PUBLIC_PRICE_TABLE_JSON en Render, si existe.
   - Tablas de la base de datos del programa, si existen:
     envios_tarifas, tarifas_envio, envios_precios, precios_envio,
     paqueterias_tarifas, tarifas_paqueteria, paqueterias_precios,
     envios_config, config_envios.
   - envios_config.json si existe en la carpeta.
   - Respaldo mínimo 5 kg si no hay tabla encontrada.
5. Si el pedido supera ENVIA_MAX_AUTO_VOLUMETRIC_KG, default 15 kg, no da precio automático y pide revisión manual.

Endpoints para revisar después de subir a Render:

1) Ver tabla de precios detectada y muestra de productos con volumétrico:
https://hilorama-celular.onrender.com/api/envios/debug-tablas?pin=TU_PIN

2) Revisar un pedido/nota por ID:
https://hilorama-celular.onrender.com/api/envios/debug-volumetrico?nota_id=COT-XXX&pin=TU_PIN

3) Cotizar envío por nota/carrito:
https://hilorama-celular.onrender.com/api/envios/cotizar?cp=97000&nota_id=COT-XXX&pin=TU_PIN

Importante:
- Si debug-tablas dice hay_tabla_db_detectada=false, significa que en esta base de Render todavía no existe la tabla de tarifas del programa de computadora, o tiene otro nombre de columnas.
- En ese caso manda captura de debug-tablas o sube la carpeta del programa de computadora para conectar el nombre exacto de la tabla.
