// Parches 5-7 de mario.md: entrada, velocidad, salto, monedas, jugador y bloques.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, cerca } from "./ayuda.mjs";

test("entrada: teclas puras", async () => {
  const { crearEntrada, aplicarTecla } = await src("entrada");
  const e = crearEntrada();
  assert.equal(e.izquierda, false);
  assert.equal(e.derecha, false);
  assert.equal(e.saltar, false);
  assert.equal(e.pausa, false);
  assert.equal(aplicarTecla(e, "KeyA", true).izquierda, true);
  assert.equal(aplicarTecla(e, "ArrowLeft", true).izquierda, true);
  assert.equal(aplicarTecla(e, "ArrowRight", true).derecha, true);
  assert.equal(aplicarTecla(e, "Space", true).saltar, true);
  assert.equal(aplicarTecla(e, "KeyW", true).saltar, true);
  assert.equal(aplicarTecla(e, "KeyP", true).pausa, true);
  assert.equal(aplicarTecla(aplicarTecla(e, "KeyD", true), "KeyD", false).derecha, false);
  assert.deepEqual(aplicarTecla(e, "KeyZ", true), e);
  assert.equal(e.izquierda, false);
});

test("movimiento: aceleración, tope y fricción", async () => {
  const { velocidadHorizontal } = await src("movimiento");
  assert.ok(cerca(velocidadHorizontal(0, { derecha: true }), 0.3));
  let v = 0;
  for (let i = 0; i < 20; i++) v = velocidadHorizontal(v, { derecha: true });
  assert.equal(v, 2.5);
  v = 0;
  for (let i = 0; i < 20; i++) v = velocidadHorizontal(v, { izquierda: true });
  assert.equal(v, -2.5);
  assert.ok(cerca(velocidadHorizontal(2, {}), 1.6));
  assert.equal(velocidadHorizontal(0.11, {}), 0);
  assert.ok(cerca(velocidadHorizontal(2, { derecha: true, izquierda: true }), 1.6));
});

test("salto: solo desde el suelo y salto corto al soltar", async () => {
  const { intentarSaltar, cortarSalto } = await src("salto");
  const s = intentarSaltar({ vy: 0, enSuelo: true }, true);
  assert.equal(s.vy, -8.5);
  assert.equal(s.enSuelo, false);
  assert.equal(intentarSaltar({ vy: 0, enSuelo: false }, true).vy, 0);
  assert.equal(intentarSaltar({ vy: 0, enSuelo: true }, false).vy, 0);
  assert.equal(cortarSalto({ vy: -7 }, false).vy, -3);
  assert.equal(cortarSalto({ vy: -7 }, true).vy, -7);
  assert.equal(cortarSalto({ vy: -2 }, false).vy, -2);
  const o = { vy: -7 };
  cortarSalto(o, false);
  assert.equal(o.vy, -7);
});

test("monedas: recoger por solape", async () => {
  const { recogerMonedas } = await src("monedas");
  const j = { x: 0, y: 0, ancho: 12, alto: 16 };
  let r = recogerMonedas(j, [{ x: 8, y: 0 }, { x: 100, y: 0 }]);
  assert.equal(r.recogidas, 1);
  assert.deepEqual(r.quedan, [{ x: 100, y: 0 }]);
  r = recogerMonedas(j, [{ x: 12, y: 0 }]);
  assert.equal(r.recogidas, 0);
  assert.equal(recogerMonedas(j, [{ x: 0, y: 0 }, { x: 4, y: 0 }]).recogidas, 2);
});

test("jugador: cae, se apoya, corre y salta", async () => {
  const { crearMapa } = await src("mapa");
  const { crearJugador, actualizarJugador } = await src("jugador");
  const m = crearMapa(["........", "........", "........", "########"]);
  let j = crearJugador({ x: 16, y: 32 });
  assert.equal(j.x, 18);
  assert.equal(j.ancho, 12);
  assert.equal(j.alto, 16);
  for (let i = 0; i < 10; i++) j = actualizarJugador(j, {}, m).jugador;
  assert.equal(j.y, 32);
  assert.equal(j.enSuelo, true);
  let k = j;
  for (let i = 0; i < 10; i++) k = actualizarJugador(k, { derecha: true }, m).jugador;
  assert.ok(k.x > 18);
  assert.equal(k.mirando, 1);
  assert.ok(actualizarJugador(j, { saltar: true }, m).jugador.vy < 0);
  const aire = { ...crearJugador({ x: 16, y: 0 }), enSuelo: false, vy: 0 };
  assert.ok(actualizarJugador(aire, { saltar: true }, m).jugador.vy >= 0);
});

test("bloques: ? da moneda, M da champi, el resto nada", async () => {
  const { crearMapa } = await src("mapa");
  const { golpearBloque } = await src("bloques");
  const m = crearMapa(["?M#B"]);
  const a = golpearBloque(m, 0, 0);
  assert.equal(a.puntos, 200);
  assert.equal(a.sale, "moneda");
  assert.deepEqual(a.mapa.tiles, ["UM#B"]);
  assert.equal(golpearBloque(m, 1, 0).sale, "champi");
  assert.equal(golpearBloque(m, 2, 0).sale, null);
  assert.equal(golpearBloque(m, 3, 0).puntos, 0);
  assert.equal(golpearBloque(a.mapa, 0, 0).sale, null);
  assert.deepEqual(m.tiles, ["?M#B"]);
});
