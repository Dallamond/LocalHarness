// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("convertir entre monedas", async () => {
  const { convertir, TASAS } = await src("src/divisas.js");
  assert.deepEqual(TASAS, { EUR: 1, USD: 1.1, GBP: 0.85 });
  assert.equal(convertir(1000, "EUR", "USD"), 1100);
  assert.equal(convertir(1100, "USD", "EUR"), 1000);
  assert.equal(convertir(850, "GBP", "USD"), 1100);
  assert.throws(() => convertir(1, "EUR", "JPY"), /moneda desconocida/);
});

test("totalFacturaEn y resumenEn convierten el total", async () => {
  const { totalFacturaEn, totalFactura } = await src("src/factura.js");
  const { resumenEn, resumen } = await src("src/resumen.js");
  assert.equal(totalFactura([{ precio: 500, cantidad: 3 }]), 1500);
  assert.equal(totalFacturaEn([{ precio: 500, cantidad: 3 }], "USD"), 1650);
  assert.deepEqual(resumen([[{ precio: 100, cantidad: 1 }], []]), { numero: 2, total: 100 });
  assert.deepEqual(resumenEn([[{ precio: 500, cantidad: 1 }], [{ precio: 250, cantidad: 2 }]], "GBP"),
    { numero: 2, total: 850 });
});

test("las tasas viven solo en divisas.js y se importan de ahí", () => {
  verde(3);
  for (const f of ["src/factura.js", "src/resumen.js"]) {
    const t = leer(f);
    assert.doesNotMatch(t, /0\.85|1\.1\b/, f);
  }
  assert.match(leer("src/factura.js"), /from\s+["']\.\/divisas\.js["']/);
});
