import { test } from "node:test";
import assert from "node:assert/strict";
import { mov, src } from "./ayuda.mjs";

test("dinero: aCentimos entiende formatos españoles y rechaza basura", async () => {
  const { aCentimos } = await src("dinero");
  assert.equal(aCentimos("12,50"), 1250);
  assert.equal(aCentimos("12.5"), 1250);
  assert.equal(aCentimos("1.234,56"), 123456);
  assert.equal(aCentimos("1.234"), 123400);
  assert.equal(aCentimos("-3"), -300);
  assert.equal(aCentimos(" 7 € "), 700);
  assert.equal(aCentimos("+2,5"), 250);
  assert.equal(aCentimos(4.1), 410);
  for (const malo of ["abc", "", "1,234", "12,", "1,2,3"]) assert.throws(() => aCentimos(malo), /importe no válido/, malo);
});

test("dinero: formatear con miles, coma y euro", async () => {
  const { formatear } = await src("dinero");
  assert.equal(formatear(123456), "1.234,56 €");
  assert.equal(formatear(-300), "-3,00 €");
  assert.equal(formatear(0), "0,00 €");
  assert.equal(formatear(5), "0,05 €");
  assert.equal(formatear(100000000), "1.000.000,00 €");
});

test("fechas: validez, meses y bisiestos", async () => {
  const f = await src("fechas");
  assert.equal(f.esFechaValida("2026-02-28"), true);
  assert.equal(f.esFechaValida("2026-02-30"), false);
  assert.equal(f.esFechaValida("2024-02-29"), true);
  assert.equal(f.esFechaValida("2026-13-01"), false);
  assert.equal(f.esFechaValida("9/10/2026"), false);
  assert.equal(f.mesDe("2026-10-09"), "2026-10");
  assert.equal(f.diasDelMes("2024-02"), 29);
  assert.equal(f.diasDelMes("1900-02"), 28);
  assert.equal(f.diasDelMes("2026-04"), 30);
  assert.equal(f.sumarMeses("2026-12", 1), "2027-01");
  assert.equal(f.sumarMeses("2026-01", -1), "2025-12");
  assert.equal(f.sumarMeses("2026-05", -17), "2024-12");
  assert.equal(f.nombreMes("2026-10"), "octubre 2026");
});

test("movimientos: crear valida y normaliza", async () => {
  const { crearMovimiento, CATEGORIAS } = await src("movimientos");
  assert.deepEqual(CATEGORIAS, ["comida", "casa", "transporte", "ocio", "salud", "ropa", "ingresos", "otros"]);
  assert.deepEqual(crearMovimiento({ fecha: "2026-10-01", concepto: "  Pan ", importe: "-1,20" }, 7),
    { id: 7, fecha: "2026-10-01", concepto: "Pan", centimos: -120, categoria: "otros" });
  assert.throws(() => crearMovimiento({ fecha: "2026-02-30", concepto: "x", importe: "1" }, 1), /fecha no válida/);
  assert.throws(() => crearMovimiento({ fecha: "2026-02-01", concepto: "  ", importe: "1" }, 1), /falta concepto/);
  assert.throws(() => crearMovimiento({ fecha: "2026-02-01", concepto: "x", importe: "1", categoria: "viajes" }, 1),
    /categoría no válida/);
  assert.throws(() => crearMovimiento({ fecha: "2026-02-01", concepto: "x", importe: "0" }, 1), /importe cero/);
});

test("movimientos: ordenar, añadir, borrar y editar sin tocar el original", async () => {
  const { anadir, borrar, editar, ordenar } = await src("movimientos");
  const lista = [mov(1, "2026-09-01", -100), mov(2, "2026-09-03", -200), mov(3, "2026-09-01", 500)];
  const copia = structuredClone(lista);
  assert.deepEqual(ordenar(lista).map((m) => m.id), [2, 3, 1]);
  assert.deepEqual(anadir(lista, mov(4, "2026-09-02", -1)).map((m) => m.id), [2, 4, 3, 1]);
  assert.deepEqual(borrar(lista, 2).map((m) => m.id), [1, 3]);
  const ed = editar(lista, 1, { fecha: "2026-09-09", centimos: -999 });
  assert.deepEqual(ed[0], { ...lista[0], fecha: "2026-09-09", centimos: -999 });
  assert.deepEqual(lista, copia);
});

