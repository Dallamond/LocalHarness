import { mesDe, sumarMeses } from "./fechas.js";

export function resumenMes(lista, mes) {
  const delMes = lista.filter((m) => mesDe(m.fecha) === mes);
  let ingresos = 0;
  let gastos = 0;
  const cats = {};
  for (const m of delMes) {
    if (m.centimos > 0) ingresos += m.centimos;
    else {
      gastos -= m.centimos;
      cats[m.categoria] = (cats[m.categoria] || 0) - m.centimos;
    }
  }
  const porCategoria = Object.entries(cats).map(([categoria, centimos]) => ({ categoria, centimos }))
    .sort((a, b) => b.centimos - a.centimos || (a.categoria < b.categoria ? -1 : 1));
  return { mes, ingresos, gastos, saldo: ingresos - gastos, porCategoria, numero: delMes.length };
}

export const saldoHasta = (lista, mes) =>
  lista.filter((m) => mesDe(m.fecha) <= mes).reduce((s, m) => s + m.centimos, 0);

export function evolucion(lista, mes, n) {
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const { ingresos, gastos, saldo } = resumenMes(lista, sumarMeses(mes, -i));
    out.push({ mes: sumarMeses(mes, -i), ingresos, gastos, saldo });
  }
  return out;
}
