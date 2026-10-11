// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("slug quita tildes, signos y espacios", async () => {
  const { slug } = await src("src/texto.js");
  assert.equal(slug("¡Hola, Señor Pérez!"), "hola-senor-perez");
  assert.equal(slug("  ya   está  "), "ya-esta");
  assert.equal(slug("Año 2026"), "ano-2026");
});

test("capitalizar cada palabra y conservar los espacios", async () => {
  const { capitalizar } = await src("src/texto.js");
  assert.equal(capitalizar("hOLA mundo"), "Hola Mundo");
  assert.equal(capitalizar("a  b"), "A  B");
});

test("truncar con puntos suspensivos y largo total n", async () => {
  const { truncar } = await src("src/texto.js");
  assert.equal(truncar("abcdef", 4), "abc…");
  assert.equal(truncar("abc", 3), "abc");
  assert.equal(truncar("abcd", 3), "ab…");
});
