"""Genera banco/casos/<caso>/ (caso.json, encargo.md, semilla/, referencia/, examen/) y banco/repertorios/basico.json.

Los casos son pruebas cortas (un parche, 1-5 min) que apuntan cada una a un fallo concreto visto en el banco. Este
script es la fuente: si cambias un caso, cámbialo aquí y vuelve a correrlo (`python banco/casos/_generar.py`).
Cada examen tiene que dar 100 a la referencia (semilla + referencia encima) y menos de 100 a la semilla: lo comprueba
tests/test_casos.py.
"""
import json
import shutil
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPERTORIOS = AQUI.parent / "repertorios"

# ---------------------------------------------------------------- base común (va debajo de cada semilla)
COMUN = {
    "package.json": json.dumps({"name": "caso", "private": True, "type": "module",
                                "scripts": {"test": "node --test"}}, indent=2) + "\n",
    ".gitignore": "node_modules/\n",
    "CHANGELOG.md": "# Changelog\n\n- Parche 000 · 11/10/2026 · Semilla del caso.\n",
    "ENCARGO.md": """# Encargo

Proyecto pequeño en JavaScript con módulos ES y sin dependencias.

## Reglas
1. El código va en `src/`. Nombres de funciones, variables y comentarios en castellano (sin ñ en los
   identificadores: `anadir`).
2. Las funciones son puras (salvo `src/main.js`, que es la única que toca el navegador): reciben datos y devuelven
   datos NUEVOS, sin modificar lo que reciben.
3. Los tests van en `tests/*.test.mjs` y usan solo `node:test` y `node:assert/strict`. `npm test` tiene que pasar.
4. No cambies la firma de una función que ya existe. No borres un test que comprueba lo que pide la especificación.
5. `CHANGELOG.md` lleva una línea por parche: `- Parche NNN · DD/MM/AAAA · qué cambió`.
""",
    "tests/proyecto.test.mjs": """import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

test("el proyecto tiene encargo y changelog", () => {
  assert.ok(existsSync("ENCARGO.md"));
  assert.ok(existsSync("CHANGELOG.md"));
});

test("cada línea del CHANGELOG lleva número, fecha y descripción", () => {
  const lineas = readFileSync("CHANGELOG.md", "utf8").split("\\n").filter((l) => l.startsWith("- Parche"));
  for (const l of lineas) assert.match(l, /^- Parche \\d{3} · \\d{2}\\/\\d{2}\\/\\d{4} · .+/, l);
});
""",
}

# ayuda de los exámenes: importa del proyecto examinado y corre sus tests en una copia (con archivos cambiados)
AYUDA = r'''// Ayuda de los exámenes de los casos (banco/casos/*/examen): se corren con PROYECTO=<ruta> (banco/puntuar.mjs).
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const RAIZ = process.env.PROYECTO;
if (!RAIZ) throw new Error("falta PROYECTO=<ruta del proyecto>");

let vez = 0;
/** Importa un módulo del proyecto (ruta relativa, p. ej. "src/precio.js"); si no carga, el test que lo usa falla. */
export const src = (ruta) => import(`${pathToFileURL(join(RAIZ, ruta)).href}?v=${vez++}`);
export const leer = (ruta) => readFileSync(join(RAIZ, ruta), "utf8");
export const existe = (ruta) => existsSync(join(RAIZ, ruta));

/** Copia el proyecto, cambia los archivos de `cambios` ({ruta: texto}) y corre `node --test`: {ok, tests, salida}. */
export function testsDelProyecto(cambios = {}) {
  const dir = mkdtempSync(join(tmpdir(), "caso-"));
  try {
    cpSync(RAIZ, dir, { recursive: true, filter: (s) => !/[\\/](\.git|node_modules)([\\/]|$)/.test(s) });
    for (const [ruta, texto] of Object.entries(cambios)) writeFileSync(join(dir, ruta), texto);
    // sin NODE_TEST_CONTEXT: dentro de un test, el `node --test` hijo se cree parte del runner y no da su resumen
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT;
    const p = spawnSync(process.execPath, ["--test"], { cwd: dir, env, encoding: "utf8", timeout: 120000 });
    const m = /ℹ tests (\d+)/.exec(p.stdout || "");
    return { ok: p.status === 0, tests: m ? Number(m[1]) : 0, salida: `${p.stdout || ""}${p.stderr || ""}` };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

let cache = null;
/** Los tests del proyecto, tal cual, pasan y son al menos `minimo` (incluidos los 2 de proyecto.test.mjs). */
export function verde(minimo) {
  cache ??= testsDelProyecto();
  if (!cache.ok) throw new Error(`npm test falla en el proyecto:\n${cache.salida.slice(-1500)}`);
  if (cache.tests < minimo) throw new Error(`solo hay ${cache.tests} tests (se esperan al menos ${minimo})`);
}

/** Con el código bueno los tests del proyecto pasan (y hay al menos `minimo`) y con el mutante fallan. */
export function pilla(bueno, mutante, minimo) {
  const b = testsDelProyecto(bueno);
  if (!b.ok) throw new Error(`con el código bueno tus tests fallan:\n${b.salida.slice(-1200)}`);
  if (b.tests < minimo) throw new Error(`solo hay ${b.tests} tests (se esperan al menos ${minimo})`);
  const m = testsDelProyecto(mutante);
  if (m.ok) throw new Error("tus tests no pillan este fallo");
}
'''

T = "import { test } from \"node:test\";\nimport assert from \"node:assert/strict\";\n"
H = 'import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";\n'


def ex(cuerpo: str) -> str:
    return "// Examen oculto: los modelos no lo ven.\n" + T + H + "\n" + cuerpo.strip() + "\n"


CASOS: dict[str, dict] = {}


def caso(nombre, titulo, grupo, tipo, encargo, semilla=None, referencia=None, examen="", abrir="index.html",
         descripcion=""):
    CASOS[nombre] = {"titulo": titulo, "grupo": grupo, "tipo": tipo, "encargo": " ".join(encargo.split()),
                     "semilla": semilla or {}, "referencia": referencia or {}, "examen": ex(examen), "abrir": abrir,
                     "descripcion": descripcion}


# ================================================================ ESCRIBIR DESDE LA ESPECIFICACIÓN
PRECIO = r'''// Precio final en céntimos: primero el descuento (entre 0 y 50 %), luego el IVA; cada paso, al céntimo.
const MAX_DESCUENTO = 50;

export function desglose(base, ivaPct, descuentoPct) {
  if (base < 0) throw new Error("base negativa");
  const pct = Math.min(Math.max(descuentoPct, 0), MAX_DESCUENTO);
  const descuento = Math.round((base * pct) / 100);
  const neto = base - descuento;
  const iva = Math.round((neto * ivaPct) / 100);
  return { base, descuento, neto, iva, total: neto + iva };
}

export function precioFinal(base, ivaPct, descuentoPct) {
  return desglose(base, ivaPct, descuentoPct).total;
}
'''
caso("e-precio", "Precio con descuento e IVA", "escribir", "logica", """
Crea src/precio.js con dos funciones (importes en céntimos enteros). desglose(base, ivaPct, descuentoPct) devuelve
{base, descuento, neto, iva, total}: el descuento se aplica primero y su porcentaje se limita entre 0 y 50 (más de 50
cuenta como 50; negativo, como 0); descuento = Math.round(base × pct / 100); neto = base − descuento;
iva = Math.round(neto × ivaPct / 100); total = neto + iva. Si base es negativa lanza Error('base negativa').
precioFinal(base, ivaPct, descuentoPct) devuelve solo el total. Añade tests/precio.test.mjs con casos concretos.""",
     referencia={"src/precio.js": PRECIO, "tests/precio.test.mjs": T + '''import { precioFinal, desglose } from "../src/precio.js";

test("precio final con descuento e IVA", () => {
  assert.equal(precioFinal(1000, 21, 10), 1089); // 1000 - 100 = 900; 900 * 0,21 = 189
  assert.deepEqual(desglose(1000, 21, 10), { base: 1000, descuento: 100, neto: 900, iva: 189, total: 1089 });
});
'''}, examen='''
test("precioFinal: descuento primero, luego IVA, cada paso al céntimo", async () => {
  const { precioFinal } = await src("src/precio.js");
  assert.equal(precioFinal(1000, 21, 10), 1089);
  assert.equal(precioFinal(999, 21, 0), 1209);
  assert.equal(precioFinal(1234, 10, 15), 1154);
});

test("desglose devuelve todas las piezas", async () => {
  const { desglose } = await src("src/precio.js");
  assert.deepEqual(desglose(1000, 21, 10), { base: 1000, descuento: 100, neto: 900, iva: 189, total: 1089 });
  assert.deepEqual(desglose(0, 21, 10), { base: 0, descuento: 0, neto: 0, iva: 0, total: 0 });
});

test("el descuento se limita entre 0 y 50", async () => {
  const { precioFinal } = await src("src/precio.js");
  assert.equal(precioFinal(1000, 21, 80), 605);
  assert.equal(precioFinal(1000, 21, -5), 1210);
});

test("base negativa lanza error", async () => {
  const { precioFinal, desglose } = await src("src/precio.js");
  assert.throws(() => precioFinal(-1, 21, 0), /base negativa/);
  assert.throws(() => desglose(-100, 21, 0), /base negativa/);
});
''')

TEXTO = r'''// Utilidades de texto.
export function slug(s) {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function capitalizar(s) {
  return s
    .split(" ")
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1).toLowerCase() : p))
    .join(" ");
}

export function truncar(s, n) {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}
'''
caso("e-texto", "Utilidades de texto", "escribir", "logica", """
Crea src/texto.js con tres funciones. slug(s): quita las tildes (á → a, ñ → n), pasa a minúsculas, cambia cada
tramo de caracteres que no sean a-z o 0-9 por un solo guion y quita los guiones del principio y del final
(slug('¡Hola, Señor Pérez!') = 'hola-senor-perez'). capitalizar(s): cada palabra (separadas por espacios, que se
conservan tal cual) con la primera letra en mayúscula y el resto en minúscula ('hOLA mundo' → 'Hola Mundo').
truncar(s, n): si s tiene n caracteres o menos la devuelve igual; si no, los n − 1 primeros y '…' (largo total n).
Añade tests/texto.test.mjs.""",
     referencia={"src/texto.js": TEXTO, "tests/texto.test.mjs": T + '''import { slug, truncar } from "../src/texto.js";

test("slug y truncar", () => {
  assert.equal(slug("¡Hola, Señor Pérez!"), "hola-senor-perez");
  assert.equal(truncar("abcdef", 4), "abc…");
});
'''}, examen='''
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
''')

