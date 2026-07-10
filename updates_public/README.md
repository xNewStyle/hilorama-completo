# Hilorama Cliente - contenido publico de actualizaciones

Esta carpeta es la raiz publicable para un servicio Render Static dedicado a
las actualizaciones de Hilorama Cliente. No contiene backend, base de datos,
credenciales ni datos reales de clientes.

Antes de crear una actualizacion real, cambia `APP_VERSION` a la misma version
del release y vuelve a compilar `HiloramaCliente.exe`. Despues, el comando
siguiente prepara la version mas reciente para publicarla de forma manual:

```powershell
python hilorama_desktop\create_update_release.py --version 0.2.1 --static-base-url "https://TU-STATIC-RENDER.onrender.com" --note "Primera actualizacion automatica"
```

El resultado queda en:

```text
updates_public/
  updates/
    HiloramaCliente/
      update.json
      HiloramaCliente.exe
      RELEASE_NOTES.txt
```

Configura Render Static para publicar el contenido de `updates_public/`. La
publicacion se hace manualmente: este proyecto no sube ni despliega archivos
por si solo.

No agregar aqui `.env`, credenciales, tokens, comprobantes, bases de datos ni
herramientas privadas.
