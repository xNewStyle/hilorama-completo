MEJORA WHATSAPP IA - CONTEXTO AUTOMATICO POR ALMACEN

Archivos principales modificados:
- hilorama_celular/app.py
- hilorama_celular/parser_whatsapp.py se conserva como parser base.

Que mejora:
1. Ya no es obligatorio seleccionar marca/hilo en la interfaz.
   El agente revisa el mensaje y detecta si la clienta esta pidiendo Velluto, Komfy Mini, Trapillo Kraft, etc.

2. El agente usa la base de datos/almacen como fuente de verdad:
   - Codigos existentes se agregan directo.
   - Hilos mencionados se usan como contexto automatico.
   - Colores se buscan dentro del hilo correcto.
   - No inventa productos que no existan en almacen.

3. Mensajes largos y humanos:
   Ejemplo:
   "quiero 3 vellutos pero un tono blanco o hueso que se vea medio amarillento y 3 negros pero de komfy mini y 1 komfy rojo pensandolo mejor quitame el komfi"

   El motor intenta:
   - Detectar Velluto para el primer tramo.
   - Detectar Komfy Mini para los negros.
   - Quitar Komfy si la clienta se arrepiente.
   - Si describe un tono en vez de codigo exacto, sugiere opciones parecidas del almacen.

4. Cuando piden un hilo sin tono/codigo:
   Ejemplo: "quiero 3 vellutos"
   Responde que si cuenta con Velluto y pide tono/codigo, en vez de inventar.

5. Cuando no encuentra el producto exacto por nombre:
   Usa un diccionario interno de texturas para sugerir productos similares del almacen.
   Nota: esto NO es busqueda web real todavia. Para buscar en internet en vivo se necesita agregar una API externa de busqueda.

6. Respuesta mas humana:
   Ya no pregunta por codigos que existen.
   No pide confirmar un negro unico.
   Solo pregunta lo que realmente esta dudoso.

Recomendacion:
Subir, probar con mensajes reales y ajustar alias/colores favoritos del negocio.