INVENTARIO = r'''// Inventario: {sku: unidades}. Las funciones devuelven un inventario nuevo, sin tocar el que reciben.
export function crearInventario() {
  return {};
}

function comprobar(n) {
  if (!Number.isInteger(n) || n <= 0) throw new Error("cantidad no válida");
}

export function anadir(inv, sku, n) {
  comprobar(n);
  return { ...inv, [sku]: (inv[sku] ?? 0) + n };
}

export function quitar(inv, sku, n) {
  comprobar(n);
  const hay = inv[sku] ?? 0;
  if (hay < n) throw new Error("no hay bastante");
  const nuevo = { ...inv };
  if (hay === n) delete nuevo[sku];
  else nuevo[sku] = hay - n;
  return nuevo;
}

export function total(inv) {
  return Object.values(inv).reduce((a, b) => a + b, 0);
}
'''
caso("e-inventario", "Inventario sin mutar", "escribir", "logica", """
Crea src/inventario.js. Un inventario es un objeto {sku: unidades}. crearInventario() devuelve {}.
anadir(inv, sku, n) devuelve un inventario NUEVO con n unidades más de ese sku. quitar(inv, sku, n) devuelve uno nuevo
con n menos; si se queda en 0, la clave desaparece; si no hay bastantes lanza Error('no hay bastante'). En las dos,
si n no es un entero mayor que 0 lanza Error('cantidad no válida'). total(inv) es la suma de todas las unidades.
Ninguna función modifica el inventario que recibe. Añade tests/inventario.test.mjs.""",
     referencia={"src/inventario.js": INVENTARIO, "tests/inventario.test.mjs": T + '''import { anadir, total } from "../src/inventario.js";

test("añadir y total", () => {
  assert.equal(total(anadir({ a: 1 }, "b", 2)), 3);
});
'''}, examen='''
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
''')

# ================================================================ TESTS
DESCUENTO = r'''// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o más, 15 %.
// totalConDescuento(unidades, precioCent) = Math.round(unidades × precioCent × (100 − porcentaje) / 100).
export function porcentaje(unidades) {
  if (unidades >= 100) return 15;
  if (unidades >= 50) return 10;
  if (unidades >= 10) return 5;
  return 0;
}

export function totalConDescuento(unidades, precioCent) {
  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);
}
'''
DESCUENTO_MUT = {
    "el borde de 10 unidades": DESCUENTO.replace("unidades >= 10) return 5", "unidades > 10) return 5"),
    "el tramo de 100 da 12 % en vez de 15 %": DESCUENTO.replace("return 15;", "return 12;"),
    "redondea hacia abajo": DESCUENTO.replace("return Math.round(", "return Math.floor("),
    "el tramo de 50 empieza en 51": DESCUENTO.replace("unidades >= 50) return 10", "unidades >= 51) return 10"),
}
caso("t-valores", "Tests con valores calculados", "tests", "logica", """
src/descuento.js ya está hecho y es correcto: no lo cambies. Escribe tests/descuento.test.mjs (node:test y
node:assert/strict) que lo comprueben de verdad: los bordes de cada tramo (9, 10, 49, 50, 99 y 100 unidades) y algún
total donde el redondeo importe. Calcula tú cada valor esperado con la regla del comentario del archivo.""",
     semilla={"src/descuento.js": DESCUENTO},
     referencia={"tests/descuento.test.mjs": T + '''import { porcentaje, totalConDescuento } from "../src/descuento.js";

test("bordes de cada tramo", () => {
  const casos = [[9, 0], [10, 5], [49, 5], [50, 10], [99, 10], [100, 15]];
  for (const [u, pct] of casos) assert.equal(porcentaje(u), pct, String(u));
});

test("totales", () => {
  assert.equal(totalConDescuento(5, 100), 500);
  assert.equal(totalConDescuento(100, 200), 17000); // 20000 × 85 / 100
});

test("el redondeo importa", () => {
  assert.equal(totalConDescuento(10, 333), 3164); // 3330 × 95 / 100 = 3163,5 → 3164
});
'''}, examen="\n".join(
        [f"const BUENO = {json.dumps(DESCUENTO)};"]
        + [f'test({json.dumps("tus tests pillan: " + k)}, () => {{\n  pilla({{ "src/descuento.js": BUENO }}, '
           f'{{ "src/descuento.js": {json.dumps(v)} }}, 5);\n}});' for k, v in DESCUENTO_MUT.items()]))

AGENDA = r'''// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha más
// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.
export function proximaCita(citas, ahora) {
  let mejor = null;
  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;
  return mejor;
}
'''
AGENDA_VALIDAS = {
    "una que, si empatan, devuelve la última": AGENDA.replace("c.fecha < mejor.fecha", "c.fecha <= mejor.fecha"),
    "una que devuelve una copia de la cita": AGENDA.replace("return mejor;", "return mejor && { ...mejor };"),
    "una que rechaza lo que no es una lista": AGENDA.replace(
        "  let mejor = null;", '  if (!Array.isArray(citas)) throw new TypeError("citas");\n  let mejor = null;'),
}
AGENDA_MUT = {
    "deja fuera la cita que es justo ahora": AGENDA.replace("c.fecha >= ahora", "c.fecha > ahora"),
    "devuelve la más tardía": AGENDA.replace("c.fecha < mejor.fecha", "c.fecha > mejor.fecha"),
    "da por hecho que la lista viene ordenada": AGENDA.replace(
        "  let mejor = null;\n  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;\n  return mejor;",
        "  return citas.find((c) => c.fecha >= ahora) ?? null;"),
}
caso("t-sin-inventar", "Tests sin inventar casos", "tests", "logica", """
src/agenda.js ya está hecho y es correcto: no lo cambies. Escribe tests/agenda.test.mjs que comprueben lo que dice
el comentario de proximaCita, y solo eso: no pruebes comportamientos que el comentario no fija.""",
     semilla={"src/agenda.js": AGENDA},
     referencia={"tests/agenda.test.mjs": T + '''import { proximaCita } from "../src/agenda.js";

const citas = [
  { titulo: "dentista", fecha: "2026-10-20T10:00" },
  { titulo: "clase", fecha: "2026-10-12T09:00" },
  { titulo: "cena", fecha: "2026-10-15T21:00" },
];

test("la más temprana desde ahora, aunque la lista esté desordenada", () => {
  assert.deepEqual(proximaCita(citas, "2026-10-13T00:00"), { titulo: "cena", fecha: "2026-10-15T21:00" });
});

test("una cita justo a la hora de ahora cuenta", () => {
  assert.equal(proximaCita(citas, "2026-10-12T09:00").titulo, "clase");
});

test("null si no queda ninguna", () => {
  assert.equal(proximaCita(citas, "2026-11-01T00:00"), null);
  assert.equal(proximaCita([], "2026-01-01T00:00"), null);
});
'''}, examen="\n".join(
        [f"const BUENO = {json.dumps(AGENDA)};"]
        + [f'test({json.dumps("tus tests aceptan otra versión correcta: " + k)}, () => {{\n  const r = '
           f'testsDelProyecto({{ "src/agenda.js": {json.dumps(v)} }});\n  assert.ok(r.ok && r.tests >= 5, '
           f'"tus tests prueban algo que el comentario no fija:\\n" + r.salida.slice(-800));\n}});'
           for k, v in AGENDA_VALIDAS.items()]
        + [f'test({json.dumps("tus tests pillan: " + k)}, () => {{\n  pilla({{ "src/agenda.js": BUENO }}, '
           f'{{ "src/agenda.js": {json.dumps(v)} }}, 5);\n}});' for k, v in AGENDA_MUT.items()]))

RELOJ_FMT = r'''// formatear(segundos) → 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') → segundos.
export function formatear(segundos) {
  const m = Math.floor(segundos / 60);
  const s = segundos % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function aSegundos(texto) {
  const [m, s] = texto.split(":").map(Number);
  return m * 60 + s;
}
'''
RELOJ_MUT = {
    "sin ceros delante": RELOJ_FMT.replace('String(m).padStart(2, "0")', "String(m)").replace(
        'String(s).padStart(2, "0")', "String(s)"),
    "minutos de 100 segundos": RELOJ_FMT.replace("return m * 60 + s;", "return m * 100 + s;"),
    "segundos sin el resto de 60": RELOJ_FMT.replace("segundos % 60", "segundos % 100"),
}
caso("t-jest", "Tests de Jest a node:test", "tests", "logica", """
npm test falla: tests/reloj.test.mjs está escrito para Jest (describe, it, expect) y aquí los tests usan node:test y
node:assert/strict. Pásalo a node:test sin perder ningún caso. src/reloj.js es correcto: no lo cambies.""",
     semilla={"src/reloj.js": RELOJ_FMT, "tests/reloj.test.mjs": '''import { formatear, aSegundos } from "../src/reloj.js";

describe("reloj", () => {
  it("formatea minutos y segundos", () => {
    expect(formatear(75)).toBe("01:15");
    expect(formatear(0)).toBe("00:00");
  });
  it("formatea más de una hora en minutos", () => {
    expect(formatear(3725)).toBe("62:05");
  });
  it("pasa de texto a segundos", () => {
    expect(aSegundos("02:30")).toBe(150);
  });
});
'''}, referencia={"tests/reloj.test.mjs": T + '''import { formatear, aSegundos } from "../src/reloj.js";

test("formatea minutos y segundos", () => {
  assert.equal(formatear(75), "01:15");
  assert.equal(formatear(0), "00:00");
});

test("formatea más de una hora en minutos", () => {
  assert.equal(formatear(3725), "62:05");
});

test("pasa de texto a segundos", () => {
  assert.equal(aSegundos("02:30"), 150);
});
'''}, examen="\n".join(
        [f"const BUENO = {json.dumps(RELOJ_FMT)};",
         '''test("tests con node:test, sin expect de Jest", () => {
  verde(5);
  const t = leer("tests/reloj.test.mjs");
  assert.match(t, /from\\s+["']node:test["']/);
  assert.doesNotMatch(t, /\\bexpect\\s*\\(/);
});''']
        + [f'test({json.dumps("los tests siguen pillando: " + k)}, () => {{\n  pilla({{ "src/reloj.js": BUENO }}, '
           f'{{ "src/reloj.js": {json.dumps(v)} }}, 5);\n}});' for k, v in RELOJ_MUT.items()]))

