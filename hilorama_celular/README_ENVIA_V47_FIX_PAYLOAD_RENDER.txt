V47 - Fix Envia.com /ship/rate/ desde Render

Qué corrige:
1. Payload de Envia con la estructura que soporte compartió:
   - origin/destination con number, type, company, email, phone_code, district, category.
   - phone sin +52; se normaliza a 10 dígitos.
   - packages incluye name.
2. Headers HTTP con Accept y User-Agent para evitar peticiones urllib demasiado vacías.
3. Ya NO cachea errores 403/1010 ni respuestas sin tarifa. Antes un fallo podía quedarse guardado por horas.
4. Cambia la versión de cache para no reutilizar errores anteriores.
5. Agrega endpoint de diagnóstico:
   GET /api/envios/debug-payload?cp=64600&carrier=dhl
   Muestra el payload exacto sin mostrar el token.

Variables recomendadas en Render:
ENVIA_ENABLED=true
ENVIA_ENV=production
ENVIA_TOKEN=tu_token_real
ENVIA_ORIGIN_ZIP=tu_cp_origen
ENVIA_ORIGIN_NAME=Hilorama
ENVIA_ORIGIN_COMPANY=Hilorama
ENVIA_ORIGIN_EMAIL=tu_correo
ENVIA_ORIGIN_PHONE=10_digitos_sin_52
ENVIA_ORIGIN_STREET=tu_calle
ENVIA_ORIGIN_NUMBER=tu_numero
ENVIA_ORIGIN_DISTRICT=tu_colonia
ENVIA_ORIGIN_CITY=tu_ciudad
ENVIA_ORIGIN_STATE=clave_estado_ej_EM_CX_NL_YU
ENVIA_CARRIERS=dhl,estafeta,fedex,paquetexpress
ENVIA_DEFAULT_WEIGHT_KG=1
ENVIA_DEFAULT_LENGTH_CM=20
ENVIA_DEFAULT_WIDTH_CM=20
ENVIA_DEFAULT_HEIGHT_CM=15
ENVIA_DECLARED_VALUE=0

Pruebas después de subir a Render:
1) Ver payload sin llamar a Envia:
https://hilorama-celular.onrender.com/api/envios/debug-payload?cp=64600&carrier=dhl

2) Cotizar real:
https://hilorama-celular.onrender.com/api/envios/cotizar?cp=64600&carriers=dhl

Importante:
- No compartir el token completo por WhatsApp.
- Este código solo cotiza /ship/rate/. No genera guías.
