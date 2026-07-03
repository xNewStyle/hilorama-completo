V49 - Envíos Hilorama con precio público por tabla propia

Qué corrige:
- Envia.com ya no define el precio que se muestra al cliente.
- Envia.com se usa para validar zona/tarifas/reexpedición.
- El precio público sale de la tabla de Hilorama.

Tabla base incluida:
- Correos de México: $110 para 1 a 5 kg volumétricos
- Estafeta: $199 para 1 a 5 kg volumétricos
- FedEx: $260 para 1 a 5 kg volumétricos
- DHL: $269 para 1 a 5 kg volumétricos

Reexpedición:
- Si Envia devuelve una tarifa mucho más alta que la base pública, el sistema marca posible reexpedición.
- Precio público = precio base + diferencia de reexpedición + extra.
- Extra default: $50.
- Puedes cambiarlo en Render con ENVIA_REEXPEDICION_EXTRA=100 si quieres cobrar $100 extra.

Variables opcionales en Render:
ENVIA_PUBLIC_CARRIERS=correos,estafeta,fedex
ENVIA_REEXPEDICION_EXTRA=50
ENVIA_REEXPEDICION_MARGIN_PCT=25

Si quieres sobreescribir toda la tabla:
ENVIA_PUBLIC_PRICE_TABLE_JSON={"correos":[{"max_kg":5,"precio":110}],"estafeta":[{"max_kg":5,"precio":199}],"fedex":[{"max_kg":5,"precio":260}]}

Prueba después de subir a Render:
/api/envios/cotizar?cp=97000&pin=TU_PIN
/api/envios/debug-payload?cp=97000&carrier=dhl&pin=TU_PIN

Importante:
No borres el token de Envia. Solo corrige variables si hace falta.
