Analizador de imágenes restaurado a modo preciso.

Cambios:
- Se desactiva el modo rápido en el servidor aunque el navegador viejo mande modo=rapido.
- Se sube la imagen a 1400 px por lado con calidad 90 para leer códigos mejor.
- Siempre se manda imagen auxiliar con marcas resaltadas.
- Se usa detail=high en OpenAI.
- Se amplió rescate de óvalos/círculos grandes para evitar que se confundan con tachón o se omitan.
- Se conserva la corrección de cliente/dirección/comprobante.

Recomendado en Render:
OPENAI_TIMEOUT_SECONDS=120
OPENAI_IMAGE_MAX_SIDE=1400
OPENAI_IMAGE_QUALITY=90
OPENAI_CATALOG_MAX_ITEMS=350