# ================================================================ DIAGNOSTICAR (la semilla está en rojo)
NIVEL = r'''// posicionDe(filas, caracter): la primera aparición del carácter en el mapa (array de strings), en píxeles:
// {x: columna × 16, y: fila × 16}, contando columnas y filas desde 0; null si no está.
export const TILE = 16;

export function posicionDe(filas, caracter) {
  for (let fila = 0; fila < filas.length; fila++) {
    const col = filas[fila].indexOf(caracter);
    if (col !== -1) return { x: col * TILE, y: fila * TILE };
  }
  return null;
}

export function contar(filas, caracter) {
  return filas.join("").split(caracter).length - 1;
}
'''
NIVEL_TEST = T + '''import { posicionDe, contar } from "../src/nivel.js";

const NIVEL = [
  "....................",
  "..J.......o.....E...",
  "##########....####F#",
];

test("el jugador empieza donde está la J", () => {
  assert.deepEqual(posicionDe(NIVEL, "J"), { x: 32, y: 16 });
});

test("la moneda y el enemigo", () => {
  assert.deepEqual(posicionDe(NIVEL, "o"), { x: 160, y: 16 });
  assert.deepEqual(posicionDe(NIVEL, "E"), { x: 256, y: 16 });
});

test("la meta está en la F", () => {
  assert.deepEqual(posicionDe(NIVEL, "F"), { x: 272, y: 32 });
});

test("cuenta los bloques de suelo", () => {
  assert.equal(contar(NIVEL, "#"), 15);
  assert.equal(posicionDe(NIVEL, "K"), null);
});
'''
caso("d-test-mal-contado", "Test con un valor mal contado", "diagnosticar", "logica", """
npm test falla. Arréglalo. La regla de src/nivel.js (el comentario de arriba) es la especificación y manda.""",
     semilla={"src/nivel.js": NIVEL, "tests/nivel.test.mjs": NIVEL_TEST},
     referencia={"tests/nivel.test.mjs": NIVEL_TEST.replace("{ x: 272, y: 32 }", "{ x: 288, y: 32 }")},
     examen='''
test("npm test pasa y siguen los 4 tests de nivel", () => verde(6));

test("posicionDe sigue la regla: columna × 16, fila × 16", async () => {
  verde(6);
  const { posicionDe } = await src("src/nivel.js");
  assert.deepEqual(posicionDe(["..F", "J.."], "F"), { x: 32, y: 0 });
  assert.deepEqual(posicionDe(["..F", "J.."], "J"), { x: 0, y: 16 });
  assert.deepEqual(posicionDe(["...", "...", "....o"], "o"), { x: 64, y: 32 });
  assert.equal(posicionDe(["..."], "J"), null);
});

test("contar sigue igual", async () => {
  verde(6);
  const { contar } = await src("src/nivel.js");
  assert.equal(contar(["#.#", "##"], "#"), 4);
});
''')

RANGO_MAL = r'''// rango(a, b): los enteros de a a b, AMBOS incluidos; [] si a > b. suma(xs): suma de una lista.
export function rango(a, b) {
  const out = [];
  for (let i = a; i < b; i++) out.push(i);
  return out;
}

export function suma(xs) {
  return xs.reduce((x, y) => x + y, 0);
}
'''
caso("d-off-by-one", "Error de uno en el código", "diagnosticar", "logica", """
npm test falla. Arréglalo: el comentario de src/rango.js es la especificación.""",
     semilla={"src/rango.js": RANGO_MAL, "tests/rango.test.mjs": T + '''import { rango, suma } from "../src/rango.js";

test("rango incluye los dos extremos", () => {
  assert.deepEqual(rango(1, 3), [1, 2, 3]);
  assert.deepEqual(rango(4, 4), [4]);
});

test("rango vacío si a > b", () => {
  assert.deepEqual(rango(3, 1), []);
});

test("suma de 1 a 10", () => {
  assert.equal(suma(rango(1, 10)), 55);
});
'''}, referencia={"src/rango.js": RANGO_MAL.replace("i < b", "i <= b")}, examen='''
test("npm test pasa y siguen los tests de rango", () => verde(5));

test("rango incluye los dos extremos", async () => {
  verde(5);
  const { rango } = await src("src/rango.js");
  assert.deepEqual(rango(-2, 1), [-2, -1, 0, 1]);
  assert.deepEqual(rango(0, 0), [0]);
  assert.deepEqual(rango(2, 1), []);
});
''')

CALC = r'''// Calculadora: sumar(a, b), restar(a, b) y media(xs) (0 si la lista está vacía).
export const sumar = (a, b) => a + b;
export const restar = (a, b) => a - b;

export function media(xs) {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}
'''
CALC_TEST = T + '''import { sumar, restar, media } from "../calc.js";

test("sumar y restar", () => {
  assert.equal(sumar(2, 3), 5);
  assert.equal(restar(2, 3), -1);
});

test("media", () => {
  assert.equal(media([1, 2, 3, 6]), 3);
});

test("media de una lista vacía", () => {
  assert.equal(media([]), 0);
});
'''
caso("d-import-mal", "Test que importa mal", "diagnosticar", "logica", """
npm test falla. Arréglalo sin cambiar lo que hace src/calc.js.""",
     semilla={"src/calc.js": CALC, "tests/calc.test.mjs": CALC_TEST},
     referencia={"tests/calc.test.mjs": CALC_TEST.replace('"../calc.js"', '"../src/calc.js"')}, examen='''
test("npm test pasa y siguen los tests de calc", () => verde(5));

test("calc hace lo mismo que antes", async () => {
  verde(5);
  const { sumar, restar, media } = await src("src/calc.js");
  assert.equal(sumar(10, -4), 6);
  assert.equal(restar(10, -4), 14);
  assert.equal(media([2, 4]), 3);
  assert.equal(media([]), 0);
});
''')

TARIFA_MAL = r'''// Tarifa de aparcamiento (ver docs/ESPEC.md). Importes en céntimos.
export const redondearCent = (x) => Math.round(x);
export const tarifaNoche = (minutos) => 50 + 10 * minutos;
export const tarifaDia = (minutos) => 100 + 20 * minutos;
'''
TARIFA_TEST = T + '''import { redondearCent, tarifaNoche, tarifaDia } from "../src/tarifa.js";

test("redondeo al céntimo", () => {
  assert.equal(redondearCent(10.4), 10);
  assert.equal(redondearCent(10.5), 10);
});

test("tarifa de noche", () => {
  assert.equal(tarifaNoche(10), 170);
});

test("tarifa de día", () => {
  assert.equal(tarifaDia(5), 200);
});
'''
caso("d-mixto", "Un fallo del test y otro del código", "diagnosticar", "logica", """
npm test falla. Arréglalo: docs/ESPEC.md es la especificación y manda, tanto sobre el código como sobre los tests.""",
     semilla={"src/tarifa.js": TARIFA_MAL, "tests/tarifa.test.mjs": TARIFA_TEST, "docs/ESPEC.md": """# Tarifa del aparcamiento

Importes en céntimos enteros.

- `redondearCent(x)`: redondea al céntimo entero más cercano; los ,5 suben (`Math.round`): 10,5 → 11.
- `tarifaNoche(minutos)` = 50 + 12 × minutos.
- `tarifaDia(minutos)` = 100 + 20 × minutos.
"""}, referencia={"src/tarifa.js": TARIFA_MAL.replace("10 * minutos", "12 * minutos"),
                  "tests/tarifa.test.mjs": TARIFA_TEST.replace("redondearCent(10.5), 10", "redondearCent(10.5), 11")},
     examen='''
test("npm test pasa y siguen los tests de tarifa", () => verde(5));

test("redondeo como dice la especificación", async () => {
  verde(5);
  const { redondearCent } = await src("src/tarifa.js");
  assert.equal(redondearCent(2.5), 3);
  assert.equal(redondearCent(2.49), 2);
});

test("tarifas como dice la especificación", async () => {
  verde(5);
  const { tarifaNoche, tarifaDia } = await src("src/tarifa.js");
  assert.equal(tarifaNoche(0), 50);
  assert.equal(tarifaNoche(30), 410);
  assert.equal(tarifaDia(1), 120);
});
''')

# ================================================================ ARREGLAR
JUEGO = r'''import { crearReloj, tic } from "./reloj.js";

// Una partida: su reloj y los puntos.
export function crearPartida(segundos) {
  return { reloj: crearReloj(segundos), puntos: 0 };
}

export function avanzar(p) {
  return { ...p, reloj: tic(p.reloj) };
}

export function sumarPuntos(p, n) {
  return { ...p, puntos: p.puntos + n };
}
'''
RELOJ = r'''// Reloj de la partida: cuenta frames y, cada 60, baja un segundo; nunca baja de 0.
export function crearReloj(segundos) {
  return { segundos, frames: 0 };
}

export function tic(r) {
  if (r.segundos <= 0) return { segundos: 0, frames: 0 };
  const frames = r.frames + 1;
  return frames >= 60 ? { segundos: r.segundos - 1, frames: 0 } : { segundos: r.segundos, frames };
}
'''
caso("a-modulo-falta", "Import de un módulo que no existe", "arreglar", "logica", """
npm test falla. Arréglalo. docs/ESPEC.md describe lo que falta.""",
     semilla={"src/juego.js": JUEGO, "docs/ESPEC.md": """# Reloj de la partida

`src/reloj.js` exporta:
- `crearReloj(segundos)` → `{segundos, frames: 0}`.
- `tic(reloj)` → un reloj NUEVO con `frames` + 1; cuando `frames` llega a 60 vuelve a 0 y `segundos` baja 1.
  Con `segundos` a 0 devuelve `{segundos: 0, frames: 0}` (nunca baja de 0).
""", "tests/juego.test.mjs": T + '''import { crearPartida, avanzar, sumarPuntos } from "../src/juego.js";

test("una partida nueva", () => {
  assert.deepEqual(crearPartida(300), { reloj: { segundos: 300, frames: 0 }, puntos: 0 });
});

test("60 frames son un segundo", () => {
  let p = crearPartida(300);
  for (let i = 0; i < 60; i++) p = avanzar(p);
  assert.deepEqual(p.reloj, { segundos: 299, frames: 0 });
});

test("sumar puntos", () => {
  assert.equal(sumarPuntos(crearPartida(10), 50).puntos, 50);
});
'''}, referencia={"src/reloj.js": RELOJ}, examen='''
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
''')

