import { crearReloj, tic } from "./reloj.js";

// Una partida: su reloj y los puntos.
export function crearPartida(segundos) {
  return { reloj: crearReloj(segundos), puntos: 0 };
}

export function avanzar(p) {
  return { ...p, reloj: tic(p.reloj) };
}

export function sumarPuntos(p, n) {
  return { ...p, puntos: p.puntos + n };
}
