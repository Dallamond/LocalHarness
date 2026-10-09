// Parches 1-4 de mario.md: mapa, rectángulos, física, cámara, niveles y colisiones.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { RAIZ, src, cuerpo } from "./ayuda.mjs";

test("mapa: crearMapa, esSolido por los bordes y columnaDe", async () => {
  const { crearMapa, esSolido, columnaDe, TILE } = await src("mapa");
  assert.equal(TILE, 16);
  const m = crearMapa(["..", "##"]);
  assert.equal(m.ancho, 2);
  assert.equal(m.alto, 2);
  assert.throws(() => crearMapa(["..", "#"]));
  assert.equal(esSolido(m, 0, 1), true);
  assert.equal(esSolido(m, 0, 0), false);
  assert.equal(esSolido(m, -1, 0), true);
  assert.equal(esSolido(m, 2, 0), true);
  assert.equal(esSolido(m, 0, -1), true);
  assert.equal(esSolido(m, 0, 2), false);
  assert.equal(columnaDe(15), 0);
  assert.equal(columnaDe(16), 1);
  assert.equal(columnaDe(-1), -1);
});

test("rect: solapan (tocarse no es solapar)", async () => {
  const { solapan } = await src("rect");
  const a = { x: 0, y: 0, ancho: 16, alto: 16 };
  assert.equal(solapan(a, { x: 8, y: 8, ancho: 16, alto: 16 }), true);
  assert.equal(solapan(a, { x: 16, y: 0, ancho: 16, alto: 16 }), false);
  assert.equal(solapan(a, { x: 0, y: 16, ancho: 16, alto: 16 }), false);
  assert.equal(solapan(a, { x: 4, y: 4, ancho: 4, alto: 4 }), true);
  assert.equal(solapan(a, { x: 40, y: 40, ancho: 4, alto: 4 }), false);
});

test("física: aplicarGravedad con tope y sin tocar el original", async () => {
  const { aplicarGravedad, GRAVEDAD, VEL_MAX_CAIDA } = await src("fisica");
  assert.equal(GRAVEDAD, 0.5);
  assert.equal(VEL_MAX_CAIDA, 8);
  assert.equal(aplicarGravedad({ vy: 0 }).vy, 0.5);
  assert.equal(aplicarGravedad({ vy: 7.8 }).vy, 8);
  assert.equal(aplicarGravedad({ vy: 8 }).vy, 8);
  assert.equal(aplicarGravedad({ vy: -8.5 }).vy, -8);
  const o = { x: 1, vy: 2 };
  const n = aplicarGravedad(o);
  assert.notEqual(n, o);
  assert.equal(o.vy, 2);
  assert.equal(n.x, 1);
});

test("cámara: camaraX y rangoColumnas", async () => {
  const { camaraX, rangoColumnas } = await src("camara");
  assert.equal(camaraX(100, 896), 0);
  assert.equal(camaraX(500, 896), 372);
  assert.equal(camaraX(890, 896), 640);
  assert.equal(camaraX(150, 200), 0);
  assert.deepEqual(rangoColumnas(0), { desde: 0, hasta: 15 });
  assert.deepEqual(rangoColumnas(372), { desde: 23, hasta: 39 });
});

test("nivel: parsearNivel saca J, o, E, K y F y los quita del mapa", async () => {
  const { parsearNivel } = await src("nivel");
  const n = parsearNivel("....\n.Jo.\n##F#\n");
  assert.deepEqual(n.inicio, { x: 16, y: 16 });
  assert.deepEqual(n.monedas, [{ x: 32, y: 16 }]);
  assert.deepEqual(n.meta, { x: 32, y: 32 });
  assert.deepEqual(n.mapa.tiles, ["....", "....", "##.#"]);
  assert.deepEqual(parsearNivel(".E..\n.Jo.\n##F#\n").enemigos, [{ tipo: "goomba", x: 16, y: 0 }]);
  assert.equal(parsearNivel(".K..\n.Jo.\n##F#\n").enemigos[0].tipo, "koopa");
  assert.throws(() => parsearNivel("....\n..o.\n##F#\n"), /falta J/);
});

test("niveles: los dos diseños copiados carácter a carácter y sin Node", async () => {
  const { NIVELES } = await src("niveles");
  assert.ok(NIVELES.length >= 2);
  for (const [i, f] of [[0, "docs/nivel-1.txt"], [1, "docs/nivel-2.txt"]]) {
    const limpio = (t) => t.replace(/\r/g, "").split("\n").map((l) => l.trim()).filter(Boolean).join("\n");
    assert.equal(limpio(NIVELES[i]), limpio(readFileSync(join(RAIZ, f), "utf8")), `nivel ${i + 1}`);
  }
  assert.doesNotMatch(readFileSync(join(RAIZ, "src/niveles.js"), "utf8"), /readFileSync|node:fs/);
});

test("colisiones: moverX contra paredes y en libre", async () => {
  const { crearMapa } = await src("mapa");
  const { moverX } = await src("colision-x");
  const m = crearMapa(["......", "......", "..#...", "######"]);
  let c = moverX(cuerpo({ x: 14, y: 32, vx: 3 }), m);
  assert.equal(c.x, 16);
  assert.equal(c.vx, 0);
  c = moverX(cuerpo({ x: 49, y: 32, vx: -3 }), m);
  assert.equal(c.x, 48);
  assert.equal(c.vx, 0);
  const o = cuerpo({ x: 0, y: 0, vx: 3 });
  c = moverX(o, m);
  assert.equal(c.x, 3);
  assert.equal(c.vx, 3);
  assert.equal(o.x, 0);
});

test("colisiones: moverY suelo, techo, hueco y esquina", async () => {
  const { crearMapa } = await src("mapa");
  const { moverY } = await src("colision-y");
  const suelo = crearMapa(["......", "......", "......", "######"]);
  let r = moverY(cuerpo({ x: 0, y: 30, vy: 4 }), suelo);
  assert.equal(r.cuerpo.y, 32);
  assert.equal(r.cuerpo.vy, 0);
  assert.equal(r.cuerpo.enSuelo, true);
  r = moverY(cuerpo({ x: 0, y: 0, vy: 4 }), suelo);
  assert.equal(r.cuerpo.y, 4);
  assert.equal(r.cuerpo.enSuelo, false);
  r = moverY(cuerpo({ x: 16, y: 20, vy: -6 }), crearMapa(["###", "...", "..."]));
  assert.equal(r.cuerpo.y, 16);
  assert.equal(r.cuerpo.vy, 0);
  assert.deepEqual(r.golpeTecho, { columna: 1, fila: 0 });
  const hueco = crearMapa(["....", "....", "#..#"]);
  r = moverY(cuerpo({ x: 16, y: 20, vy: 6 }), hueco);
  assert.equal(r.cuerpo.y, 26);
  assert.equal(r.cuerpo.enSuelo, false);
  r = moverY(cuerpo({ x: 8, y: 20, vy: 6 }), hueco);
  assert.equal(r.cuerpo.y, 16);
  assert.equal(r.cuerpo.enSuelo, true);
});
