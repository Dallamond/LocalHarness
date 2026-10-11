// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("partida nueva y un paso", async () => {
  const { crearPartida, paso } = await src("src/serpiente.js");
  const p = crearPartida(10, 8);
  assert.deepEqual(p, { ancho: 10, alto: 8, cuerpo: [{ x: 2, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 0 }], dir: "derecha",
    comida: null, puntos: 0, estado: "jugando" });
  Object.freeze(p);
  assert.deepEqual(paso(p).cuerpo, [{ x: 3, y: 0 }, { x: 2, y: 0 }, { x: 1, y: 0 }]);
  assert.equal(p.cuerpo[0].x, 2);
});

test("girar, salvo a la contraria", async () => {
  const { crearPartida, girar, paso } = await src("src/serpiente.js");
  const p = crearPartida(10, 10);
  assert.equal(girar(p, "izquierda").dir, "derecha");
  assert.deepEqual(paso(girar(p, "abajo")).cuerpo[0], { x: 2, y: 1 });
});

test("comer crece y suma 10", async () => {
  const { crearPartida, ponerComida, paso } = await src("src/serpiente.js");
  const p = paso(ponerComida(crearPartida(10, 10), 3, 0));
  assert.equal(p.cuerpo.length, 4);
  assert.equal(p.puntos, 10);
  assert.equal(p.comida, null);
});

test("chocar con la pared o consigo misma acaba la partida", async () => {
  const { crearPartida, girar, paso } = await src("src/serpiente.js");
  let p = girar(crearPartida(4, 4), "arriba");
  assert.equal(paso(p).estado, "fin");
  p = { ...crearPartida(10, 10), dir: "abajo",
    cuerpo: [{ x: 5, y: 5 }, { x: 5, y: 6 }, { x: 4, y: 6 }, { x: 4, y: 5 }, { x: 4, y: 4 }] };
  assert.equal(paso(p).estado, "fin");
  const fin = paso(p);
  assert.equal(paso(fin), fin);
});

test("index.html y main.js montan el juego", () => {
  assert.match(leer("index.html"), /<canvas[^>]+id=["']tablero["']/);
  assert.match(leer("index.html"), /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?src\/main\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /from\s+["']\.\/serpiente\.js["']/);
  assert.match(main, /keydown/);
});