ESTADISTICA_BIEN = r'''// media(xs): media aritmética redondeada a 2 decimales (Math.round(x × 100) / 100); 0 si la lista está vacía.
// mediana(xs): el valor del medio de la lista ordenada (la media de los dos del medio si son pares).
export function mediana(xs) {
  const o = [...xs].sort((a, b) => a - b);
  const m = Math.floor(o.length / 2);
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
}

export function media(xs) {
  if (!xs.length) return 0;
  return Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 100) / 100;
}
'''
ESTADISTICA_MAL = ESTADISTICA_BIEN.replace("export function mediana", """export function media(xs) {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function mediana""")
caso("a-duplicada", "Función declarada dos veces", "arreglar", "logica", """
npm test falla porque src/estadistica.js no carga. Arréglalo: el comentario de arriba del archivo es la
especificación.""",
     semilla={"src/estadistica.js": ESTADISTICA_MAL, "tests/estadistica.test.mjs": T + '''import { media, mediana } from "../src/estadistica.js";

test("media redondeada a 2 decimales", () => {
  assert.equal(media([1, 2, 3, 4]), 2.5);
  assert.equal(media([1, 2, 2]), 1.67);
});

test("media de una lista vacía", () => {
  assert.equal(media([]), 0);
});

test("mediana", () => {
  assert.equal(mediana([3, 1, 2]), 2);
  assert.equal(mediana([4, 1, 3, 2]), 2.5);
});
'''}, referencia={"src/estadistica.js": ESTADISTICA_BIEN}, examen='''
test("npm test pasa", () => verde(5));

test("media como dice el comentario", async () => {
  verde(5);
  const { media } = await src("src/estadistica.js");
  assert.equal(media([10, 20, 25]), 18.33);
  assert.equal(media([]), 0);
});

test("mediana sigue igual", async () => {
  verde(5);
  const { mediana } = await src("src/estadistica.js");
  assert.equal(mediana([5]), 5);
  assert.equal(mediana([9, 1]), 5);
});
''')

COLOR_BIEN = r'''// Colores: hex(r, g, b) → '#rrggbb'; rgb('#rrggbb') → [r, g, b]; aclarar('#rrggbb', pct) acerca cada canal a 255
// en pct %: canal + Math.round((255 − canal) × pct / 100).
export function hex(r, g, b) {
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

export function rgb(texto) {
  const n = parseInt(texto.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function aclarar(texto, pct) {
  const [r, g, b] = rgb(texto).map((c) => c + Math.round(((255 - c) * pct) / 100));
  return hex(r, g, b);
}
'''
caso("a-export-duplicado", "Export duplicado", "arreglar", "logica", """
npm test falla porque src/color.js no carga. Arréglalo sin cambiar lo que hace.""",
     semilla={"src/color.js": COLOR_BIEN + "\nexport { hex, rgb };\n", "tests/color.test.mjs": T + '''import { hex, rgb, aclarar } from "../src/color.js";

test("hex y rgb", () => {
  assert.equal(hex(255, 0, 128), "#ff0080");
  assert.deepEqual(rgb("#ff0080"), [255, 0, 128]);
});

test("aclarar", () => {
  assert.equal(aclarar("#000000", 50), "#808080");
  assert.equal(aclarar("#ffffff", 30), "#ffffff");
});
'''}, referencia={"src/color.js": COLOR_BIEN}, examen='''
test("npm test pasa", () => verde(4));

test("color hace lo mismo que antes", async () => {
  verde(4);
  const { hex, rgb, aclarar } = await src("src/color.js");
  assert.equal(hex(10, 11, 12), "#0a0b0c");
  assert.deepEqual(rgb("#0a0b0c"), [10, 11, 12]);
  assert.equal(aclarar("#204060", 10), "#3653703".slice(0, 7));
});
''')


def tablas(bien: bool) -> str:
    lineas = ["// Catálogo de productos (generado) y consultas sobre él.", "export const PRODUCTOS = ["]
    for i in range(1, 301):
        lineas.append(f'  {{ id: {i}, nombre: "producto-{i:03d}", precio: {(i * 37) % 1000 + 100}, '
                      f'stock: {(i * 13) % 50}, categoria: "{"abc"[i % 3]}" }},')
    lineas += ["];", "", "// buscar(id): el producto con ese id, o null si no existe."]
    lineas += ["export function buscar(id) {",
               f"  for (let i = 0; i {'<' if bien else '<='} PRODUCTOS.length; i++) "
               "if (PRODUCTOS[i].id === id) return PRODUCTOS[i];",
               "  return null;", "}", "",
               "// caros(min): ids de los productos con precio >= min.",
               "export function caros(min) {", "  return PRODUCTOS.filter((p) => p.precio >= min).map((p) => p.id);",
               "}", "", "// totalStock(): unidades en el almacén.", "export function totalStock() {",
               "  return PRODUCTOS.reduce((a, p) => a + p.stock, 0);", "}", "",
               "// porCategoria(cat): cuántos productos hay de esa categoría.", "export function porCategoria(cat) {",
               "  return PRODUCTOS.filter((p) => p.categoria === cat).length;", "}", ""]
    return "\n".join(lineas)


caso("a-archivo-largo", "Arreglo en un archivo largo", "arreglar", "logica", """
npm test falla. Arregla el fallo de src/tablas.js sin tocar nada más del archivo (el catálogo tiene que quedar igual).""",
     semilla={"src/tablas.js": tablas(False), "tests/tablas.test.mjs": T + '''import { buscar, caros, totalStock } from "../src/tablas.js";

test("buscar un producto que existe", () => {
  assert.equal(buscar(5).nombre, "producto-005");
});

test("buscar uno que no existe da null", () => {
  assert.equal(buscar(999), null);
});

test("consultas", () => {
  assert.equal(caros(1100).length, 0);
  assert.ok(totalStock() > 0);
});
'''}, referencia={"src/tablas.js": tablas(True)}, examen='''
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
''')

# ================================================================ AMPLIAR SIN ROMPER
CARRITO = r'''// Carrito: {lineas: [{sku, precio (céntimos), cantidad}]}. Las funciones no modifican el carrito que reciben.
export function crearCarrito() {
  return { lineas: [] };
}

export function anadir(carrito, sku, precio, cantidad = 1) {
  const hay = carrito.lineas.find((l) => l.sku === sku);
  const lineas = hay
    ? carrito.lineas.map((l) => (l.sku === sku ? { ...l, cantidad: l.cantidad + cantidad } : l))
    : [...carrito.lineas, { sku, precio, cantidad }];
  return { ...carrito, lineas };
}

export function subtotal(carrito) {
  return carrito.lineas.reduce((a, l) => a + l.precio * l.cantidad, 0);
}

export function total(carrito) {
  return subtotal(carrito);
}
'''
CARRITO_REF = CARRITO.replace('''export function total(carrito) {
  return subtotal(carrito);
}
''', '''const CUPONES = {
  DIEZ: (s) => s - Math.round(s / 10),
  ENVIO: (s) => Math.max(0, s - 499),
};

export function aplicarCupon(carrito, codigo) {
  if (!CUPONES[codigo]) throw new Error("cupón no válido");
  return { ...carrito, cupon: codigo };
}

export function total(carrito) {
  const s = subtotal(carrito);
  return carrito.cupon ? CUPONES[carrito.cupon](s) : s;
}
''')
CARRITO_TEST = T + '''import { crearCarrito, anadir, subtotal, total } from "../src/carrito.js";

test("añadir junta el mismo sku", () => {
  const c = anadir(anadir(crearCarrito(), "a", 100), "a", 100, 2);
  assert.deepEqual(c.lineas, [{ sku: "a", precio: 100, cantidad: 3 }]);
});

test("subtotal y total", () => {
  const c = anadir(anadir(crearCarrito(), "a", 250, 2), "b", 99);
  assert.equal(subtotal(c), 599);
  assert.equal(total(c), 599);
});
'''
caso("m-carrito", "Ampliar un módulo sin romperlo", "ampliar", "logica", """
Añade cupones a src/carrito.js sin cambiar la firma de nada y sin romper lo que ya hace. aplicarCupon(carrito,
codigo) devuelve un carrito NUEVO con cupon: codigo si el código existe y lanza Error('cupón no válido') si no.
Cupones: 'DIEZ' quita un 10 % del subtotal (Math.round(subtotal / 10)); 'ENVIO' quita 499 céntimos sin bajar de 0.
total(carrito) pasa a restar el cupón si lo hay; subtotal no cambia. Añade los tests a tests/carrito.test.mjs.""",
     semilla={"src/carrito.js": CARRITO, "tests/carrito.test.mjs": CARRITO_TEST},
     referencia={"src/carrito.js": CARRITO_REF, "tests/carrito.test.mjs": CARRITO_TEST + '''
test("cupón DIEZ", async () => {
  const { aplicarCupon } = await import("../src/carrito.js");
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 1999), "DIEZ")), 1799);
});
'''}, examen='''
test("lo que ya hacía sigue igual", async () => {
  verde(4);
  const { crearCarrito, anadir, subtotal, total } = await src("src/carrito.js");
  const c = anadir(anadir(anadir(crearCarrito(), "a", 300), "b", 50, 4), "a", 300);
  assert.deepEqual(c.lineas, [{ sku: "a", precio: 300, cantidad: 2 }, { sku: "b", precio: 50, cantidad: 4 }]);
  assert.equal(subtotal(c), 800);
  assert.equal(total(c), 800);
});

test("cupón DIEZ quita el 10 % redondeado", async () => {
  const { crearCarrito, anadir, aplicarCupon, subtotal, total } = await src("src/carrito.js");
  const c = aplicarCupon(anadir(crearCarrito(), "a", 1999), "DIEZ");
  assert.equal(c.cupon, "DIEZ");
  assert.equal(subtotal(c), 1999);
  assert.equal(total(c), 1799);
});

test("cupón ENVIO no baja de 0", async () => {
  const { crearCarrito, anadir, aplicarCupon, total } = await src("src/carrito.js");
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 1000), "ENVIO")), 501);
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 300), "ENVIO")), 0);
});

test("cupón que no existe y sin modificar el carrito", async () => {
  const { crearCarrito, anadir, aplicarCupon } = await src("src/carrito.js");
  const c = anadir(crearCarrito(), "a", 100);
  Object.freeze(c);
  Object.freeze(c.lineas);
  assert.throws(() => aplicarCupon(c, "GRATIS"), /cupón no válido/);
  assert.equal(aplicarCupon(c, "DIEZ").cupon, "DIEZ");
  assert.equal(c.cupon, undefined);
});
''')

