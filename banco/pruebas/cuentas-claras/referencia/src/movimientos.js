import { aCentimos } from "./dinero.js";
import { esFechaValida } from "./fechas.js";

export const CATEGORIAS = ["comida", "casa", "transporte", "ocio", "salud", "ropa", "ingresos", "otros"];

export function crearMovimiento(datos, id) {
  if (!esFechaValida(datos.fecha)) throw new Error("fecha no válida");
  const concepto = String(datos.concepto ?? "").trim();
  if (!concepto) throw new Error("falta concepto");
  const categoria = datos.categoria || "otros";
  if (!CATEGORIAS.includes(categoria)) throw new Error("categoría no válida");
  const centimos = aCentimos(datos.importe);
  if (centimos === 0) throw new Error("importe cero");
  return { id, fecha: datos.fecha, concepto, centimos, categoria };
}

export const ordenar = (lista) =>
  [...lista].sort((a, b) => (a.fecha === b.fecha ? b.id - a.id : a.fecha < b.fecha ? 1 : -1));

export const anadir = (lista, mov) => ordenar([...lista, mov]);

export const borrar = (lista, id) => lista.filter((m) => m.id !== id);

export const editar = (lista, id, cambios) => ordenar(lista.map((m) => (m.id === id ? { ...m, ...cambios, id } : m)));
