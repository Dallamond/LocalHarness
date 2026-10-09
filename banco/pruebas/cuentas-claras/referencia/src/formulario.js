import { escapar } from "./html.js";
import { CATEGORIAS } from "./movimientos.js";

export function formularioMovimiento(datos = {}, errores = []) {
  const v = (k) => escapar(datos[k] ?? "");
  const opciones = CATEGORIAS.map((c) => `<option value="${c}"${datos.categoria === c ? " selected" : ""}>${c}</option>`);
  return `<form id="form-movimiento">${errores.map((e) => `<p class="error">${escapar(e)}</p>`).join("")}`
    + `<label>Fecha <input type="date" name="fecha" value="${v("fecha")}" required></label>`
    + `<label>Concepto <input name="concepto" value="${v("concepto")}" required></label>`
    + `<label>Importe <input name="importe" inputmode="decimal" value="${v("importe")}" required></label>`
    + `<label>Categoría <select name="categoria">${opciones.join("")}</select></label>`
    + "<button>Guardar</button></form>";
}
