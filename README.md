# KZTTS v0.5 — persistencia real

Esta versión convierte el prototipo en una app persistente:

- PostgreSQL guarda la cuenta KZTTS y la configuración del TTS.
- Los tokens OAuth de Twitch/Kick se guardan cifrados usando una clave derivada de `SESSION_SECRET`.
- Twitch/Kick siguen conectados después de un redeploy (salvo que el proveedor revoque/caduque el token).
- La Browser Source se guarda en la cuenta y conserva la misma URL entre deploys.
- Voz, velocidad, tono, blacklist, cooldown, plataformas, @YouTube y @TikTok se guardan en la nube.
- La configuración de localStorage de v0.4 se usa como migración si todavía no existe una copia cloud.

## Railway

1. Añade un servicio PostgreSQL al mismo proyecto.
2. En el servicio `kztts` agrega una Reference Variable:
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`
3. Mantén `SESSION_SECRET` exactamente igual. Si lo cambias, las sesiones y los tokens cifrados anteriores dejan de poder recuperarse.
4. Redeploy.
5. Reconecta Twitch y Kick una última vez para migrarlos a la base.
6. Pulsa **Guardar configuración**. Desde ahí la configuración y la URL quedan persistentes.

No pongas `DATABASE_URL` ni ningún secret en GitHub.
