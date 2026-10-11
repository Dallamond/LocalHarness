// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("formatearEuros existe y formatear ya no", async () => {
  verde(4);
  const m = await src("src/dinero.js");
  assert.equal(m.formatearEuros(1234), "12,34 €");
  assert.equal(m.formatear, undefined);
});

test("ticket e informe dan lo mismo que antes", async () => {
  verde(4);
  const { lineaTicket } = await src("src/ticket.js");
  const { informe } = await src("src/informe.js");
  assert.equal(lineaTicket("café", 150), "café: 1,50 €");
  assert.equal(informe([{ nombre: "a", centimos: 100 }, { nombre: "b", centimos: 250 }]), "a: 1,00 €\nb: 2,50 €\nTOTAL 3,50 €");
});

test("no queda el nombre viejo en ningún archivo", () => {
  for (const f of ["src/dinero.js", "src/ticket.js", "src/informe.js", "tests/dinero.test.mjs", "tests/ticket.test.mjs"]) {
    if (existe(f)) assert.doesNotMatch(leer(f), /\bformatear\b/, f);
  }
});
