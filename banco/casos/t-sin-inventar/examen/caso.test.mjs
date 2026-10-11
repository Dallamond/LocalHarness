// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

const BUENO = "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;\n  return mejor;\n}\n";
test("tus tests aceptan otra versi\u00f3n correcta: una que, si empatan, devuelve la \u00faltima", () => {
  const r = testsDelProyecto({ "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha <= mejor.fecha)) mejor = c;\n  return mejor;\n}\n" });
  assert.ok(r.ok && r.tests >= 5, "tus tests prueban algo que el comentario no fija:\n" + r.salida.slice(-800));
});
test("tus tests aceptan otra versi\u00f3n correcta: una que devuelve una copia de la cita", () => {
  const r = testsDelProyecto({ "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;\n  return mejor && { ...mejor };\n}\n" });
  assert.ok(r.ok && r.tests >= 5, "tus tests prueban algo que el comentario no fija:\n" + r.salida.slice(-800));
});
test("tus tests aceptan otra versi\u00f3n correcta: una que rechaza lo que no es una lista", () => {
  const r = testsDelProyecto({ "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  if (!Array.isArray(citas)) throw new TypeError(\"citas\");\n  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;\n  return mejor;\n}\n" });
  assert.ok(r.ok && r.tests >= 5, "tus tests prueban algo que el comentario no fija:\n" + r.salida.slice(-800));
});
test("tus tests pillan: deja fuera la cita que es justo ahora", () => {
  pilla({ "src/agenda.js": BUENO }, { "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  let mejor = null;\n  for (const c of citas) if (c.fecha > ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;\n  return mejor;\n}\n" }, 5);
});
test("tus tests pillan: devuelve la m\u00e1s tard\u00eda", () => {
  pilla({ "src/agenda.js": BUENO }, { "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha > mejor.fecha)) mejor = c;\n  return mejor;\n}\n" }, 5);
});
test("tus tests pillan: da por hecho que la lista viene ordenada", () => {
  pilla({ "src/agenda.js": BUENO }, { "src/agenda.js": "// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha m\u00e1s\n// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.\nexport function proximaCita(citas, ahora) {\n  return citas.find((c) => c.fecha >= ahora) ?? null;\n}\n" }, 5);
});
