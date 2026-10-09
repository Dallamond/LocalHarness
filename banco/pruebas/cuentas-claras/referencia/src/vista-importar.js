import { escapar } from "./html.js";

export function vistaImportar(resultado) {
  let aviso = "";
  if (resultado) {
    const errores = resultado.errores.map((e) => `<li>línea ${e.linea}: ${escapar(e.motivo)}</li>`).join("");
    aviso = `<p class="aviso">Añadidos ${resultado.anadidos} movimientos</p>${errores ? `<ul class="errores">${errores}</ul>` : ""}`;
  }
  return `<section class="importar">${aviso}<form id="form-importar"><label>CSV (fecha;concepto;importe;categoria)`
    + '<textarea name="csv" rows="10"></textarea></label><button>Importar</button></form>'
    + '<button type="button" id="exportar">Exportar CSV</button></section>';
}
