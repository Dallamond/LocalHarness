import { crearPartida, girar, paso, ponerComida } from "./serpiente.js";

const CELDA = 20;
const lienzo = document.getElementById("tablero");
const ctx = lienzo.getContext("2d");
const marcador = document.getElementById("puntos");
let p = crearPartida(lienzo.width / CELDA, lienzo.height / CELDA);

function nuevaComida() {
  for (;;) {
    const x = Math.floor(Math.random() * p.ancho);
    const y = Math.floor(Math.random() * p.alto);
    if (!p.cuerpo.some((s) => s.x === x && s.y === y)) return ponerComida(p, x, y);
  }
}

function dibujar() {
  ctx.fillStyle = "#1d2b1f";
  ctx.fillRect(0, 0, lienzo.width, lienzo.height);
  if (p.comida) {
    ctx.fillStyle = "#e0533d";
    ctx.fillRect(p.comida.x * CELDA + 3, p.comida.y * CELDA + 3, CELDA - 6, CELDA - 6);
  }
  ctx.fillStyle = "#9bd36a";
  for (const s of p.cuerpo) ctx.fillRect(s.x * CELDA + 1, s.y * CELDA + 1, CELDA - 2, CELDA - 2);
  marcador.textContent = p.estado === "fin" ? `Fin: ${p.puntos} puntos (Espacio para volver a jugar)` : `${p.puntos} puntos`;
}

const TECLAS = { ArrowRight: "derecha", ArrowLeft: "izquierda", ArrowUp: "arriba", ArrowDown: "abajo" };
addEventListener("keydown", (e) => {
  if (TECLAS[e.key]) p = girar(p, TECLAS[e.key]);
  if (e.key === " " && p.estado === "fin") p = crearPartida(p.ancho, p.alto);
});

setInterval(() => {
  if (!p.comida) p = nuevaComida();
  p = paso(p);
  dibujar();
}, 120);
