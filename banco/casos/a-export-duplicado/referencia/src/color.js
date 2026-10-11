// Colores: hex(r, g, b) → '#rrggbb'; rgb('#rrggbb') → [r, g, b]; aclarar('#rrggbb', pct) acerca cada canal a 255
// en pct %: canal + Math.round((255 − canal) × pct / 100).
export function hex(r, g, b) {
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

export function rgb(texto) {
  const n = parseInt(texto.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function aclarar(texto, pct) {
  const [r, g, b] = rgb(texto).map((c) => c + Math.round(((255 - c) * pct) / 100));
  return hex(r, g, b);
}
