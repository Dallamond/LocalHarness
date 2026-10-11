// Reloj de la partida: cuenta frames y, cada 60, baja un segundo; nunca baja de 0.
export function crearReloj(segundos) {
  return { segundos, frames: 0 };
}

export function tic(r) {
  if (r.segundos <= 0) return { segundos: 0, frames: 0 };
  const frames = r.frames + 1;
  return frames >= 60 ? { segundos: r.segundos - 1, frames: 0 } : { segundos: r.segundos, frames };
}
