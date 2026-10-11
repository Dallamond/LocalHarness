// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa", () => verde(5));

test("buscar encuentra y devuelve null si no está", async () => {
  verde(5);
  const { buscar } = await src("src/tablas.js");
  assert.equal(buscar(300).id, 300);
  assert.equal(buscar(0), null);
  assert.equal(buscar(301), null);
});

test("el catálogo y las otras consultas siguen igual", async () => {
  verde(5);
  const { PRODUCTOS, caros, totalStock, porCategoria } = await src("src/tablas.js");
  assert.equal(PRODUCTOS.length, 300);
  for (let i = 1; i <= 300; i++) {
    const p = PRODUCTOS[i - 1];
    assert.deepEqual(p, { id: i, nombre: `producto-${String(i).padStart(3, "0")}`, precio: ((i * 37) % 1000) + 100,
      stock: (i * 13) % 50, categoria: "abc"[i % 3] });
  }
  let stock = 0;
  for (let i = 1; i <= 300; i++) stock += (i * 13) % 50;
  assert.equal(totalStock(), stock);
  assert.equal(porCategoria("a"), 100);
  assert.deepEqual(caros(1098), PRODUCTOS.filter((p) => p.precio >= 1098).map((p) => p.id));
});
