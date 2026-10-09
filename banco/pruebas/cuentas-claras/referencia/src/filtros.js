import { mesDe } from "./fechas.js";

export const normalizar = (texto) => String(texto).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function filtrar(lista, filtro = {}) {
  const { mes, categoria, texto, tipo = "todos" } = filtro;
  const buscado = texto ? normalizar(texto) : "";
  return lista.filter((m) => (!mes || mesDe(m.fecha) === mes)
    && (!categoria || m.categoria === categoria)
    && (tipo === "todos" || (tipo === "gasto" ? m.centimos < 0 : m.centimos > 0))
    && (!buscado || normalizar(m.concepto).includes(buscado)));
}
