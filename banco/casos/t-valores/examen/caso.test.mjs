// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

const BUENO = "// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o m\u00e1s, 15 %.\n// totalConDescuento(unidades, precioCent) = Math.round(unidades \u00d7 precioCent \u00d7 (100 \u2212 porcentaje) / 100).\nexport function porcentaje(unidades) {\n  if (unidades >= 100) return 15;\n  if (unidades >= 50) return 10;\n  if (unidades >= 10) return 5;\n  return 0;\n}\n\nexport function totalConDescuento(unidades, precioCent) {\n  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);\n}\n";
test("tus tests pillan: el borde de 10 unidades", () => {
  pilla({ "src/descuento.js": BUENO }, { "src/descuento.js": "// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o m\u00e1s, 15 %.\n// totalConDescuento(unidades, precioCent) = Math.round(unidades \u00d7 precioCent \u00d7 (100 \u2212 porcentaje) / 100).\nexport function porcentaje(unidades) {\n  if (unidades >= 100) return 15;\n  if (unidades >= 50) return 10;\n  if (unidades > 10) return 5;\n  return 0;\n}\n\nexport function totalConDescuento(unidades, precioCent) {\n  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);\n}\n" }, 5);
});
test("tus tests pillan: el tramo de 100 da 12 % en vez de 15 %", () => {
  pilla({ "src/descuento.js": BUENO }, { "src/descuento.js": "// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o m\u00e1s, 15 %.\n// totalConDescuento(unidades, precioCent) = Math.round(unidades \u00d7 precioCent \u00d7 (100 \u2212 porcentaje) / 100).\nexport function porcentaje(unidades) {\n  if (unidades >= 100) return 12;\n  if (unidades >= 50) return 10;\n  if (unidades >= 10) return 5;\n  return 0;\n}\n\nexport function totalConDescuento(unidades, precioCent) {\n  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);\n}\n" }, 5);
});
test("tus tests pillan: redondea hacia abajo", () => {
  pilla({ "src/descuento.js": BUENO }, { "src/descuento.js": "// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o m\u00e1s, 15 %.\n// totalConDescuento(unidades, precioCent) = Math.round(unidades \u00d7 precioCent \u00d7 (100 \u2212 porcentaje) / 100).\nexport function porcentaje(unidades) {\n  if (unidades >= 100) return 15;\n  if (unidades >= 50) return 10;\n  if (unidades >= 10) return 5;\n  return 0;\n}\n\nexport function totalConDescuento(unidades, precioCent) {\n  return Math.floor((unidades * precioCent * (100 - porcentaje(unidades))) / 100);\n}\n" }, 5);
});
test("tus tests pillan: el tramo de 50 empieza en 51", () => {
  pilla({ "src/descuento.js": BUENO }, { "src/descuento.js": "// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o m\u00e1s, 15 %.\n// totalConDescuento(unidades, precioCent) = Math.round(unidades \u00d7 precioCent \u00d7 (100 \u2212 porcentaje) / 100).\nexport function porcentaje(unidades) {\n  if (unidades >= 100) return 15;\n  if (unidades >= 51) return 10;\n  if (unidades >= 10) return 5;\n  return 0;\n}\n\nexport function totalConDescuento(unidades, precioCent) {\n  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);\n}\n" }, 5);
});