PASO = r'''// paso(estado, entrada): un paso del juego. estado {x, vx}; entrada {izquierda, derecha} (teclas pulsadas).
// vx = 2 con derecha, -2 con izquierda, 0 con ninguna o con las dos; x += vx sin salir de 0..300.
export function crearEstado() {
  return { x: 0, vx: 0 };
}

export function paso(estado, entrada) {
  const vx = entrada.derecha && !entrada.izquierda ? 2 : entrada.izquierda && !entrada.derecha ? -2 : 0;
  const x = Math.min(300, Math.max(0, estado.x + vx));
  return { ...estado, x, vx };
}
'''
PASO_REF = r'''// paso(estado, entrada): un paso del juego. estado {x, vx, pausado, pausaAntes}; entrada {izquierda, derecha,
// pausa} (teclas pulsadas). vx = 2 con derecha, -2 con izquierda, 0 con ninguna o con las dos; x += vx sin salir de
// 0..300. Al pulsar pausa (de no pulsada a pulsada) se alterna `pausado`; pausado, x y vx no cambian.
export function crearEstado() {
  return { x: 0, vx: 0, pausado: false, pausaAntes: false };
}

export function paso(estado, entrada) {
  const pulsada = !!entrada.pausa;
  const pausado = pulsada && !estado.pausaAntes ? !estado.pausado : !!estado.pausado;
  if (pausado) return { ...estado, pausado, pausaAntes: pulsada };
  const vx = entrada.derecha && !entrada.izquierda ? 2 : entrada.izquierda && !entrada.derecha ? -2 : 0;
  const x = Math.min(300, Math.max(0, estado.x + vx));
  return { ...estado, x, vx, pausado, pausaAntes: pulsada };
}
'''
PASO_TEST = T + '''import { crearEstado, paso } from "../src/paso.js";

test("se mueve a la derecha y a la izquierda", () => {
  let e = paso(crearEstado(), { derecha: true });
  assert.equal(e.x, 2);
  e = paso(e, { izquierda: true });
  assert.equal(e.x, 0);
});

test("no sale de 0..300", () => {
  assert.equal(paso({ ...crearEstado(), x: 299 }, { derecha: true }).x, 300);
  assert.equal(paso(crearEstado(), { izquierda: true }).x, 0);
});
'''
caso("m-paso", "Ampliar sin cambiar la firma", "ampliar", "logica", """
Añade pausa a src/paso.js sin cambiar la firma de paso(estado, entrada) y sin romper el movimiento. entrada.pausa es
la tecla P (true mientras se mantiene pulsada). Al PULSARLA (pasa de no pulsada a pulsada) estado.pausado cambia
de false a true o de true a false; mantenerla pulsada no lo vuelve a cambiar. Mientras está pausado, x y vx no
cambian. crearEstado() devuelve también pausado: false y lo que necesites para saber si la tecla ya estaba pulsada.
Añade los tests a tests/paso.test.mjs.""",
     semilla={"src/paso.js": PASO, "tests/paso.test.mjs": PASO_TEST},
     referencia={"src/paso.js": PASO_REF, "tests/paso.test.mjs": PASO_TEST + '''
test("pausa al pulsar", () => {
  assert.equal(paso(crearEstado(), { pausa: true }).pausado, true);
});
'''}, examen='''
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
''')

# ================================================================ VARIOS ARCHIVOS
FACTURA = r'''// totalFactura(lineas): suma de precio × cantidad (céntimos, en euros).
export function totalFactura(lineas) {
  return lineas.reduce((a, l) => a + l.precio * l.cantidad, 0);
}
'''
RESUMEN = r'''import { totalFactura } from "./factura.js";

// resumen(facturas): {numero, total} de una lista de facturas (cada una, una lista de líneas).
export function resumen(facturas) {
  return { numero: facturas.length, total: facturas.reduce((a, f) => a + totalFactura(f), 0) };
}
'''
caso("v-divisas", "Un módulo nuevo que usan otros dos", "varios", "logica", """
Crea src/divisas.js con TASAS = {EUR: 1, USD: 1.1, GBP: 0.85} (unidades de esa moneda por 1 euro) y
convertir(centimos, de, a) = Math.round(centimos / TASAS[de] × TASAS[a]); si alguna moneda no está en TASAS lanza
Error('moneda desconocida'). Después añade totalFacturaEn(lineas, moneda) a src/factura.js y resumenEn(facturas,
moneda) a src/resumen.js: hacen lo mismo que totalFactura y resumen pero con el total ya sumado convertido de EUR a
esa moneda, usando convertir importado de src/divisas.js (sin copiar las tasas). Lo que ya había no cambia. Añade
tests.""",
     semilla={"src/factura.js": FACTURA, "src/resumen.js": RESUMEN, "tests/factura.test.mjs": T + '''import { totalFactura } from "../src/factura.js";
import { resumen } from "../src/resumen.js";

test("total y resumen en euros", () => {
  assert.equal(totalFactura([{ precio: 500, cantidad: 3 }]), 1500);
  assert.deepEqual(resumen([[{ precio: 100, cantidad: 1 }], []]), { numero: 2, total: 100 });
});
'''}, referencia={"src/divisas.js": r'''// Monedas: unidades de cada una por 1 euro.
export const TASAS = { EUR: 1, USD: 1.1, GBP: 0.85 };

export function convertir(centimos, de, a) {
  if (!(de in TASAS) || !(a in TASAS)) throw new Error("moneda desconocida");
  return Math.round((centimos / TASAS[de]) * TASAS[a]);
}
''', "src/factura.js": 'import { convertir } from "./divisas.js";\n\n' + FACTURA + '''
// totalFacturaEn(lineas, moneda): el total convertido de EUR a esa moneda.
export function totalFacturaEn(lineas, moneda) {
  return convertir(totalFactura(lineas), "EUR", moneda);
}
''', "src/resumen.js": RESUMEN.replace('import { totalFactura } from "./factura.js";',
                                      'import { totalFactura } from "./factura.js";\nimport { convertir } from "./divisas.js";') + '''
// resumenEn(facturas, moneda): el resumen con el total convertido de EUR a esa moneda.
export function resumenEn(facturas, moneda) {
  const r = resumen(facturas);
  return { ...r, total: convertir(r.total, "EUR", moneda) };
}
''', "tests/divisas.test.mjs": T + '''import { convertir } from "../src/divisas.js";

test("convertir", () => {
  assert.equal(convertir(1000, "EUR", "USD"), 1100);
});
'''}, examen='''
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
    assert.doesNotMatch(t, /0\\.85|1\\.1\\b/, f);
  }
  assert.match(leer("src/factura.js"), /from\\s+["']\\.\\/divisas\\.js["']/);
});
''')

DINERO = r'''// formatear(centimos) → '12,34 €'.
export function formatear(centimos) {
  return `${(centimos / 100).toFixed(2).replace(".", ",")} €`;
}
'''
TICKET = r'''import { formatear } from "./dinero.js";

// lineaTicket(nombre, centimos) → 'nombre: 12,34 €'.
export function lineaTicket(nombre, centimos) {
  return `${nombre}: ${formatear(centimos)}`;
}
'''
INFORME = r'''import { formatear } from "./dinero.js";
import { lineaTicket } from "./ticket.js";

// informe(items): una línea por item y la del total.
export function informe(items) {
  const total = items.reduce((a, i) => a + i.centimos, 0);
  return [...items.map((i) => lineaTicket(i.nombre, i.centimos)), `TOTAL ${formatear(total)}`].join("\n");
}
'''
DINERO_TEST = T + '''import { formatear } from "../src/dinero.js";

test("formatear", () => {
  assert.equal(formatear(1234), "12,34 €");
  assert.equal(formatear(5), "0,05 €");
});
'''
TICKET_TEST = T + '''import { lineaTicket } from "../src/ticket.js";
import { informe } from "../src/informe.js";

test("línea e informe", () => {
  assert.equal(lineaTicket("pan", 120), "pan: 1,20 €");
  assert.equal(informe([{ nombre: "pan", centimos: 120 }]), "pan: 1,20 €\\nTOTAL 1,20 €");
});
'''
caso("v-renombrar", "Renombrar en varios archivos", "varios", "logica", """
Renombra la función formatear a formatearEuros en src/dinero.js y en todo lo que la usa (src/ticket.js,
src/informe.js y los tests). Que no quede ninguna exportación ni llamada con el nombre viejo. El comportamiento no
cambia.""",
     semilla={"src/dinero.js": DINERO, "src/ticket.js": TICKET, "src/informe.js": INFORME,
              "tests/dinero.test.mjs": DINERO_TEST, "tests/ticket.test.mjs": TICKET_TEST},
     referencia={"src/dinero.js": DINERO.replace("formatear(", "formatearEuros("),
                 "src/ticket.js": TICKET.replace("formatear", "formatearEuros"),
                 "src/informe.js": INFORME.replace("formatear", "formatearEuros"),
                 "tests/dinero.test.mjs": DINERO_TEST.replace("formatear", "formatearEuros")}, examen='''
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
  assert.equal(informe([{ nombre: "a", centimos: 100 }, { nombre: "b", centimos: 250 }]), "a: 1,00 €\\nb: 2,50 €\\nTOTAL 3,50 €");
});

test("no queda el nombre viejo en ningún archivo", () => {
  for (const f of ["src/dinero.js", "src/ticket.js", "src/informe.js", "tests/dinero.test.mjs", "tests/ticket.test.mjs"]) {
    if (existe(f)) assert.doesNotMatch(leer(f), /\\bformatear\\b/, f);
  }
});
''')

