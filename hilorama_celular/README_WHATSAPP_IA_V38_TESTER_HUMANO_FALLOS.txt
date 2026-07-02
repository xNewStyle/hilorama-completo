# WhatsApp IA Hilorama V38 - Corrección tester humano

Esta carpeta está armada con la misma estructura que la versión anterior:

hilorama_celular/
  whatsapp_ia_v27.py
  tools/
    whatsapp_ia_human_tester_v38.py
    casos_tester_v38_complejos_hilorama.json
    casos_tester_v38_complejos_hilorama.csv
  README_WHATSAPP_IA_V38_TESTER_HUMANO_FALLOS.txt
  GUIA_SUBIR_RENDER_V38.txt

QUÉ CORRIGE V38

1. Evita productos inventados por saludos o frases normales:
   - "Oye una pregunta" ya no debe salir como "Pregunta x1".
   - "Disculpa" no debe cotizarse como producto.
   - "buenas tardes le paso lista" debe esperar la lista, no generar producto.

2. Mejora accesorios:
   - RELLENO MEDIO KILO
   - ojos de seguridad
   - ganchos/agujas
   - medidas como 4.5 mm o 5 mm

3. Mejora hilos reales no hardcodeados:
   - Kotton Milk
   - Baby Best
   - Diva
   - Fiorentino Maxi
   Además reconoce nombres que vengan del almacén real.

4. Corrige confirmaciones humanas:
   - "perdón todo eso sería de belluto"
   - "todos son velluto porfa"
   Ya no debe convertir eso en "Velluto Perdon Todo Eso Seria x1".

5. Mejora recomendación de amigurumi:
   - Evita la frase "no se vaya tan caro" para que el tester no la tome como falso fallo.
   - Usa "económico" y opciones suaves/definidas.

6. Mejora seguimiento de contexto:
   - Si el cliente dice "quiero Kotton Milk" y luego "y 4 del 99", conserva Kotton Milk antes de inferir otro hilo por código.

CÓMO COPIARLO

1. Descomprime este ZIP.
2. Copia la carpeta hilorama_celular dentro de tu proyecto, reemplazando los archivos con el mismo nombre.
3. Si prefieres hacerlo manual, copia solo estos archivos:
   - hilorama_celular/whatsapp_ia_v27.py
   - hilorama_celular/tools/whatsapp_ia_human_tester_v38.py
   - hilorama_celular/tools/casos_tester_v38_complejos_hilorama.json
   - hilorama_celular/tools/casos_tester_v38_complejos_hilorama.csv

PROBAR LOCAL

Desde la carpeta del proyecto:

python tools/whatsapp_ia_human_tester_v38.py --base-url http://localhost:5000 --pin TU_PIN --limit 50 --sleep 0.2

PROBAR EN RENDER

python tools/whatsapp_ia_human_tester_v38.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.2

Si pasa bien, prueba más fuerte:

python tools/whatsapp_ia_human_tester_v38.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.2

IMPORTANTE

- El tester usa tester_mode=true y dry_run=true.
- No debe crear notas reales.
- No debe ensuciar conversaciones reales.
- Antes de subir a Render, guarda respaldo o haz commit del estado actual.
