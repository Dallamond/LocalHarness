// Lo que hace que la página arranque en el navegador: todo carga, imports correctos, nada de Node y main.js cosido.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { RAIZ, src } from "./ayuda.mjs";

const SRC = join(RAIZ, "src");
const modulos = () => (existsSync(SRC) ? readdirSync(SRC).filter((f) => f.endsWith(".js")) : []);
const leer = (ruta) => (existsSync(join(RAIZ, ruta)) ? readFileSync(join(RAIZ, ruta), "utf8") : "");

test("todos los módulos de src/ cargan en node (salvo main.js, que necesita el navegador)", async () => {
  assert.ok(modulos().length >= 15, `solo hay ${modulos().length} módulos en src/`);
  const rotos = [];
  for (const f of modulos().filter((f) => f !== "main.js")) {
    try {
      await src(f.replace(/\.js$/, ""));
    } catch (e) {
      rotos.push(`${f}: ${String(e.message).split("\n")[0]}`);
    }
  }
  assert.deepEqual(rotos, []);
});

test("los imports de src/ apuntan a archivos que existen y exportan lo importado", () => {
  assert.ok(modulos().length, "src/ está vacío");
  const malos = [];
  for (const f of modulos()) {
    const texto = readFileSync(join(SRC, f), "utf8");
    for (const m of texto.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"](\.[^'"]+)['"]/g)) {
      const destino = resolve(SRC, m[2]);
      if (!existsSync(destino)) {
        malos.push(`${f}: ${m[2]} no existe`);
        continue;
      }
      const exporta = readFileSync(destino, "utf8");
      for (const nombre of m[1].split(",").map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean)) {
        if (!new RegExp(`export\\s+(?:async\\s+)?(?:function\\*?|const|let|var|class)\\s+${nombre}\\b`).test(exporta)
          && !new RegExp(`export\\s*\\{[^}]*\\b${nombre}\\b`).test(exporta)) {
          malos.push(`${f}: ${m[2]} no exporta ${nombre}`);
        }
      }
    }
  }
  assert.deepEqual(malos, []);
});

test("nada de Node ni marcas de edición en el código del navegador", () => {
  assert.ok(modulos().length, "src/ está vacío");
  const malos = [];
  for (const f of modulos()) {
    const t = readFileSync(join(SRC, f), "utf8");
    if (/from\s*['"]node:|require\(|readFileSync|process\./.test(t)) malos.push(`${f}: usa Node`);
    if (/^(<{7}|={7}|>{7})/m.test(t)) malos.push(`${f}: marcas de conflicto`);
  }
  assert.deepEqual(malos, []);
});

test("index.html carga main.js como módulo y tiene el contenedor", () => {
  const h = leer("index.html");
  assert.match(h, /<html[^>]*lang="es"/);
  assert.match(h, /<meta[^>]*name="viewport"/);
  assert.match(h, /<main[^>]*id="app"/);
  assert.match(h, /<script[^>]*type="module"[^>]*src="(\.\/)?src\/main\.js"/);
});

test("main.js cose rutas, estado, almacén y vistas", () => {
  const m = leer("src/main.js");
  assert.ok(m, "no hay src/main.js");
  for (const t of ["hashchange", "localStorage", "leerRuta", "reducir", "cargar", "guardar", "innerHTML"]) {
    assert.ok(m.includes(t), `main.js no usa ${t}`);
  }
  for (const v of ["vistaResumen", "tablaMovimientos", "vistaPresupuestos", "formularioMovimiento", "vistaImportar"]) {
    assert.ok(m.includes(v), `main.js no pinta ${v}`);
  }
});

test("estilos: modo oscuro y móvil", () => {
  const css = leer("estilos.css");
  assert.ok(css, "no hay estilos.css");
  assert.match(css, /prefers-color-scheme:\s*dark/);
  assert.match(css, /@media[^{]*max-width/);
  assert.match(leer("index.html"), /<link[^>]*href="(\.\/)?estilos\.css"/);
});

test("ningún archivo de src/ pasa de 200 líneas", () => {
  assert.ok(modulos().length, "src/ está vacío");
  const largos = modulos().map((f) => [f, readFileSync(join(SRC, f), "utf8").split("\n").length]).filter(([, n]) => n > 200);
  assert.deepEqual(largos, []);
});
