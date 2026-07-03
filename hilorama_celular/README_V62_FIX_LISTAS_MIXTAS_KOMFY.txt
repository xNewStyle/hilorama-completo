V62 - Fix listas mixtas con hilos distintos en una misma línea

Problema detectado en tester V61:
- Mensaje: "velluto 429 x34 y KOMFY 99 x2"
- La IA agregaba Velluto 429 x34, pero no agregaba Komfy 99 x2.
- Causa: el extractor detectaba "99 x2" sin conservar que antes decía KOMFY, y al resolver el código usaba el contexto anterior de Velluto.

Corrección:
- El extractor ahora reconoce patrones como:
  * velluto 429 x34
  * komfy 99 x2
  * komfy mini 99 x2
  * kurumi 12 x5
- Cada item guarda el hilo explícito cuando viene en la misma frase.
- El resolvedor busca ese código dentro de esa familia de hilo, no solo en el contexto memorizado.

Ejemplo esperado:
Cliente: velluto 429 x34 y KOMFY 99 x2
IA debe agregar:
- Velluto 429 x34
- Komfy Mini 99 x2

Esto mantiene la lógica V61 de volumétrico por puntos de almacén:
- productos.volumetrico = puntos de espacio
- 50 puntos = 5 kg volumétricos
- 100 puntos = 10 kg volumétricos
- 150 puntos = 15 kg volumétricos
