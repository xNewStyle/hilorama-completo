WhatsApp IA V20 - listas con código + color seguro

Corrige listas reales donde la clienta escribe color y código en la misma línea:

550 x2
493
216 canario - 4
Blanco 01- 2
Rojo escolar- 2
Hueso 26- 1

Mejoras:
- Si el código no existe en el hilo confirmado, intenta resolver por el nombre/color antes de marcar error.
- Si el código existe pero NO coincide con el color escrito, ya no agrega el producto equivocado.
- Ejemplo: si en Velluto el código 26 es Café Chocolate pero la clienta escribió Hueso 26, no debe agregar Café Chocolate sin validar; busca Hueso por nombre o pregunta.
- Si la clienta confirma después “todo sería Velluto”, re-resuelve la lista anterior con estas reglas nuevas.
- “Blanco 01-2” puede resolverse por color Blanco si el código 01 no existe en Velluto.
