Hilorama WhatsApp IA - Envia.com SOLO COTIZACION V24

Qué agrega:
- Endpoint nuevo: /api/envios/cotizar
- Consulta Envia.com usando únicamente POST /ship/rate/
- NO llama /ship/generate/
- NO genera guías
- NO compra etiquetas
- NO genera cargos automáticos de envío
- Guarda cache de cotizaciones por CP/peso/medidas/paqueterías
- Conecta el agente WhatsApp IA para que, si el cliente manda CP, responda tarifas reales de Envia.

Variables necesarias en Render:
ENVIA_ENABLED=1
ENVIA_ENV=production
ENVIA_TOKEN=tu_token
ENVIA_ORIGIN_COUNTRY=MX
ENVIA_ORIGIN_ZIP=57000
ENVIA_DEFAULT_WEIGHT_KG=1
ENVIA_DEFAULT_LENGTH_CM=30
ENVIA_DEFAULT_WIDTH_CM=25
ENVIA_DEFAULT_HEIGHT_CM=20
ENVIA_CACHE_HOURS=24

Variables opcionales recomendadas:
ENVIA_ORIGIN_NAME=Hilorama
ENVIA_ORIGIN_PHONE=+52TU_TELEFONO
ENVIA_ORIGIN_STREET=TU_DIRECCION_DE_ORIGEN
ENVIA_ORIGIN_CITY=Nezahualcoyotl
ENVIA_ORIGIN_STATE=EM
ENVIA_CARRIERS=estafeta,fedex,dhl,paquetexpress,correosdemexico
ENVIA_TIMEOUT_SECONDS=18
ENVIA_DECLARED_VALUE=1000
ENVIA_CURRENCY=MXN

Prueba API manual:
POST /api/envios/cotizar
Body:
{
  "cp_destino": "78174",
  "piezas": 20
}

Respuesta esperada:
{
  "ok": true,
  "modo": "SOLO_COTIZACION_NO_GUIAS",
  "opciones": [ ... ]
}

Prueba en WhatsApp IA:
Cliente: ¿cuánto sale el envío?
Debe pedir CP.

Cliente: mi CP es 78174
Debe consultar Envia y responder opciones reales.

Importante:
Si Envia no devuelve tarifa, el agente no inventa precio. Responde que se debe revisar manualmente.
