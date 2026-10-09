import { escapar } from "./html.js";
import { CATEGORIAS } from "./movimientos.js";

export function formularioFiltros(filtro = {}) {
  const sel = (a, b) => (a === b ? " selected" : "");
  const cats = ['<option value="">todas</option>',
    ...CATEGORIAS.map((c) => `<option value="${c}"${sel(filtro.categoria, c)}>${c}</option>`)];
  const tipos = ["todos", "gasto", "ingreso"].map((t) => `<option value="${t}"${sel(filtro.tipo || "todos", t)}>${t}</option>`);
  return `<form id="form-filtros"><input type="month" name="mes" value="${escapar(filtro.mes ?? "")}">`
    + `<select name="categoria">${cats.join("")}</select><select name="tipo">${tipos.join("")}</select>`
    + `<input type="search" name="texto" value="${escapar(filtro.texto ?? "")}" placeholder="Buscar"><button>Filtrar</button></form>`;
}
