import { mesDe } from "./fechas.js";

export function estadoPresupuestos(presupuestos, lista, mes) {
  return Object.entries(presupuestos).filter(([, limite]) => limite > 0).map(([categoria, limite]) => {
    const gastado = lista.filter((m) => m.categoria === categoria && m.centimos < 0 && mesDe(m.fecha) === mes)
      .reduce((s, m) => s - m.centimos, 0);
    const porcentaje = Math.round((gastado * 100) / limite);
    const estado = porcentaje < 80 ? "ok" : porcentaje <= 100 ? "aviso" : "pasado";
    return { categoria, limite, gastado, restante: limite - gastado, porcentaje, estado };
  }).sort((a, b) => b.porcentaje - a.porcentaje || (a.categoria < b.categoria ? -1 : 1));
}
