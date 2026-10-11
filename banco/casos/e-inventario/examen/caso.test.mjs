// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("añadir suma y no modifica el original", async () => {
  const { crearInventario, anadir } = await src("src/inventario.js");
  assert.deepEqual(crearInventario(), {});
  const inv = Object.freeze({ a: 2 });
  assert.deepEqual(anadir(inv, "a", 3), { a: 5 });
  assert.deepEqual(anadir(inv, "b", 1), { a: 2, b: 1 });
  assert.deepEqual(inv, { a: 2 });
});

test("quitar resta y borra la clave al llegar a 0", async () => {
  const { quitar } = await src("src/inventario.js");
  const inv = Object.freeze({ a: 2, b: 5 });
  assert.deepEqual(quitar(inv, "b", 2), { a: 2, b: 3 });
  assert.deepEqual(quitar(inv, "a", 2), { b: 5 });
  assert.throws(() => quitar(inv, "a", 3), /no hay bastante/);
  assert.throws(() => quitar(inv, "z", 1), /no hay bastante/);
});

test("cantidades no válidas", async () => {
  const { anadir, quitar } = await src("src/inventario.js");
  for (const n of [0, -1, 1.5]) {
    assert.throws(() => anadir({}, "a", n), /cantidad no válida/);
    assert.throws(() => quitar({ a: 5 }, "a", n), /cantidad no válida/);
  }
});

test("total", async () => {
  const { total } = await src("src/inventario.js");
  assert.equal(total({}), 0);
  assert.equal(total({ a: 2, b: 5, c: 1 }), 8);
});
