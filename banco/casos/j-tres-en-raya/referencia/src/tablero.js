// Tres en raya: el tablero es una lista de 9 casillas ('X', 'O' o null), de izquierda a derecha y de arriba abajo.
const LINEAS = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

export function crearTablero() {
  return Array(9).fill(null);
}

export function jugar(t, i, ficha) {
  if (t[i] !== null) throw new Error("casilla ocupada");
  return t.map((c, k) => (k === i ? ficha : c));
}

export function ganador(t) {
  for (const [a, b, c] of LINEAS) if (t[a] && t[a] === t[b] && t[a] === t[c]) return t[a];
  return t.every((c) => c !== null) ? "empate" : null;
}

function cierra(t, ficha) {
  for (let i = 0; i < 9; i++) if (t[i] === null && ganador(jugar(t, i, ficha)) === ficha) return i;
  return -1;
}

export function jugadaIA(t, ficha) {
  const rival = ficha === "X" ? "O" : "X";
  for (const f of [ficha, rival]) {
    const i = cierra(t, f);
    if (i !== -1) return i;
  }
  if (t[4] === null) return 4;
  for (const i of [0, 2, 6, 8]) if (t[i] === null) return i;
  return t.indexOf(null);
}
