WhatsApp IA V7 - Biblioteca IA + aprendizaje humano

Qué agrega:
- Sección nueva en IA / WhatsApp: Biblioteca IA / Recursos para clientes.
- Puedes guardar respuestas, cartas de colores, catálogos, links de Canva/Drive, datos de pago, reglas de envío, productos similares y casos especiales.
- Sección de Aprendizaje humano dentro del simulador.
- Cuando la IA responda mal, escribes la respuesta correcta que sí mandarías a la clienta y presionas Guardar aprendizaje.
- El agente buscará esos aprendizajes y recursos antes de usar la respuesta automática.

Tablas nuevas:
- ia_recursos
- ia_pendientes_humano

Endpoints nuevos:
- GET  /api/ia/recursos
- POST /api/ia/recursos
- PUT  /api/ia/recursos/<id>
- POST /api/whatsapp-ia/guardar-aprendizaje
- POST /api/whatsapp-ia/pendiente-humano
- GET  /api/whatsapp-ia/pendientes

Cómo usarlo:
1. Prueba un mensaje en Simulador WhatsApp IA.
2. Si la respuesta no te gusta, escribe abajo la respuesta humana correcta.
3. Agrega tags si quieres, por ejemplo: abuelita, sustituto, kurumi.
4. Presiona Guardar aprendizaje.
5. Vuelve a probar un mensaje parecido; debe usar esa respuesta guardada.

Para imágenes:
- En Biblioteca IA puedes pegar un link de Canva, Drive o imagen pública.
- Cuando el agente use ese recurso, en el simulador mostrará el link como recurso para enviar.

Notas:
- Esta versión no sube archivos físicamente a la nube todavía; guarda URLs/links.
- Para subida directa de imágenes desde celular se recomienda después usar Cloudinary, Supabase Storage o Google Drive API.
