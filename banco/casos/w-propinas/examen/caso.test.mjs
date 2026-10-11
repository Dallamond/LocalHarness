// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("calcular propina, total y por persona", async () => {
  const { calcular } = await src("src/propinas.js");
  assert.deepEqual(calcular(5000, 10, 3), { propina: 500, total: 5500, porPersona: 1834 });
  assert.deepEqual(calcular(1999, 15, 1), { propina: 300, total: 2299, porPersona: 2299 });
  assert.throws(() => calcular(1000, 10, 0), /personas no válidas/);
});

test("euros con miles y coma", async () => {
  const { euros } = await src("src/formato.js");
  assert.equal(euros(123450), "1.234,50 €");
  assert.equal(euros(5), "0,05 €");
  assert.equal(euros(0), "0,00 €");
  assert.equal(euros(100000000), "1.000.000,00 €");
});

test("la vista pinta los tres párrafos", async () => {
  const { vista } = await src("src/vista.js");
  const html = vista({ propina: 500, total: 5500, porPersona: 1834 });
  assert.ok(html.includes('<p class="propina">Propina: 5,00 €</p>'), html);
  assert.ok(html.includes('<p class="total">Total: 55,00 €</p>'), html);
  assert.ok(html.includes('<p class="por-persona">Cada uno: 18,34 €</p>'), html);
});

test("index.html y main.js montan la página", () => {
  const html = leer("index.html");
  for (const id of ["cuenta", "porcentaje", "personas", "resultado"]) assert.match(html, new RegExp(`id=["']${id}["']`), id);
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?src\/main\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /from\s+["']\.\/vista\.js["']/);
  assert.match(main, /from\s+["']\.\/propinas\.js["']/);
  assert.match(main, /resultado/);
});