# ================================================================ TANGIBLES: WEBS Y JUEGOS (se pueden abrir y usar)
PROPINAS = r'''// calcular(cuentaCent, pct, personas) → {propina, total, porPersona} en céntimos.
export function calcular(cuentaCent, pct, personas) {
  if (!Number.isInteger(personas) || personas < 1) throw new Error("personas no válidas");
  const propina = Math.round((cuentaCent * pct) / 100);
  const total = cuentaCent + propina;
  return { propina, total, porPersona: Math.ceil(total / personas) };
}
'''
FORMATO = r'''// euros(centimos) → '1.234,50 €' (miles con punto, decimales con coma).
export function euros(centimos) {
  const signo = centimos < 0 ? "-" : "";
  const abs = Math.abs(centimos);
  const enteros = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${signo}${enteros},${String(abs % 100).padStart(2, "0")} €`;
}
'''
VISTA_PROPINAS = r'''import { euros } from "./formato.js";

// vista(r): el resultado como HTML.
export function vista(r) {
  return [
    `<p class="propina">Propina: ${euros(r.propina)}</p>`,
    `<p class="total">Total: ${euros(r.total)}</p>`,
    `<p class="por-persona">Cada uno: ${euros(r.porPersona)}</p>`,
  ].join("\n");
}
'''
MAIN_PROPINAS = r'''import { calcular } from "./propinas.js";
import { vista } from "./vista.js";

const $ = (id) => document.getElementById(id);
const aCentimos = (texto) => Math.round(Number(String(texto).replace(",", ".")) * 100) || 0;

function pintar() {
  try {
    const r = calcular(aCentimos($("cuenta").value), Number($("porcentaje").value), Number($("personas").value));
    $("resultado").innerHTML = vista(r);
  } catch (e) {
    $("resultado").textContent = e.message;
  }
}

for (const id of ["cuenta", "porcentaje", "personas"]) $(id).addEventListener("input", pintar);
pintar();
'''
INDEX_PROPINAS = '''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Propinas</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 420px; margin: 40px auto; padding: 0 16px; }
    label { display: block; margin: 10px 0; }
    input { width: 100%; padding: 6px; font-size: 1rem; }
    #resultado p { font-size: 1.15rem; margin: 6px 0; }
  </style>
</head>
<body>
  <h1>Calculadora de propinas</h1>
  <label>Cuenta (€) <input id="cuenta" value="50,00" inputmode="decimal" /></label>
  <label>Propina (%) <input id="porcentaje" type="number" value="10" min="0" /></label>
  <label>Personas <input id="personas" type="number" value="2" min="1" /></label>
  <section id="resultado"></section>
  <script type="module" src="src/main.js"></script>
</body>
</html>
'''
caso("w-propinas", "Web: calculadora de propinas", "tangible", "web", """
Haz una web de una página para calcular propinas. src/propinas.js: calcular(cuentaCent, pct, personas) devuelve
{propina, total, porPersona} en céntimos: propina = Math.round(cuenta × pct / 100), total = cuenta + propina,
porPersona = Math.ceil(total / personas); si personas no es un entero de 1 o más lanza Error('personas no
válidas'). src/formato.js: euros(centimos) → texto con miles con punto y decimales con coma ('1.234,50 €',
'0,05 €'). src/vista.js: vista(r) devuelve este HTML, una línea por párrafo: <p class="propina">Propina: …</p>,
<p class="total">Total: …</p> y <p class="por-persona">Cada uno: …</p>, con los importes en euros(). index.html:
campos con id cuenta (en euros, admite coma), porcentaje y personas, una sección con id resultado y
<script type="module" src="src/main.js">. src/main.js: al escribir en los campos, calcula y pinta vista() en
#resultado. Añade tests de la lógica y de la vista.""",
     referencia={"src/propinas.js": PROPINAS, "src/formato.js": FORMATO, "src/vista.js": VISTA_PROPINAS,
                 "src/main.js": MAIN_PROPINAS, "index.html": INDEX_PROPINAS, "tests/propinas.test.mjs": T + '''import { calcular } from "../src/propinas.js";

test("calcular", () => {
  assert.deepEqual(calcular(5000, 10, 3), { propina: 500, total: 5500, porPersona: 1834 });
});
'''}, examen='''
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
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\\.?\\/?src\\/main\\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /from\\s+["']\\.\\/vista\\.js["']/);
  assert.match(main, /from\\s+["']\\.\\/propinas\\.js["']/);
  assert.match(main, /resultado/);
});
''')

SERPIENTE = r'''// La serpiente: la lógica pura del juego (src/main.js la dibuja y lee el teclado).
const MOV = { derecha: [1, 0], izquierda: [-1, 0], arriba: [0, -1], abajo: [0, 1] };
const CONTRARIA = { derecha: "izquierda", izquierda: "derecha", arriba: "abajo", abajo: "arriba" };

export function crearPartida(ancho, alto) {
  return {
    ancho, alto, dir: "derecha", comida: null, puntos: 0, estado: "jugando",
    cuerpo: [{ x: 2, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 0 }],
  };
}

export function ponerComida(p, x, y) {
  return { ...p, comida: { x, y } };
}

export function girar(p, dir) {
  return dir in MOV && dir !== CONTRARIA[p.dir] ? { ...p, dir } : p;
}

export function paso(p) {
  if (p.estado !== "jugando") return p;
  const [dx, dy] = MOV[p.dir];
  const cabeza = { x: p.cuerpo[0].x + dx, y: p.cuerpo[0].y + dy };
  const fuera = cabeza.x < 0 || cabeza.y < 0 || cabeza.x >= p.ancho || cabeza.y >= p.alto;
  const choca = p.cuerpo.slice(0, -1).some((s) => s.x === cabeza.x && s.y === cabeza.y);
  if (fuera || choca) return { ...p, estado: "fin" };
  const come = p.comida && p.comida.x === cabeza.x && p.comida.y === cabeza.y;
  const cuerpo = [cabeza, ...(come ? p.cuerpo : p.cuerpo.slice(0, -1))];
  return { ...p, cuerpo, comida: come ? null : p.comida, puntos: p.puntos + (come ? 10 : 0) };
}
'''
MAIN_SERPIENTE = r'''import { crearPartida, girar, paso, ponerComida } from "./serpiente.js";

const CELDA = 20;
const lienzo = document.getElementById("tablero");
const ctx = lienzo.getContext("2d");
const marcador = document.getElementById("puntos");
let p = crearPartida(lienzo.width / CELDA, lienzo.height / CELDA);

function nuevaComida() {
  for (;;) {
    const x = Math.floor(Math.random() * p.ancho);
    const y = Math.floor(Math.random() * p.alto);
    if (!p.cuerpo.some((s) => s.x === x && s.y === y)) return ponerComida(p, x, y);
  }
}

function dibujar() {
  ctx.fillStyle = "#1d2b1f";
  ctx.fillRect(0, 0, lienzo.width, lienzo.height);
  if (p.comida) {
    ctx.fillStyle = "#e0533d";
    ctx.fillRect(p.comida.x * CELDA + 3, p.comida.y * CELDA + 3, CELDA - 6, CELDA - 6);
  }
  ctx.fillStyle = "#9bd36a";
  for (const s of p.cuerpo) ctx.fillRect(s.x * CELDA + 1, s.y * CELDA + 1, CELDA - 2, CELDA - 2);
  marcador.textContent = p.estado === "fin" ? `Fin: ${p.puntos} puntos (Espacio para volver a jugar)` : `${p.puntos} puntos`;
}

const TECLAS = { ArrowRight: "derecha", ArrowLeft: "izquierda", ArrowUp: "arriba", ArrowDown: "abajo" };
addEventListener("keydown", (e) => {
  if (TECLAS[e.key]) p = girar(p, TECLAS[e.key]);
  if (e.key === " " && p.estado === "fin") p = crearPartida(p.ancho, p.alto);
});

setInterval(() => {
  if (!p.comida) p = nuevaComida();
  p = paso(p);
  dibujar();
}, 120);
'''
INDEX_SERPIENTE = '''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Serpiente</title>
  <style>
    body { font-family: system-ui, sans-serif; display: grid; place-items: center; background: #101810; color: #e8f0e0; }
    canvas { border: 2px solid #3a5a3a; }
  </style>
</head>
<body>
  <h1>Serpiente</h1>
  <p id="puntos">0 puntos</p>
  <canvas id="tablero" width="400" height="400"></canvas>
  <p>Flechas para moverte.</p>
  <script type="module" src="src/main.js"></script>
</body>
</html>
'''
caso("j-serpiente", "Juego: la serpiente", "tangible", "juego", """
Haz el juego de la serpiente. src/serpiente.js (lógica pura, sin DOM): crearPartida(ancho, alto) → {ancho, alto,
cuerpo: [{x: 2, y: 0}, {x: 1, y: 0}, {x: 0, y: 0}] (la cabeza primero), dir: 'derecha', comida: null, puntos: 0,
estado: 'jugando'}. ponerComida(p, x, y) → partida nueva con comida {x, y}. girar(p, dir) → partida nueva con esa
dirección ('derecha', 'izquierda', 'arriba' o 'abajo'), salvo si es la contraria a la actual (entonces no cambia).
paso(p): si estado no es 'jugando' devuelve p; la nueva cabeza es la actual movida una casilla (derecha x+1,
izquierda x−1, arriba y−1, abajo y+1); si sale del tablero o cae sobre el cuerpo (sin contar el último segmento)
→ estado 'fin'; si cae en la comida, crece (no quita la cola), suma 10 puntos y comida pasa a null; si no, avanza
quitando la cola. Ninguna función modifica la partida que recibe. index.html con <canvas id="tablero"> y
<script type="module" src="src/main.js">; src/main.js dibuja la partida, mueve con las flechas (keydown) y pone
comida al azar donde no haya serpiente. Añade tests de la lógica.""",
     referencia={"src/serpiente.js": SERPIENTE, "src/main.js": MAIN_SERPIENTE, "index.html": INDEX_SERPIENTE,
                 "tests/serpiente.test.mjs": T + '''import { crearPartida, paso } from "../src/serpiente.js";

test("avanza a la derecha", () => {
  assert.deepEqual(paso(crearPartida(10, 10)).cuerpo[0], { x: 3, y: 0 });
});
'''}, examen='''
test("partida nueva y un paso", async () => {
  const { crearPartida, paso } = await src("src/serpiente.js");
  const p = crearPartida(10, 8);
  assert.deepEqual(p, { ancho: 10, alto: 8, cuerpo: [{ x: 2, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 0 }], dir: "derecha",
    comida: null, puntos: 0, estado: "jugando" });
  Object.freeze(p);
  assert.deepEqual(paso(p).cuerpo, [{ x: 3, y: 0 }, { x: 2, y: 0 }, { x: 1, y: 0 }]);
  assert.equal(p.cuerpo[0].x, 2);
});

test("girar, salvo a la contraria", async () => {
  const { crearPartida, girar, paso } = await src("src/serpiente.js");
  const p = crearPartida(10, 10);
  assert.equal(girar(p, "izquierda").dir, "derecha");
  assert.deepEqual(paso(girar(p, "abajo")).cuerpo[0], { x: 2, y: 1 });
});

test("comer crece y suma 10", async () => {
  const { crearPartida, ponerComida, paso } = await src("src/serpiente.js");
  const p = paso(ponerComida(crearPartida(10, 10), 3, 0));
  assert.equal(p.cuerpo.length, 4);
  assert.equal(p.puntos, 10);
  assert.equal(p.comida, null);
});

test("chocar con la pared o consigo misma acaba la partida", async () => {
  const { crearPartida, girar, paso } = await src("src/serpiente.js");
  let p = girar(crearPartida(4, 4), "arriba");
  assert.equal(paso(p).estado, "fin");
  p = { ...crearPartida(10, 10), dir: "abajo",
    cuerpo: [{ x: 5, y: 5 }, { x: 5, y: 6 }, { x: 4, y: 6 }, { x: 4, y: 5 }, { x: 4, y: 4 }] };
  assert.equal(paso(p).estado, "fin");
  const fin = paso(p);
  assert.equal(paso(fin), fin);
});

test("index.html y main.js montan el juego", () => {
  assert.match(leer("index.html"), /<canvas[^>]+id=["']tablero["']/);
  assert.match(leer("index.html"), /<script[^>]+type=["']module["'][^>]+src=["']\\.?\\/?src\\/main\\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /from\\s+["']\\.\\/serpiente\\.js["']/);
  assert.match(main, /keydown/);
});
''')

