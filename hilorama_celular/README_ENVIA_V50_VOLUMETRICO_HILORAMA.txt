V50 - ENVÍOS HILORAMA POR PESO VOLUMÉTRICO REAL

Objetivo:
- Envia.com se usa para validar zona / reexpedición.
- Al cliente se le cobra la tabla pública de Hilorama.
- El precio se basa en peso volumétrico del pedido, no solo en CP.

Regla base:
- 35 Velluto = 5 kg volumétricos.
- Si el producto tiene productos.volumetrico, se usa ese valor.
- Si no tiene volumétrico, se usan respaldos:
  ENVIA_VOL_VELLUTO=0.142857
  ENVIA_VOL_KOMFY_MINI=0.07
  ENVIA_VOL_TRAPILLO=0.50
  ENVIA_VOL_RELLENO=0.50
  ENVIA_VOL_DEFAULT=0.10

Tabla default:
- 1 a 5 kg volumétricos:
  Correos $110, Estafeta $199, FedEx $260, DHL $269
- 6 a 10 kg volumétricos:
  default doble
- 11 a 15 kg volumétricos:
  default triple

Si tienes tu tabla exacta, configúrala en Render con:
ENVIA_PUBLIC_PRICE_TABLE_JSON={"correos":[{"max_kg":5,"precio":110},{"max_kg":10,"precio":220},{"max_kg":15,"precio":330}],"estafeta":[{"max_kg":5,"precio":199},{"max_kg":10,"precio":398},{"max_kg":15,"precio":597}],"fedex":[{"max_kg":5,"precio":260},{"max_kg":10,"precio":520},{"max_kg":15,"precio":780}],"dhl":[{"max_kg":5,"precio":269},{"max_kg":10,"precio":538},{"max_kg":15,"precio":807}]}

Pedidos mayores:
- Si el pedido pasa de ENVIA_MAX_AUTO_VOLUMETRIC_KG, default 15, el agente NO da precio automático.
- Responde que se revisa manualmente y marca alerta.

Reexpedición:
- Si Envia devuelve un precio mucho mayor al precio base, se marca posible reexpedición.
- Precio público = precio base + diferencia estimada + ENVIA_REEXPEDICION_EXTRA.
- ENVIA_REEXPEDICION_EXTRA default 50, se puede poner 100.

Pruebas útiles en navegador:
1) Ver que 35 Velluto caiga en 5 kg:
/api/envios/debug-volumetrico?velluto=35&pin=TU_PIN

2) Ver que 34 Velluto + 2 Komfy Mini siga en 5 kg:
/api/envios/debug-volumetrico?velluto=34&komfy=2&pin=TU_PIN

3) Cotizar con tabla Hilorama:
/api/envios/cotizar?cp=97000&velluto=35&pin=TU_PIN

4) Cotizar por nota guardada:
/api/envios/cotizar?cp=97000&nota_id=COT-XXX&pin=TU_PIN

IMPORTANTE:
El simulador del agente ahora manda el carrito actual al backend como items_envio para que calcule el peso volumétrico real.
