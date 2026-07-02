# WhatsApp IA Hilorama V37 - Corrección tester humano

Esta versión corrige fallos detectados por el tester conversacional humano V36.

Resultado V36 analizado:
- 50 conversaciones probadas
- 43 aprobadas
- 7 fallos
- 86% de efectividad

Problema principal:
El agente confundía preguntas generales con pedidos/cotizaciones inventadas.
Ejemplos incorrectos:
- "qué hilos tienes?" -> "Hilos Tienes x1"
- "manejan accesorios para tejer?" -> "Accesorios Tejer x1"
- "quiero hacer amigurumis, qué me recomienda?" -> lo convertía en producto
- "y de Karina qué tiene?" -> "Y x1"

Correcciones V37:
1. Nueva intención catalogo_general
   Detecta preguntas como:
   - qué hilos tienes
   - qué más manejan
   - qué marcas de hilos maneja
   - manejan accesorios para tejer
   - manejan agujas o ganchos
   - y de Karina qué tiene

2. Nueva intención recomendacion_producto
   Detecta dudas como:
   - quiero hacer amigurumis, qué me recomienda
   - ocupo algo tipo chenille pero barato
   - qué hilo me conviene
   - algo suave y económico

3. Evita cotizaciones inventadas
   Ya no debe generar productos falsos como:
   - Hilos Tienes x1
   - Accesorios Tejer x1
   - Holaa x1
   - Algo Tipo Chenille Pero Barato x1

4. Respuestas usando almacén
   El agente resume marcas, hilos y accesorios con base en productos leídos del almacén.

5. Descuentos humanos
   Mejora detección de frases como:
   - si llevo 15 me mejoras precio
   - me mejora precio
   - mejor precio
   Estas deben mandar a revisión humana.

6. Tester V37
   Se agregó:
   hilorama_celular/tools/whatsapp_ia_human_tester_v37.py

Comando recomendado:
python tools/whatsapp_ia_human_tester_v37.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.2

Después, si pasa bien:
python tools/whatsapp_ia_human_tester_v37.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.2
