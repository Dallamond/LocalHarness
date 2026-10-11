// formatear(segundos) → 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') → segundos.
export function formatear(segundos) {
  const m = Math.floor(segundos / 60);
  const s = segundos % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function aSegundos(texto) {
  const [m, s] = texto.split(":").map(Number);
  return m * 60 + s;
}
