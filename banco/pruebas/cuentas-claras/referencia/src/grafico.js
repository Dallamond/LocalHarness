// Barras de ingresos y gastos por mes: la más alta mide 100 de alto; el resto, en proporción.
export function graficoBarras(evo) {
  const max = Math.max(1, ...evo.map((e) => Math.max(e.ingresos, e.gastos)));
  const barras = evo.map((e, i) => {
    const hi = Math.round((e.ingresos * 100) / max);
    const hg = Math.round((e.gastos * 100) / max);
    const x = i * 40;
    return `<rect class="ingresos" data-mes="${e.mes}" x="${x}" y="${100 - hi}" width="16" height="${hi}"></rect>`
      + `<rect class="gastos" data-mes="${e.mes}" x="${x + 18}" y="${100 - hg}" width="16" height="${hg}"></rect>`;
  });
  return `<svg class="grafico" viewBox="0 0 ${evo.length * 40} 100" role="img" aria-label="Ingresos y gastos por mes">`
    + `${barras.join("")}</svg>`;
}
