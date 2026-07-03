V54 - Repositorio visual local Hilorama

Objetivo:
La IA ya no necesita depender de URLs externas para recursos visuales. Jorge puede pegar imágenes locales de gamas, tonos, fichas, accesorios, envíos, pagos y promociones.

Ruta principal:
hilorama_celular/static/recursos_ia/repositorio_visual/

Estructura principal:
- hilos/ALIZE/VELLUTO/gama
- hilos/ALIZE/VELLUTO/tonos
- hilos/ALIZE/VELLUTO/ficha
- hilos/KARINA/KOMFY_MINI/gama
- hilos/KARINA/KOMFY_MINI/tonos
- hilos/KARINA/KOMFY_MINI/ficha
- hilos/KARINA/KOMFY_PLUS/gama
- hilos/KARINA/KOMFY_PLUS/tonos
- hilos/KARINA/KOMFY_PLUS/ficha
- hilos/KARINA/KURUMI/gama
- hilos/KARINA/KURUMI/tonos
- hilos/KARINA/KURUMI/ficha
- hilos/KARINA/KOTTON_MILK/gama
- hilos/KARINA/KOTTON_MILK/tonos
- hilos/KARINA/KOTTON_MILK/ficha
- accesorios/ganchos
- accesorios/agujas
- accesorios/ojos_seguridad
- accesorios/relleno
- catalogos/KARINA
- catalogos/ALIZE
- catalogos/HILORAMA
- envios/costos
- envios/zonas_reexpedicion
- pagos/datos_pago
- promociones

Cómo agregar imágenes:
1. Pega las imágenes en la carpeta correcta.
2. Usa nombres simples:
   - 429.webp
   - 429_tabaco_claro.webp
   - 60_negro.jpg
   - gama_01.png
   - ficha_tecnica.png
3. Ejecuta:
   python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py
4. Sube cambios a GitHub/Render.
5. Importa en la IA:
   /api/ia/recursos/importar-static?pin=TU_PIN

Notas importantes:
- archivo_url ahora es una ruta local interna tipo /static/recursos_ia/..., no una URL externa.
- Las gamas se registran con enviar_junto=True para mandar varias imágenes juntas.
- Los tonos individuales se registran como foto_tono para responder: “me mandas foto del 429”.
- Las fichas se registran para composición, metraje, gancho, agujas y uso recomendado.
- Los envíos/pagos/promociones quedan como recursos visuales reutilizables.
