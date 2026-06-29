# Biblioteca IA V9 - Previsualización de recursos

Esta versión mejora el simulador WhatsApp IA para que las rutas de imágenes detectadas desde la Biblioteca IA se muestren como previsualizaciones.

Cambios principales:
- Cuando la IA encuentra un grupo como `gama_velluto`, el simulador muestra las 4 imágenes en tarjetas.
- La respuesta sugerida ya no muestra las rutas dentro del texto principal; las rutas aparecen en una sección separada de "Recursos para enviar".
- Botón "Copiar rutas" para copiar las imágenes detectadas.
- Botón "Abrir imágenes" para abrir cada recurso en una pestaña nueva.
- La vista "Ver biblioteca" también muestra miniatura cuando el recurso tiene imagen.

Para que una gama mande varias imágenes juntas:
- Todas deben tener el mismo grupo, por ejemplo `gama_velluto`.
- Deben tener `Enviar junto` activado.
- Deben tener orden 1, 2, 3, 4.
- Deben tener URLs válidas como `/static/recursos_ia/Velluto Carta de Colores/004.png`.

Si no se ve una imagen:
- Abre la ruta directamente en el navegador.
- Si da 404, revisa que la imagen exista en `hilorama_celular/static/recursos_ia/` y que se haya subido a Git.
- Evita cambiar mayúsculas, espacios o nombres de carpeta después de registrar el recurso.
