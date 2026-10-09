import { test } from "node:test";
import assert from "node:assert/strict";
import { ejemplo, mov, src } from "./ayuda.mjs";

test("csv: exportar con cabecera, coma decimal y comillas cuando hace falta", async () => {
  const { aCsv, importeCsv } = await src("csv");
  assert.equal(importeCsv(-123456), "-1234,56");
  assert.equal(importeCsv(5), "0,05");
  assert.equal(aCsv([mov(1, "2026-09-01", -1250, "ocio", 'Bar "Pepe"; cañas'), mov(2, "2026-09-02", 3000, "ingresos", "Venta")]),
    'fecha;concepto;importe;categoria\n2026-09-01;"Bar ""Pepe""; cañas";-12,50;ocio\n2026-09-02;Venta;30,00;ingresos\n');
  assert.equal(aCsv([]), "fecha;concepto;importe;categoria\n");
});

test("csv: importar con errores por línea, BOM, \\r\\n e ids seguidos", async () => {
  const { deCsv } = await src("csv");
  const texto = "﻿fecha;concepto;importe;categoria\r\n2026-09-01;Pan;-1,20;comida\r\n\r\n2026-02-30;Mal;-1;comida\r\n"
    + "2026-09-02;Solo tres;-1\r\n2026-09-03;\"Uno; dos\";5;ingresos\r\n";
  const r = deCsv(texto, 10);
  assert.deepEqual(r.movimientos, [
    { id: 10, fecha: "2026-09-01", concepto: "Pan", centimos: -120, categoria: "comida" },
    { id: 11, fecha: "2026-09-03", concepto: "Uno; dos", centimos: 500, categoria: "ingresos" }]);
  assert.deepEqual(r.errores, [{ linea: 4, motivo: "fecha no válida" }, { linea: 5, motivo: "faltan columnas" }]);
  assert.deepEqual(deCsv("hola;que;tal\n2026-09-01;Pan;-1;comida\n"),
    { movimientos: [], errores: [{ linea: 1, motivo: "cabecera no válida" }] });
});

test("csv: el ejemplo de docs/ entra entero y vuelve igual", async () => {
  const { aCsv, deCsv } = await src("csv");
  const r = deCsv(ejemplo());
  assert.equal(r.movimientos.length, 30);
  assert.deepEqual(r.errores, []);
  assert.equal(r.movimientos[9].concepto, 'Bar "El Tranco"; cañas');
  const sinId = (l) => l.map(({ id, ...m }) => m);
  assert.deepEqual(sinId(deCsv(aCsv(r.movimientos)).movimientos), sinId(r.movimientos));
});

test("almacen: guardar y cargar; lo roto o antiguo da estado vacío", async () => {
  const { CLAVE, cargar, estadoVacio, guardar } = await src("almacen");
  const mapa = new Map();
  const almacen = { getItem: (k) => (mapa.has(k) ? mapa.get(k) : null), setItem: (k, v) => mapa.set(k, String(v)) };
  assert.equal(CLAVE, "cuentas-claras");
  assert.deepEqual(estadoVacio(), { version: 1, movimientos: [], presupuestos: {}, siguienteId: 1 });
  assert.deepEqual(cargar(almacen), estadoVacio());
  const e = { version: 1, movimientos: [mov(1, "2026-09-01", -5)], presupuestos: { ocio: 100 }, siguienteId: 2 };
  guardar(almacen, e);
  assert.deepEqual(cargar(almacen), e);
  mapa.set(CLAVE, "{roto");
  assert.deepEqual(cargar(almacen), estadoVacio());
  mapa.set(CLAVE, JSON.stringify({ version: 0, movimientos: [] }));
  assert.deepEqual(cargar(almacen), estadoVacio());
});