test("filtros: mes, categoría, tipo y texto sin tildes ni mayúsculas", async () => {
  const { filtrar, normalizar } = await src("filtros");
  assert.equal(normalizar("Panadería ÁRBOL"), "panaderia arbol");
  const lista = [mov(1, "2026-09-01", -100, "comida", "Panadería"), mov(2, "2026-10-01", 500, "ingresos", "Nómina"),
    mov(3, "2026-09-05", -50, "ocio", "Cine"), mov(4, "2026-09-07", 30, "ingresos", "Vinted")];
  assert.deepEqual(filtrar(lista, {}).map((m) => m.id), [1, 2, 3, 4]);
  assert.deepEqual(filtrar(lista, { mes: "2026-09" }).map((m) => m.id), [1, 3, 4]);
  assert.deepEqual(filtrar(lista, { categoria: "ocio" }).map((m) => m.id), [3]);
  assert.deepEqual(filtrar(lista, { tipo: "gasto" }).map((m) => m.id), [1, 3]);
  assert.deepEqual(filtrar(lista, { tipo: "ingreso", mes: "2026-09" }).map((m) => m.id), [4]);
  assert.deepEqual(filtrar(lista, { texto: "PANADERIA" }).map((m) => m.id), [1]);
  assert.deepEqual(filtrar(lista, { texto: "nomina" }).map((m) => m.id), [2]);
});

test("resumen: ingresos, gastos, saldo y categorías del mes", async () => {
  const { resumenMes, saldoHasta, evolucion } = await src("resumen");
  const lista = [mov(1, "2026-09-01", 100000, "ingresos"), mov(2, "2026-09-02", -2000, "comida"),
    mov(3, "2026-09-03", -3000, "ocio"), mov(4, "2026-09-04", -1000, "comida"), mov(5, "2026-08-30", -500, "casa"),
    mov(6, "2026-09-05", -3000, "casa")];
  assert.deepEqual(resumenMes(lista, "2026-09"), { mes: "2026-09", ingresos: 100000, gastos: 9000, saldo: 91000,
    porCategoria: [{ categoria: "casa", centimos: 3000 }, { categoria: "comida", centimos: 3000 },
      { categoria: "ocio", centimos: 3000 }], numero: 5 });
  assert.deepEqual(resumenMes(lista, "2026-07"), { mes: "2026-07", ingresos: 0, gastos: 0, saldo: 0, porCategoria: [],
    numero: 0 });
  assert.equal(saldoHasta(lista, "2026-08"), -500);
  assert.equal(saldoHasta(lista, "2026-09"), 90500);
  assert.deepEqual(evolucion(lista, "2026-09", 3).map((e) => [e.mes, e.ingresos, e.gastos, e.saldo]),
    [["2026-07", 0, 0, 0], ["2026-08", 0, 500, -500], ["2026-09", 100000, 9000, 91000]]);
});

test("presupuestos: porcentaje, estado y orden", async () => {
  const { estadoPresupuestos } = await src("presupuestos");
  const lista = [mov(1, "2026-09-01", -4000, "comida"), mov(2, "2026-09-02", -1000, "comida"),
    mov(3, "2026-09-03", -1050, "ocio"), mov(4, "2026-08-03", -9999, "ocio"), mov(5, "2026-09-04", 5000, "ocio")];
  assert.deepEqual(estadoPresupuestos({ comida: 10000, ocio: 1000, ropa: 2000, salud: 0 }, lista, "2026-09"), [
    { categoria: "ocio", limite: 1000, gastado: 1050, restante: -50, porcentaje: 105, estado: "pasado" },
    { categoria: "comida", limite: 10000, gastado: 5000, restante: 5000, porcentaje: 50, estado: "ok" },
    { categoria: "ropa", limite: 2000, gastado: 0, restante: 2000, porcentaje: 0, estado: "ok" }]);
  const [e] = estadoPresupuestos({ comida: 5000 }, [mov(1, "2026-09-01", -4000)], "2026-09");
  assert.equal(e.estado, "aviso");
  const [f] = estadoPresupuestos({ comida: 5000 }, [mov(1, "2026-09-01", -5000)], "2026-09");
  assert.equal(f.estado, "aviso");
});
