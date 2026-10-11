// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("el movimiento sigue igual y la firma también", async () => {
  verde(4);
  const { crearEstado, paso } = await src("src/paso.js");
  assert.equal(paso.length, 2);
  let e = crearEstado();
  assert.equal(e.pausado, false);
  e = paso(e, { derecha: true });
  e = paso(e, { derecha: true });
  assert.deepEqual([e.x, e.vx], [4, 2]);
  assert.deepEqual([paso(e, { derecha: true, izquierda: true }).x, paso(e, {}).vx], [4, 0]);
});

test("pulsar alterna la pausa; mantener no", async () => {
  const { crearEstado, paso } = await src("src/paso.js");
  let e = paso(crearEstado(), { pausa: true });
  assert.equal(e.pausado, true);
  e = paso(e, { pausa: true });
  assert.equal(e.pausado, true);
  e = paso(e, {});
  assert.equal(e.pausado, true);
  e = paso(e, { pausa: true });
  assert.equal(e.pausado, false);
});

test("pausado no se mueve", async () => {
  const { crearEstado, paso } = await src("src/paso.js");
  let e = paso(paso(crearEstado(), { derecha: true }), { pausa: true, derecha: true });
  assert.equal(e.pausado, true);
  const x = e.x;
  e = paso(e, { derecha: true });
  e = paso(e, { derecha: true });
  assert.equal(e.x, x);
  e = paso(paso(e, { pausa: true }), { derecha: true });
  assert.equal(e.pausado, false);
  assert.equal(e.x, x + 2);
});
