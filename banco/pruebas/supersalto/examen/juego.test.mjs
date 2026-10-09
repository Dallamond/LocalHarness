// Parches 10-14 de mario.md: partida, paso, meta, fin de nivel, pantallas y control.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src } from "./ayuda.mjs";

const DOS = [".J..F\n#####\n", ".J...F\n######\n"];

test("partida: crearPartida y cargarNivel conservando puntos", async () => {
  const { crearPartida, cargarNivel } = await src("partida");
  const p = crearPartida(DOS);
  assert.equal(p.vidas, 3);
  assert.equal(p.puntos, 0);
  assert.equal(p.estado, "jugando");
  assert.equal(p.jugador.x, 18);
  const q = cargarNivel({ ...p, puntos: 300 }, 1);
  assert.equal(q.puntos, 300);
  assert.equal(q.mapa.ancho, 6);
});

test("paso: se apoya, muere en un hueco y vuelve a jugar", async () => {
  const { crearPartida } = await src("partida");
  const { paso } = await src("paso");
  let p = crearPartida([".J......F\n.........\n#########\n", ".J..F\n#####\n"]);
  for (let i = 0; i < 60; i++) p = paso(p, {});
  assert.equal(p.jugador.enSuelo, true);
  assert.equal(p.estado, "jugando");
  p = crearPartida([".J.....F\n........\n#..#####\n", ".J..F\n#####\n"]);
  for (let i = 0; i < 120; i++) p = paso(p, {});
  assert.equal(p.vidas, 2);
  assert.equal(p.estado, "muerto");
  let volvio = false;
  for (let i = 0; i < 100 && !volvio; i++) {
    p = paso(p, {});
    volvio = p.estado === "jugando";
  }
  assert.ok(volvio, "tras morir vuelve a 'jugando'");
});

test("meta: tocar el mástil y puntos por altura", async () => {
  const { tocaMeta, puntosMeta } = await src("meta");
  const meta = { x: 160, y: 160 };
  assert.equal(tocaMeta({ x: 160, y: 150, ancho: 12, alto: 16 }, meta), true);
  assert.equal(tocaMeta({ x: 100, y: 150, ancho: 12, alto: 16 }, meta), false);
  assert.equal(puntosMeta({ y: 50 }, meta), 5000);
  assert.equal(puntosMeta({ y: 100 }, meta), 2000);
  assert.equal(puntosMeta({ y: 150 }, meta), 400);
});

test("fin de nivel: bonus de tiempo, meta y victoria", async () => {
  const { terminarNivel } = await src("fin-nivel");
  const r = terminarNivel({ nivel: 0, niveles: ["a", "b"], puntos: 100, reloj: { segundos: 10, frames: 0 } });
  assert.equal(r.puntos, 600);
  assert.equal(r.estado, "meta");
  assert.equal(r.espera, 180);
  assert.equal(terminarNivel({ nivel: 1, niveles: ["a", "b"], puntos: 0, reloj: { segundos: 0, frames: 0 } }).estado,
    "victoria");
});

test("paso: llegar a la bandera pasa al nivel siguiente", async () => {
  const { crearPartida } = await src("partida");
  const { paso } = await src("paso");
  let p = crearPartida([".JF..\n#####\n", ".J...F\n######\n"]);
  for (let i = 0; i < 60 && p.estado === "jugando"; i++) p = paso(p, { derecha: true });
  assert.equal(p.estado, "meta");
  for (let i = 0; i < 200 && p.estado !== "jugando"; i++) p = paso(p, {});
  assert.equal(p.nivel, 1);
  assert.equal(p.estado, "jugando");
  assert.ok(p.puntos > 0);
});

test("pantallas: textos por estado", async () => {
  const { textoPantalla } = await src("pantallas");
  assert.equal(textoPantalla({ estado: "jugando" }), null);
  assert.deepEqual(textoPantalla({ estado: "pausa" }), ["PAUSA", "pulsa P para seguir"]);
  assert.deepEqual(textoPantalla({ estado: "fin" }), ["FIN DEL JUEGO", "pulsa Espacio"]);
  assert.deepEqual(textoPantalla({ estado: "muerto", nivel: 0, vidas: 2 }), ["MUNDO 1-1", "x 2"]);
  assert.deepEqual(textoPantalla({ estado: "victoria", puntos: 900 }), ["¡HAS GANADO!", "puntos 900", "pulsa Espacio"]);
});

test("control: pausa al pulsar (no al mantener) y reinicio desde el fin", async () => {
  const { controlar } = await src("control");
  assert.equal(controlar({ estado: "jugando" }, { pausa: true }, { pausa: false }).estado, "pausa");
  assert.equal(controlar({ estado: "pausa" }, { pausa: true }, { pausa: false }).estado, "jugando");
  assert.equal(controlar({ estado: "jugando" }, { pausa: true }, { pausa: true }).estado, "jugando");
  const r = controlar({ estado: "fin", niveles: DOS }, { saltar: true }, { saltar: false });
  assert.equal(r.estado, "jugando");
  assert.equal(r.vidas, 3);
});
