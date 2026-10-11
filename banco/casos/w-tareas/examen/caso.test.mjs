// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

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
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?src\/main\.js["']/);
  const main = leer("src/main.js");
  assert.match(main, /localStorage/);
  assert.match(main, /from\s+["']\.\/almacen\.js["']/);
});
