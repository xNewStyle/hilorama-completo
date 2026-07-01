WhatsApp IA V19 - Contexto y listas

Correcciones:
1. El selector "Todas/Todos" ya no bloquea la memoria de conversación.
   Antes el sistema lo tomaba como si fuera un hilo real y por eso no aplicaba Velluto guardado en memoria.

2. Si la clienta responde algo como:
   - seria todo de velluto
   - sería todo en Velluto
   - todos son Velluto
   - la lista es de Velluto

   El agente lo interpreta como confirmación de contexto, NO como pregunta de precio.

3. Si había una lista anterior con dudas por hilos repetidos, la reintenta resolver usando el hilo confirmado.

4. Mejora ligera para colores coloquiales como "rojo escolar" cuando el hilo ya está confirmado.

Prueba recomendada:
- Pegar lista:
  me puede poner esta lista 550 x2
  493
  216 canario - 4
  Blanco 01- 2
  Rojo escolar- 2
  Hueso 26- 1

- Si pregunta dudas, responder:
  seria todo de velluto

Debe tomar la lista anterior como Velluto y no responder con precio.
