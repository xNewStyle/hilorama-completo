Hilorama celular - corrección analizar imagen con IA

Cambios incluidos:
1. Timeout de OpenAI subido por defecto a 60 segundos.
2. Imagen enviada a IA optimizada por defecto a 900 px para Render gratis.
3. Prompt visual ampliado con más formas de interpretar marcas:
   - círculos, óvalos, rayas, palitos, puntos, puntitos, flechas, palomitas, subrayados.
   - 1 punto = 1 pieza, 2 puntos = 2 piezas, 3 puntos = 3 piezas.
   - 1 raya/palito = 1 pieza, 2 rayas/palitos = 2 piezas, 3 = 3, 4 = 4.
   - números escritos cerca del producto: 2, 3, x2, 2pz, etc.
   - taches pueden ser selección cuando el comentario dice los marcados/los de X/los tachados.
   - taches pueden ser exclusión cuando el comentario dice tachados no/menos/excepto.
   - si tacha uno y dice todos los demás, selecciona todos los visibles menos el tachado.
4. Regla para evitar que un óvalo grande como el del 193 OXFORD se confunda con tachado.
5. Respaldo visual: si la IA confunde un círculo grande con X, el sistema puede rescatarlo como seleccionado y muestra advertencia.

Render recomendado:
Start Command:
gunicorn --timeout 180 --workers 1 --log-level info app:app

Variables recomendadas:
OPENAI_TIMEOUT_SECONDS=60
OPENAI_IMAGE_MAX_SIDE=900
OPENAI_CATALOG_MAX_ITEMS=250