TAREAS = r'''// Lista de tareas: [{id, texto, hecha}]. Las funciones devuelven listas nuevas.
export function anadir(tareas, texto, id) {
  const t = texto.trim();
  if (!t) throw new Error("texto vacío");
  return [...tareas, { id, texto: t, hecha: false }];
}

export function completar(tareas, id) {
  return tareas.map((t) => (t.id === id ? { ...t, hecha: !t.hecha } : t));
}

export function borrar(tareas, id) {
  return tareas.filter((t) => t.id !== id);
}

export function filtrar(tareas, filtro) {
  if (filtro === "pendientes") return tareas.filter((t) => !t.hecha);
  if (filtro === "hechas") return tareas.filter((t) => t.hecha);
  return tareas;
}

export function contar(tareas) {
  const hechas = tareas.filter((t) => t.hecha).length;
  return { total: tareas.length, pendientes: tareas.length - hechas, hechas };
}
'''
ALMACEN = r'''// Guardar y cargar la lista en un almacén con getItem/setItem (localStorage en el navegador).
export const CLAVE = "tareas-v1";

export function guardar(almacen, tareas) {
  almacen.setItem(CLAVE, JSON.stringify(tareas));
}

export function cargar(almacen) {
  try {
    const datos = JSON.parse(almacen.getItem(CLAVE));
    return Array.isArray(datos) ? datos : [];
  } catch {
    return [];
  }
}
'''
VISTA_TAREAS = r'''// vistaLista(tareas): la lista como HTML (el texto, escapado).
export const escapar = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function vistaLista(tareas) {
  const items = tareas.map((t) => `<li data-id="${t.id}" class="${t.hecha ? "hecha" : "pendiente"}">${escapar(t.texto)}</li>`);
  return `<ul class="tareas">${items.join("")}</ul>`;
}
'''
MAIN_TAREAS = r'''import { anadir, borrar, completar, contar, filtrar } from "./tareas.js";
import { cargar, guardar } from "./almacen.js";
import { vistaLista } from "./vista.js";

let tareas = cargar(localStorage);
let filtro = "todas";
const $ = (id) => document.getElementById(id);

function pintar() {
  $("lista").innerHTML = vistaLista(filtrar(tareas, filtro));
  const c = contar(tareas);
  $("contador").textContent = `${c.pendientes} pendientes de ${c.total}`;
  guardar(localStorage, tareas);
}

$("formulario").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    tareas = anadir(tareas, $("texto").value, Date.now());
    $("texto").value = "";
  } catch { /* texto vacío: no se añade */ }
  pintar();
});
$("lista").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  const id = Number(li.dataset.id);
  tareas = e.altKey ? borrar(tareas, id) : completar(tareas, id);
  pintar();
});
$("filtro").addEventListener("change", (e) => {
  filtro = e.target.value;
  pintar();
});
pintar();
'''
INDEX_TAREAS = '''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tareas</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 40px auto; padding: 0 16px; }
    .tareas { list-style: none; padding: 0; }
    .tareas li { padding: 8px; border-bottom: 1px solid #ddd; cursor: pointer; }
    .tareas li.hecha { text-decoration: line-through; color: #888; }
  </style>
</head>
<body>
  <h1>Tareas</h1>
  <form id="formulario"><input id="texto" placeholder="Nueva tarea" /> <button>Añadir</button></form>
  <select id="filtro"><option value="todas">Todas</option><option value="pendientes">Pendientes</option><option value="hechas">Hechas</option></select>
  <p id="contador"></p>
  <div id="lista"></div>
  <p><small>Clic para completar; Alt + clic para borrar.</small></p>
  <script type="module" src="src/main.js"></script>
</body>
</html>
'''
caso("w-tareas", "Web: lista de tareas", "tangible", "web", """
Haz una web de lista de tareas que se guarde en el navegador. src/tareas.js (puras, devuelven listas nuevas):
anadir(tareas, texto, id) añade {id, texto (sin espacios a los lados), hecha: false} al final y lanza Error('texto
vacío') si el texto queda vacío; completar(tareas, id) alterna hecha de esa tarea; borrar(tareas, id);
filtrar(tareas, filtro) con 'todas', 'pendientes' o 'hechas'; contar(tareas) → {total, pendientes, hechas}.
src/almacen.js: CLAVE = 'tareas-v1'; guardar(almacen, tareas) hace almacen.setItem(CLAVE, JSON.stringify(tareas));
cargar(almacen) devuelve la lista guardada, o [] si no hay nada, si el JSON está roto o si no es una lista.
src/vista.js: vistaLista(tareas) → '<ul class="tareas">' con un <li data-id="ID" class="hecha|pendiente">texto</li>
por tarea (el texto escapado: & < > ") y '</ul>'. index.html con un formulario id formulario, un campo id texto, un
select id filtro, un párrafo id contador, un div id lista y <script type="module" src="src/main.js">; src/main.js lo
une todo con localStorage. Añade tests.""",
     referencia={"src/tareas.js": TAREAS, "src/almacen.js": ALMACEN, "src/vista.js": VISTA_TAREAS,
                 "src/main.js": MAIN_TAREAS, "index.html": INDEX_TAREAS, "tests/tareas.test.mjs": T + '''import { anadir, contar } from "../src/tareas.js";

test("añadir y contar", () => {
  assert.deepEqual(contar(anadir([], "pan", 1)), { total: 1, pendientes: 1, hechas: 0 });
});
'''}, examen='''
test("añadir, completar y borrar", async () => {
  const { anadir, completar, borrar } = await src("src/tareas.js");
  const vacia = Object.freeze([]);
  let t = anadir(vacia, "  pan  ", 1);
  assert.deepEqual(t, [{ id: 1, texto: "pan", hecha: false }]);
  assert.equal(vacia.length, 0);
  t = anadir(t, "leche", 2);
  assert.throws(() => anadir(t, "   ", 3), /texto vacío/);
  t = completar(t, 1);
  assert.deepEqual(t[0], { id: 1, texto: "pan", hecha: true });
  assert.equal(completar(t, 1)[0].hecha, false);
  assert.deepEqual(borrar(t, 1).map((x) => x.id), [2]);
});

test("filtrar y contar", async () => {
  const { filtrar, contar } = await src("src/tareas.js");
  const t = [{ id: 1, texto: "a", hecha: true }, { id: 2, texto: "b", hecha: false }, { id: 3, texto: "c", hecha: false }];
  assert.deepEqual(filtrar(t, "pendientes").map((x) => x.id), [2, 3]);
  assert.deepEqual(filtrar(t, "hechas").map((x) => x.id), [1]);
  assert.equal(filtrar(t, "todas").length, 3);
  assert.deepEqual(contar(t), { total: 3, pendientes: 2, hechas: 1 });
});

test("guardar y cargar del almacén", async () => {
  const { guardar, cargar, CLAVE } = await src("src/almacen.js");
  const datos = {};
  const almacen = { getItem: (k) => (k in datos ? datos[k] : null), setItem: (k, v) => { datos[k] = String(v); } };
  assert.equal(CLAVE, "tareas-v1");
  assert.deepEqual(cargar(almacen), []);
  guardar(almacen, [{ id: 1, texto: "a", hecha: false }]);
  assert.deepEqual(JSON.parse(datos["tareas-v1"]), [{ id: 1, texto: "a", hecha: false }]);
  assert.deepEqual(cargar(almacen), [{ id: 1, texto: "a", hecha: false }]);
  datos["tareas-v1"] = "{roto";
  assert.deepEqual(cargar(almacen), []);
  datos["tareas-v1"] = '{"a":1}';
  assert.deepEqual(cargar(almacen), []);
});

test("la vista escapa el texto", async () => {
  const { vistaLista } = await src("src/vista.js");
  const html = vistaLista([{ id: 7, texto: '<b>"x" & y</b>', hecha: true }, { id: 8, texto: "z", hecha: false }]);
  assert.ok(html.startsWith('<ul class="tareas">') && html.endsWith("</ul>"), html);
  assert.ok(html.includes('<li data-id="7" class="hecha">&lt;b&gt;&quot;x&quot; &amp; y&lt;/b&gt;</li>'), html);
  assert.ok(html.includes('<li data-id="8" class="pendiente">z</li>'), html);
});

test("index.html y main.js montan la página", () => {
  const html = leer("index.html");
  for (const id of ["formulario", "texto", "filtro", "contador", "lista"]) assert.match(html, new RegExp(`id=["']${id}["']`), id);
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\\.?\\/?src\\/main\\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /localStorage/);
  assert.match(main, /from\\s+["']\\.\\/almacen\\.js["']/);
});
''')

