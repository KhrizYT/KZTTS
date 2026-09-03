# KZTTS v0.6

Rediseño completo del dashboard de KZTTS sobre la base persistente de v0.5.

## Novedades

- Dashboard con sidebar y páginas: Resumen, Plataformas, TTS · Voz, Filtros y OBS.
- Biblioteca visual de voces mexicanas gratuitas.
- Guardado automático en PostgreSQL, además del botón de guardado manual.
- Browser Source permanente: la URL de OBS no cambia al modificar ajustes.
- Control de TTS en vivo desde el dashboard: pausar/reanudar, skip y vaciar cola.
- Estado de la Browser Source, mensaje actual y tamaño de cola en tiempo real.
- Volumen configurable.
- Modo `Leer todo` o `Sólo comando` (por defecto `!tts`).
- Twitch + Kick + YouTube + TikTok siguen usando la misma cola.

## Actualización desde v0.5

Reemplaza en GitHub:

- `main.py`
- `static/index.html`
- `static/app.js`
- `static/style.css`
- `static/overlay.html`

No necesitas cambiar PostgreSQL ni añadir nuevas variables de entorno.

Railway redeployará automáticamente. La URL permanente de OBS vinculada a tu cuenta se conserva.
