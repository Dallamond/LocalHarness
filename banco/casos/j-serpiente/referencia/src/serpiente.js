// La serpiente: la lógica pura del juego (src/main.js la dibuja y lee el teclado).
const MOV = { derecha: [1, 0], izquierda: [-1, 0], arriba: [0, -1], abajo: [0, 1] };
const CONTRARIA = { derecha: "izquierda", izquierda: "derecha", arriba: "abajo", abajo: "arriba" };

export function crearPartida(ancho, alto) {
  return {
    ancho, alto, dir: "derecha", comida: null, puntos: 0, estado: "jugando",
    cuerpo: [{ x: 2, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 0 }],
  };
}

export function ponerComida(p, x, y) {
  return { ...p, comida: { x, y } };
}

export function girar(p, dir) {
  return dir in MOV && dir !== CONTRARIA[p.dir] ? { ...p, dir } : p;
}

export function paso(p) {
  if (p.estado !== "jugando") return p;
  const [dx, dy] = MOV[p.dir];
  const cabeza = { x: p.cuerpo[0].x + dx, y: p.cuerpo[0].y + dy };
  const fuera = cabeza.x < 0 || cabeza.y < 0 || cabeza.x >= p.ancho || cabeza.y >= p.alto;
  const choca = p.cuerpo.slice(0, -1).some((s) => s.x === cabeza.x && s.y === cabeza.y);
  if (fuera || choca) return { ...p, estado: "fin" };
  const come = p.comida && p.comida.x === cabeza.x && p.comida.y === cabeza.y;
  const cuerpo = [cabeza, ...(come ? p.cuerpo : p.cuerpo.slice(0, -1))];
  return { ...p, cuerpo, comida: come ? null : p.comida, puntos: p.puntos + (come ? 10 : 0) };
}