TABLERO = r'''// Tres en raya: el tablero es una lista de 9 casillas ('X', 'O' o null), de izquierda a derecha y de arriba abajo.
const LINEAS = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

export function crearTablero() {
  return Array(9).fill(null);
}

export function jugar(t, i, ficha) {
  if (t[i] !== null) throw new Error("casilla ocupada");
  return t.map((c, k) => (k === i ? ficha : c));
}

export function ganador(t) {
  for (const [a, b, c] of LINEAS) if (t[a] && t[a] === t[b] && t[a] === t[c]) return t[a];
  return t.every((c) => c !== null) ? "empate" : null;
}

function cierra(t, ficha) {
  for (let i = 0; i < 9; i++) if (t[i] === null && ganador(jugar(t, i, ficha)) === ficha) return i;
  return -1;
}

export function jugadaIA(t, ficha) {
  const rival = ficha === "X" ? "O" : "X";
  for (const f of [ficha, rival]) {
    const i = cierra(t, f);
    if (i !== -1) return i;
  }
  if (t[4] === null) return 4;
  for (const i of [0, 2, 6, 8]) if (t[i] === null) return i;
  return t.indexOf(null);
}
'''
MAIN_TABLERO = r'''import { crearTablero, ganador, jugadaIA, jugar } from "./tablero.js";

let t = crearTablero();
const casillas = [...document.querySelectorAll("#tablero button")];
const estado = document.getElementById("estado");

function pintar() {
  casillas.forEach((b, i) => { b.textContent = t[i] ?? ""; });
  const g = ganador(t);
  estado.textContent = g === "empate" ? "Empate" : g ? `Gana ${g}` : "Te toca (X)";
}

casillas.forEach((b, i) => b.addEventListener("click", () => {
  if (t[i] !== null || ganador(t)) return;
  t = jugar(t, i, "X");
  if (!ganador(t)) t = jugar(t, jugadaIA(t, "O"), "O");
  pintar();
}));
document.getElementById("otra").addEventListener("click", () => { t = crearTablero(); pintar(); });
pintar();
'''
INDEX_TABLERO = '''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Tres en raya</title>
  <style>
    body { font-family: system-ui, sans-serif; display: grid; place-items: center; }
    #tablero { display: grid; grid-template-columns: repeat(3, 80px); gap: 6px; }
    #tablero button { width: 80px; height: 80px; font-size: 2rem; }
  </style>
</head>
<body>
  <h1>Tres en raya</h1>
  <p id="estado"></p>
  <div id="tablero">
    <button></button><button></button><button></button>
    <button></button><button></button><button></button>
    <button></button><button></button><button></button>
  </div>
  <p><button id="otra">Otra partida</button></p>
  <script type="module" src="src/main.js"></script>
</body>
</html>
'''
caso("j-tres-en-raya", "Juego: tres en raya contra la máquina", "tangible", "juego", """
Haz el tres en raya contra la máquina. src/tablero.js: el tablero es una lista de 9 casillas ('X', 'O' o null) de
izquierda a derecha y de arriba abajo. crearTablero() → 9 null. jugar(t, i, ficha) → tablero nuevo (Error('casilla
ocupada') si no está libre). ganador(t) → 'X' u 'O' si tiene tres en raya, 'empate' si está lleno sin ganador, null
si la partida sigue. jugadaIA(t, ficha) → índice de la casilla que juega la máquina, en este orden: 1) la que le
hace ganar ya; 2) la que bloquea una victoria inmediata del rival; 3) el centro (4); 4) la primera esquina libre en
el orden 0, 2, 6, 8; 5) la primera casilla libre. En 1 y 2, si hay varias, la de índice más bajo. index.html con un
div id tablero de 9 botones, un párrafo id estado y un botón id otra, y <script type="module" src="src/main.js">;
src/main.js: el jugador pone X al hacer clic y la máquina contesta con O. Añade tests.""",
     referencia={"src/tablero.js": TABLERO, "src/main.js": MAIN_TABLERO, "index.html": INDEX_TABLERO,
                 "tests/tablero.test.mjs": T + '''import { crearTablero, ganador } from "../src/tablero.js";

test("tablero vacío", () => {
  assert.equal(ganador(crearTablero()), null);
});
'''}, examen='''
const tab = (s) => [...s].map((c) => (c === "." ? null : c));

test("crear y jugar", async () => {
  const { crearTablero, jugar } = await src("src/tablero.js");
  const t = Object.freeze(crearTablero());
  assert.deepEqual(t, Array(9).fill(null));
  assert.deepEqual(jugar(t, 4, "X"), tab("....X...."));
  assert.throws(() => jugar(tab("X........"), 0, "O"), /casilla ocupada/);
});

test("ganador, empate o sigue", async () => {
  const { ganador } = await src("src/tablero.js");
  assert.equal(ganador(tab("XXX.OO...")), "X");
  assert.equal(ganador(tab("O.XO.XO..")), "O");
  assert.equal(ganador(tab("X.O.XO..X")), "X");
  assert.equal(ganador(tab("XOXXOOOXX")), "empate");
  assert.equal(ganador(tab("XO.......")), null);
});

test("la máquina gana si puede y si no bloquea", async () => {
  const { jugadaIA } = await src("src/tablero.js");
  assert.equal(jugadaIA(tab("OO.XX...."), "O"), 2);
  assert.equal(jugadaIA(tab("XX..O...."), "O"), 2);
  assert.equal(jugadaIA(tab("XO..O...."), "X"), 7);
});

test("si no, centro, esquina y la primera libre", async () => {
  const { jugadaIA } = await src("src/tablero.js");
  assert.equal(jugadaIA(tab("X........"), "O"), 4);
  assert.equal(jugadaIA(tab("....X...."), "O"), 0);
  assert.equal(jugadaIA(tab("O...X...."), "O"), 2);
  assert.equal(jugadaIA(tab("X.O.X...O"), "O"), 5); // gana en la columna 2-5-8
});

test("index.html y main.js montan el juego", () => {
  const html = leer("index.html");
  for (const id of ["tablero", "estado", "otra"]) assert.match(html, new RegExp(`id=["']${id}["']`), id);
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\\.?\\/?src\\/main\\.js["']/);
  assert.match(leer("src/main.js"), /from\\s+["']\\.\\/tablero\\.js["']/);
});
''')


# ---------------------------------------------------------------- escribir todo
def escribir(base: Path, archivos: dict) -> None:
    for ruta, texto in archivos.items():
        f = base / ruta
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(texto, encoding="utf-8", newline="\n")


def main() -> None:
    comun = AQUI / "_comun"
    if comun.exists():
        shutil.rmtree(comun)
    escribir(comun / "semilla", COMUN)
    escribir(comun, {"examen.mjs": AYUDA})
    for nombre, c in CASOS.items():
        d = AQUI / nombre
        if d.exists():
            shutil.rmtree(d)
        escribir(d / "semilla", c["semilla"]) if c["semilla"] else (d / "semilla").mkdir(parents=True)
        escribir(d / "referencia", c["referencia"])
        escribir(d / "examen", {"caso.test.mjs": c["examen"]})
        escribir(d, {"encargo.md": f"- {c['encargo']}\n", "caso.json": json.dumps({
            "titulo": c["titulo"], "tipo": c["tipo"], "grupo": c["grupo"], "descripcion": c["descripcion"],
            "check": "npm test", "abrir": c["abrir"], "base": "../_comun/semilla",
            "modalidades": {"caso": {"parches": "encargo.md", "descripcion": "Un parche."}}},
            ensure_ascii=False, indent=2) + "\n"})
    REPERTORIOS.mkdir(exist_ok=True)
    escribir(REPERTORIOS, {"basico.json": json.dumps({
        "titulo": "Básico", "descripcion": "Los 22 casos: escribir desde la especificación, tests, diagnosticar, "
        "arreglar, ampliar sin romper, varios archivos y cuatro tangibles (dos webs y dos juegos).",
        "minutos_tarea": 15, "casos": list(CASOS)}, ensure_ascii=False, indent=2) + "\n"})
    print(f"{len(CASOS)} casos escritos")


if __name__ == "__main__":
    main()