test("estado: reducir añade, edita, borra, presupuesta e importa", async () => {
  const { reducir } = await src("estado");
  const { estadoVacio } = await src("almacen");
  const vacio = estadoVacio();
  let e = reducir(vacio, { tipo: "anadir", datos: { fecha: "2026-09-01", concepto: "Pan", importe: "-1,20", categoria: "comida" } });
  e = reducir(e, { tipo: "anadir", datos: { fecha: "2026-09-05", concepto: "Cine", importe: "-8", categoria: "ocio" } });
  assert.deepEqual(vacio, estadoVacio());
  assert.equal(e.siguienteId, 3);
  assert.deepEqual(e.movimientos.map((m) => m.id), [2, 1]);
  e = reducir(e, { tipo: "editar", id: 1, datos: { fecha: "2026-09-09", concepto: "Pan", importe: "-2", categoria: "comida" } });
  assert.deepEqual(e.movimientos.map((m) => [m.id, m.centimos]), [[1, -200], [2, -800]]);
  e = reducir(e, { tipo: "borrar", id: 2 });
  assert.deepEqual(e.movimientos.map((m) => m.id), [1]);
  e = reducir(e, { tipo: "presupuesto", categoria: "comida", importe: "150" });
  assert.deepEqual(e.presupuestos, { comida: 15000 });
  e = reducir(e, { tipo: "presupuesto", categoria: "comida", importe: "" });
  assert.deepEqual(e.presupuestos, {});
  e = reducir(e, { tipo: "importar", texto: "fecha;concepto;importe;categoria\n2026-10-01;A;-1;otros\nmal\n2026-10-02;B;2;ingresos\n" });
  assert.equal(e.siguienteId, 5);
  assert.deepEqual(e.movimientos.map((m) => m.id), [4, 3, 1]);
  assert.throws(() => reducir(e, { tipo: "anadir", datos: { fecha: "x", concepto: "a", importe: "1" } }), /fecha no válida/);
  assert.throws(() => reducir(e, { tipo: "volar" }), /acción desconocida/);
});

test("rutas: leer y crear hashes", async () => {
  const { VISTAS, crearRuta, leerRuta } = await src("rutas");
  assert.deepEqual(VISTAS, ["resumen", "movimientos", "nuevo", "presupuestos", "importar"]);
  assert.deepEqual(leerRuta(""), { vista: "resumen", params: {} });
  assert.deepEqual(leerRuta("#/"), { vista: "resumen", params: {} });
  assert.deepEqual(leerRuta("#/movimientos?mes=2026-10&categoria=comida"),
    { vista: "movimientos", params: { mes: "2026-10", categoria: "comida" } });
  assert.deepEqual(leerRuta("#/movimientos?texto=caf%C3%A9%20con"), { vista: "movimientos", params: { texto: "café con" } });
  assert.deepEqual(leerRuta("#/marte"), { vista: "no-encontrada", params: {} });
  assert.equal(crearRuta("resumen"), "#/resumen");
  assert.equal(crearRuta("movimientos", { mes: "2026-10", categoria: "comida", texto: "" }),
    "#/movimientos?categoria=comida&mes=2026-10");
  assert.equal(crearRuta("movimientos", { texto: "café con" }), "#/movimientos?texto=caf%C3%A9%20con");
});

test("todo junto: el ejemplo importado da las cuentas de septiembre", async () => {
  const { reducir } = await src("estado");
  const { estadoVacio } = await src("almacen");
  const { resumenMes, saldoHasta } = await src("resumen");
  const { estadoPresupuestos } = await src("presupuestos");
  let e = reducir(estadoVacio(), { tipo: "importar", texto: ejemplo() });
  assert.equal(e.siguienteId, 31);
  const r = resumenMes(e.movimientos, "2026-09");
  assert.deepEqual([r.ingresos, r.gastos, r.saldo, r.numero], [125750, 71825, 53925, 18]);
  assert.deepEqual(r.porCategoria.map((c) => c.categoria), ["casa", "comida", "transporte", "ropa", "ocio", "salud"]);
  assert.equal(saldoHasta(e.movimientos, "2026-09"), 133045);
  for (const [categoria, importe] of [["comida", "150"], ["ocio", "50"], ["transporte", "200"]]) {
    e = reducir(e, { tipo: "presupuesto", categoria, importe });
  }
  assert.deepEqual(estadoPresupuestos(e.presupuestos, e.movimientos, "2026-09").map((p) => [p.categoria, p.porcentaje, p.estado]),
    [["ocio", 102, "pasado"], ["comida", 99, "aviso"], ["transporte", 56, "ok"]]);
});
