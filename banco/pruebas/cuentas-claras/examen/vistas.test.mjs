import { test } from "node:test";
import assert from "node:assert/strict";
import { cuenta, mov, src } from "./ayuda.mjs";

test("html: escapar los cinco caracteres peligrosos", async () => {
  const { escapar } = await src("html");
  assert.equal(escapar(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.equal(escapar(null), "");
  assert.equal(escapar(12), "12");
});

test("navegación: un enlace por vista y la actual marcada", async () => {
  const { navegacion } = await src("navegacion");
  const h = navegacion("presupuestos");
  assert.match(h, /^<nav[\s>]/);
  for (const v of ["resumen", "movimientos", "nuevo", "presupuestos", "importar"]) assert.ok(h.includes(`href="#/${v}"`), v);
  assert.equal(cuenta(h, 'aria-current="page"'), 1);
  assert.match(h, /href="#\/presupuestos"[^>]*aria-current="page"/);
});

test("movimientos: tabla con una fila por movimiento, importes y concepto escapado", async () => {
  const { tablaMovimientos } = await src("vista-movimientos");
  const h = tablaMovimientos([mov(7, "2026-09-01", -123456, "ocio", "<b>Cine</b>"), mov(3, "2026-09-02", 500, "ingresos")]);
  assert.match(h, /<table class="movimientos"/);
  assert.equal(cuenta(h, "<tr data-id="), 2);
  assert.ok(h.indexOf('data-id="7"') < h.indexOf('data-id="3"'));
  assert.ok(h.includes("-1.234,56 €") && h.includes("5,00 €"));
  assert.ok(h.includes("&lt;b&gt;Cine&lt;/b&gt;") && !h.includes("<b>Cine"));
  assert.ok(h.includes('data-borrar="7"') && h.includes('data-borrar="3"'));
  const vacia = tablaMovimientos([]);
  assert.match(vacia, /class="vacio"/);
  assert.ok(!vacia.includes("<table"));
});

test("resumen: mes, cifras formateadas, categorías y gráfico", async () => {
  const { vistaResumen } = await src("vista-resumen");
  const estado = { movimientos: [mov(1, "2026-09-01", 100000, "ingresos"), mov(2, "2026-09-02", -2050, "comida"),
    mov(3, "2026-09-03", -1000, "ocio")], presupuestos: {}, siguienteId: 4, version: 1 };
  const h = vistaResumen(estado, "2026-09");
  assert.match(h, /<section class="resumen" data-mes="2026-09"/);
  assert.ok(h.includes("septiembre 2026"));
  for (const t of ["1.000,00 €", "30,50 €", "969,50 €"]) assert.ok(h.includes(t), t);
  assert.equal(cuenta(h, "<li data-categoria="), 2);
  assert.ok(h.indexOf('data-categoria="comida"') < h.indexOf('data-categoria="ocio"'));
  assert.ok(h.includes("<svg"));
});

test("gráfico: dos barras por mes, la más alta mide 100", async () => {
  const { graficoBarras } = await src("grafico");
  const h = graficoBarras([{ mes: "2026-08", ingresos: 1000, gastos: 500, saldo: 500 },
    { mes: "2026-09", ingresos: 2000, gastos: 0, saldo: 2000 }]);
  assert.match(h, /^<svg/);
  assert.equal(cuenta(h, '<rect class="ingresos"'), 2);
  assert.equal(cuenta(h, '<rect class="gastos"'), 2);
  const alturas = [...h.matchAll(/<rect class="(\w+)"[^>]*height="(\d+(?:\.\d+)?)"/g)].map((m) => [m[1], Number(m[2])]);
  assert.deepEqual(alturas, [["ingresos", 50], ["gastos", 25], ["ingresos", 100], ["gastos", 0]]);
  assert.match(graficoBarras([{ mes: "2026-01", ingresos: 0, gastos: 0, saldo: 0 }]), /height="0"/);
});

test("presupuestos: barra por categoría con clase de estado y tope 100", async () => {
  const { vistaPresupuestos } = await src("vista-presupuestos");
  const h = vistaPresupuestos([
    { categoria: "ocio", limite: 1000, gastado: 1500, restante: -500, porcentaje: 150, estado: "pasado" },
    { categoria: "comida", limite: 10000, gastado: 5000, restante: 5000, porcentaje: 50, estado: "ok" }]);
  assert.match(h, /class="presupuesto pasado" data-categoria="ocio"/);
  assert.match(h, /class="presupuesto ok" data-categoria="comida"/);
  assert.ok(h.includes('<progress value="100" max="100"'));
  assert.ok(h.includes('<progress value="50" max="100"'));
  assert.ok(h.includes('id="form-presupuesto"'));
});

test("formularios: movimiento, filtros e importar", async () => {
  const { formularioMovimiento } = await src("formulario");
  const f = formularioMovimiento({ concepto: '"Hola"', categoria: "ocio" }, ["falta concepto"]);
  assert.ok(f.includes('id="form-movimiento"'));
  for (const n of ["fecha", "concepto", "importe", "categoria"]) assert.ok(f.includes(`name="${n}"`), n);
  assert.equal(cuenta(f, "<option"), 8);
  assert.match(f, /<option value="ocio" selected/);
  assert.ok(f.includes('value="&quot;Hola&quot;"'));
  assert.match(f, /<p class="error">falta concepto<\/p>/);
  const { formularioFiltros } = await src("vista-filtros");
  const g = formularioFiltros({ mes: "2026-09", categoria: "comida", tipo: "gasto", texto: "pan" });
  assert.ok(g.includes('id="form-filtros"'));
  assert.ok(g.includes('name="mes" value="2026-09"') && g.includes('name="texto" value="pan"'));
  assert.match(g, /<option value="comida" selected/);
  assert.match(g, /<option value="gasto" selected/);
  const { vistaImportar } = await src("vista-importar");
  const i = vistaImportar(null);
  assert.ok(i.includes('<textarea name="csv"') && i.includes('id="exportar"') && !i.includes("Añadidos"));
  const j = vistaImportar({ anadidos: 3, errores: [{ linea: 4, motivo: "fecha <no> válida" }] });
  assert.ok(j.includes("Añadidos 3 movimientos") && j.includes("línea 4") && j.includes("&lt;no&gt;"));
});
