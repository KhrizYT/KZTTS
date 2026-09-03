# KZTTS v0.1

Primer MVP web de KZTTS:

- Login OAuth con Twitch (`chat:read` para el lector IRC del MVP).
- Lee el chat de Twitch desde el servidor.
- TTS gratuito con Microsoft Edge TTS (`es-MX-DaliaNeural` por defecto).
- Voces mexicanas seleccionables.
- Blacklist de usuarios/bots (Nightbot, StreamElements, etc.).
- Ignorar comandos y links.
- Cooldown por usuario.
- Cola de reproducción en una Browser Source de OBS.
- Sin programa de escritorio ni Social Stream Ninja.

## Importante

La v0.1 usa Twitch IRC para simplificar el primer despliegue. Twitch recomienda EventSub para implementaciones nuevas; la migración a EventSub queda prevista para la siguiente versión.

Edge TTS usa el servicio online de lectura de Microsoft Edge mediante una integración comunitaria no oficial. No necesita API key ni cobra por carácter, pero Microsoft puede cambiar el servicio. KZTTS está estructurado para cambiar de motor después sin reescribir el sistema de chats.

## Ejecutar

1. Crea una app en Twitch Developer Console.
2. Callback OAuth: `http://localhost:8000/auth/twitch/callback` para pruebas o `https://TU-DOMINIO/auth/twitch/callback` al desplegar.
3. Copia `.env.example` a `.env` y rellena las variables.
4. Instala dependencias:

```bash
pip install -r requirements.txt
```

5. Inicia:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## OBS

En el dashboard pulsa **Generar Browser Source**, copia la URL privada y crea una fuente `Browser` en OBS con esa URL. Activa la opción de controlar el audio mediante OBS si quieres manejar KZTTS como canal independiente.

## Despliegue online

El proyecto funciona en cualquier host Python que soporte WebSockets (Render, Railway, Fly.io, VPS, etc.). Para v0.1 los datos de las fuentes viven en memoria: si el servidor reinicia, genera una nueva URL. En v0.2 se migrarán cuentas/configuración a Postgres/Supabase.

## Siguiente versión

- Persistencia Postgres/Supabase.
- Kick.
- YouTube Live.
- TikTok Live.
- Panel de cola: skip / clear / mute.
- Diccionario de pronunciaciones.
- Filtros antispam más avanzados.
