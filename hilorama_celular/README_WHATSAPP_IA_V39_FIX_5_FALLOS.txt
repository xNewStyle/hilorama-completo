HILORAMA WHATSAPP IA V39 - CORRECCIÓN 5 FALLOS DEL TESTER V38

Qué corrige esta carpeta:

1) Cantidades en palabras:
   - Antes: "dos del 55 y cinco del 60" lo tomaba como x1 y x1.
   - Ahora: detecta 55 x2 y 60 x5.

2) Cantidad global para lista:
   - Antes: "55, 60, 429 todos x2" agregaba todos x1 y además tomaba el 2 como código.
   - Ahora: aplica x2 a 55, 60 y 429.

3) Validación de total:
   - Antes: "serían 15 piezas verdad?" contestaba genérico pidiendo hilo/código.
   - Ahora: revisa el pedido activo y confirma si son 15 piezas.

4) Seguimiento de pago/comprobante:
   - Antes: "me confirmas si llegó?" contestaba genérico.
   - Ahora: entiende que habla del comprobante y responde que lo revisa y confirma.

5) Pago futuro / apartado sin prometer:
   - Antes: "te pago en la noche" lo trataba como pago ya realizado.
   - Ahora: no promete apartado; responde que revisa la cotización y confirma disponibilidad.

6) Mejora extra encontrada en el reporte:
   - "tienes ojo de seguridad negro de 14 mm?" ya no debe confundirse con Komfy Mini 99 Negro.
   - Los números con "mm" en accesorios ya no se toman como códigos de hilo.

Archivos importantes:
- whatsapp_ia_v27.py  -> motor corregido V39
- tools/whatsapp_ia_human_tester_v39.py -> tester nuevo
- tools/casos_tester_v39_complejos_hilorama.json -> casos complejos reforzados

Cómo copiar:
1. Descomprime este ZIP.
2. Copia la carpeta hilorama_celular encima de tu carpeta actual del proyecto.
3. Acepta reemplazar archivos.
4. Prueba local.

Comando para probar en Render después de subir:
python hilorama_celular/tools/whatsapp_ia_human_tester_v39.py --base-url https://TU-SERVICIO.onrender.com --pin TU_PIN --limit 50 --sleep 0.2

Si tu servicio es el de siempre:
python hilorama_celular/tools/whatsapp_ia_human_tester_v39.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.2
