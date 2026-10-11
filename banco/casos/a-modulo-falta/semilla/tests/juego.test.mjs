import { test } from "node:test";
import assert from "node:assert/strict";
import { crearPartida, avanzar, sumarPuntos } from "../src/juego.js";

test("una partida nueva", () => {
  assert.deepEqual(crearPartida(300), { reloj: { segundos: 300, frames: 0 }, puntos: 0 });
});

test("60 frames son un segundo", () => {
  let p = crearPartida(300);
  for (let i = 0; i < 60; i++) p = avanzar(p);
  assert.deepEqual(p.reloj, { segundos: 299, frames: 0 });
});

test("sumar puntos", () => {
  assert.equal(sumarPuntos(crearPartida(10), 50).puntos, 50);
});
