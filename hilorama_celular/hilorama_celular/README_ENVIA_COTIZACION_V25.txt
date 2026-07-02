Hilorama V25 - Envia.com solo cotizacion corregida

Cambios:
- Sigue usando SOLO /ship/rate/. NO genera guias ni compra etiquetas.
- Ya no depende de Geocodes API para Mexico, porque algunos tokens regresan 403 Forbidden.
- Usa cp_offline.json local para obtener municipio/estado por CP.
- Normaliza estados a claves de Envia: Estado de Mexico -> EM, Yucatan -> YU, CDMX -> CX, etc.
- Cambia cache a version V25 para no reutilizar respuestas fallidas de V24.
- Agrega endpoint debug:
  /api/envios/debug-direccion?cp=97000&pin=TU_PIN

Prueba manual:
/api/envios/debug-direccion?cp=97000&pin=TU_PIN
/api/envios/cotizar?cp=97000&carriers=dhl&pin=TU_PIN
/api/envios/cotizar?cp=97000&carriers=estafeta&pin=TU_PIN

Variables recomendadas en Render:
ENVIA_ENABLED=1
ENVIA_ENV=production
ENVIA_TOKEN=tu_token
ENVIA_ORIGIN_COUNTRY=MX
ENVIA_ORIGIN_ZIP=57000
ENVIA_ORIGIN_NAME=Hilorama
ENVIA_ORIGIN_PHONE=+52TU_TELEFONO_REAL
ENVIA_ORIGIN_STREET=TU_CALLE_Y_NUMERO
ENVIA_ORIGIN_CITY=Nezahualcoyotl
ENVIA_ORIGIN_STATE=EM
ENVIA_CARRIERS=dhl,estafeta,fedex,paquetexpress,ampm
ENVIA_TIMEOUT_SECONDS=25

Importante:
Si pruebas desde navegador y tienes MOBILE_PIN activo, agrega &pin=TU_PIN.
