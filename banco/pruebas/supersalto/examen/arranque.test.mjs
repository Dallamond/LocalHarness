// Lo que hace que el juego arranque en el navegador: todo carga, nada de Node, main.js con bucle y una partida
// larga sin valores rotos. Es lo que el 09/10 falló con 33 de 40 parches «integrados».
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { RAIZ, src } from "./ayuda.mjs";

const SRC = join(RAIZ, "src");
const modulos = () => (existsSync(SRC) ? readdirSync(SRC).filter((f) => f.endsWith(".js")) : []);

test("todos los módulos de src/ cargan (salvo main.js, que necesita el navegador)", async () => {
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

test("los imports de src/ apuntan a archivos que existen y exportan lo importado", async () => {
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
  for (const f of modulos()) {
    const texto = readFileSync(join(SRC, f), "utf8");
    assert.doesNotMatch(texto, /from\s+['"]node:|require\(|readFileSync|process\./, f);
    assert.doesNotMatch(texto, /^(<{7}|={7}|>{7})/m, f);
  }
});

test("index.html y main.js arrancan el juego", () => {
  const html = readFileSync(join(RAIZ, "index.html"), "utf8");
  assert.match(html, /<canvas[^>]*id=["']pantalla["']/);
  assert.match(html, /<script[^>]*type=["']module["'][^>]*src=["']\.?\/?src\/main\.js["']/);
  const main = readFileSync(join(SRC, "main.js"), "utf8");
  for (const trozo of ["requestAnimationFrame", "getContext", "./paso.js", "./render.js", "./partida.js",
    "./entrada.js", "./niveles.js"]) {
    assert.ok(main.includes(trozo), `main.js no contiene ${trozo}`);
  }
});

test("una partida de 3000 pasos en los niveles reales, dibujando, sin romperse", async () => {
  const { NIVELES } = await src("niveles");
  const { crearPartida } = await src("partida");
  const { paso } = await src("paso");
  const { dibujar } = await src("render");
  const ctx = new Proxy({ fillRect() {}, fillText() {}, save() {}, restore() {}, beginPath() {}, fill() {},
    strokeRect() {}, drawImage() {}, measureText: () => ({ width: 10 }) }, {
    get: (o, k) => (k in o ? o[k] : () => {}), set: () => true });
  const patron = [[100, { derecha: true }], [20, { derecha: true, saltar: true }], [30, {}]];
  let p = crearPartida(NIVELES);
  const estados = new Set(["jugando", "muerto", "fin", "meta", "victoria", "pausa"]);
  let n = 0;
  while (n < 3000) {
    for (const [veces, entrada] of patron) {
      for (let i = 0; i < veces && n < 3000; i++, n++) {
        p = paso(p, entrada);
        for (const k of ["x", "y"]) assert.ok(Number.isFinite(p.jugador[k]), `jugador.${k} en el paso ${n}`);
        assert.ok(Number.isFinite(p.puntos), `puntos en el paso ${n}`);
        assert.ok(p.vidas >= 0, `vidas en el paso ${n}`);
        assert.ok(estados.has(p.estado), `estado ${p.estado} en el paso ${n}`);
        if (n % 100 === 0) dibujar(ctx, p);
      }
    }
  }
});

test("se puede avanzar por el nivel 1", async () => {
  const { NIVELES } = await src("niveles");
  const { crearPartida } = await src("partida");
  const { paso } = await src("paso");
  let p = crearPartida(NIVELES);
  let lejos = 0;
  for (let n = 0; n < 1500 && p.estado !== "fin"; n++) {
    p = paso(p, { derecha: true, saltar: n % 60 < 20 });
    if (p.estado === "jugando") lejos = Math.max(lejos, p.jugador.x);
  }
  assert.ok(lejos > 300, `solo llega a x ${Math.round(lejos)}`);
});

