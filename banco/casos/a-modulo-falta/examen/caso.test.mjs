// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa", () => verde(5));

test("tic cuenta frames y baja un segundo cada 60", async () => {
  verde(5);
  const { crearReloj, tic } = await src("src/reloj.js");
  let r = crearReloj(10);
  for (let i = 0; i < 59; i++) r = tic(r);
  assert.deepEqual(r, { segundos: 10, frames: 59 });
  assert.deepEqual(tic(r), { segundos: 9, frames: 0 });
});

test("el reloj no baja de 0 ni modifica el que recibe", async () => {
  verde(5);
  const { tic } = await src("src/reloj.js");
  assert.deepEqual(tic({ segundos: 0, frames: 0 }), { segundos: 0, frames: 0 });
  const r = Object.freeze({ segundos: 5, frames: 3 });
  assert.deepEqual(tic(r), { segundos: 5, frames: 4 });
});
