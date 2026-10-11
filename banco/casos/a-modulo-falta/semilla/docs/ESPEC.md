# Reloj de la partida

`src/reloj.js` exporta:
- `crearReloj(segundos)` → `{segundos, frames: 0}`.
- `tic(reloj)` → un reloj NUEVO con `frames` + 1; cuando `frames` llega a 60 vuelve a 0 y `segundos` baja 1.
  Con `segundos` a 0 devuelve `{segundos: 0, frames: 0}` (nunca baja de 0).
