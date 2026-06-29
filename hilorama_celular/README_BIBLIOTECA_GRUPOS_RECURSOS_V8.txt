Biblioteca IA V8 - Grupos de recursos / envío conjunto

Qué agrega:
- Nuevos campos en ia_recursos: grupo, orden, enviar_junto.
- Si una gama tiene varias imágenes, todas usan el mismo grupo y enviar_junto=true.
- Cuando la IA encuentre una parte de la gama, responderá con todos los archivos activos del mismo grupo, ordenados por orden.
- Botón en Biblioteca IA: "Importar recursos físicos de static/recursos_ia".
- Autoimporta:
  * hilorama_celular/static/recursos_ia/Velluto Carta de Colores/*.png como grupo gama_velluto.
  * hilorama_celular/static/recursos_ia/Velluto Colores/* como fotos individuales de tonos.

Cómo agregar correctamente una gama de 4 imágenes:
1. Copia tus imágenes dentro del proyecto, por ejemplo:
   hilorama_celular/static/recursos_ia/Velluto Carta de Colores/004.png
   hilorama_celular/static/recursos_ia/Velluto Carta de Colores/4.png
   hilorama_celular/static/recursos_ia/Velluto Carta de Colores/5.png
   hilorama_celular/static/recursos_ia/Velluto Carta de Colores/6.png

2. Sube esos archivos con Git y Render.

3. En la app entra a Crear > IA / WhatsApp > Biblioteca IA / Recursos para clientes.

4. Presiona "Importar recursos físicos de static/recursos_ia".

5. Verifica que aparezcan recursos con:
   Categoria: carta_colores
   Grupo: gama_velluto
   Orden: 1,2,3,4
   Enviar junto: sí

Si agregas manualmente una gama:
- Nombre: Carta de colores Alize Velluto 1
- Categoría: carta_colores
- Marca: ALIZE
- Hilo: VELLUTO
- Grupo: gama_velluto
- Orden: 1
- Enviar junto: activado
- Tags: velluto, alize velluto, colores velluto, carta velluto, gama velluto, tonos velluto
- URL: /static/recursos_ia/Velluto Carta de Colores/004.png

Repite para las otras imágenes cambiando orden y URL.

Fotos individuales:
- Nombre: Foto tono Velluto 429
- Categoría: foto_tono
- Marca: ALIZE
- Hilo: VELLUTO
- Grupo: tono_velluto_429
- Orden: 1
- Enviar junto: desactivado
- Tags: velluto 429, tono 429, código 429, foto 429
- URL: /static/recursos_ia/Velluto Colores/429.webp

Pruebas:
- "Hola, me interesa Alize Velluto. ¿Qué colores tienen disponibles?"
  Debe responder con la gama y listar las 4 imágenes del grupo gama_velluto.

- "¿Me mandas foto del 429?"
  Debe responder con una sola foto del tono 429.
