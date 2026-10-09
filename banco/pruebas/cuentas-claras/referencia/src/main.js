// Lo único que toca el navegador: lee la ruta, pinta la vista y traduce formularios y clics en acciones.
import { aCsv, deCsv } from "./csv.js";
import { cargar, guardar } from "./almacen.js";
import { reducir } from "./estado.js";
import { filtrar } from "./filtros.js";
import { formularioMovimiento } from "./formulario.js";
import { navegacion } from "./navegacion.js";
import { estadoPresupuestos } from "./presupuestos.js";
import { crearRuta, leerRuta } from "./rutas.js";
import { formularioFiltros } from "./vista-filtros.js";
import { vistaImportar } from "./vista-importar.js";
import { tablaMovimientos } from "./vista-movimientos.js";
import { vistaPresupuestos } from "./vista-presupuestos.js";
import { vistaResumen } from "./vista-resumen.js";

let estado = cargar(localStorage);
let errores = [];
let importado = null;
const app = document.getElementById("app");
const mesActual = () => new Date().toISOString().slice(0, 7);

function cambiar(accion) {
  estado = reducir(estado, accion);
  guardar(localStorage, estado);
}

function pintar() {
  const { vista, params } = leerRuta(location.hash);
  const mes = params.mes || mesActual();
  let cuerpo;
  if (vista === "resumen") cuerpo = vistaResumen(estado, mes);
  else if (vista === "movimientos") cuerpo = formularioFiltros(params) + tablaMovimientos(filtrar(estado.movimientos, params));
  else if (vista === "nuevo") cuerpo = formularioMovimiento({}, errores);
  else if (vista === "presupuestos") cuerpo = vistaPresupuestos(estadoPresupuestos(estado.presupuestos, estado.movimientos, mes));
  else if (vista === "importar") cuerpo = vistaImportar(importado);
  else cuerpo = '<p class="vacio">Esta página no existe</p>';
  app.innerHTML = navegacion(vista) + cuerpo;
}

app.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const datos = Object.fromEntries(new FormData(ev.target));
  errores = [];
  try {
    if (ev.target.id === "form-movimiento") {
      cambiar({ tipo: "anadir", datos });
      location.hash = crearRuta("movimientos");
    } else if (ev.target.id === "form-presupuesto") cambiar({ tipo: "presupuesto", ...datos });
    else if (ev.target.id === "form-importar") {
      const r = deCsv(datos.csv, estado.siguienteId);
      cambiar({ tipo: "importar", texto: datos.csv });
      importado = { anadidos: r.movimientos.length, errores: r.errores };
    } else if (ev.target.id === "form-filtros") location.hash = crearRuta("movimientos", datos);
  } catch (e) {
    errores = [e.message];
  }
  pintar();
});

app.addEventListener("click", (ev) => {
  const borrar = ev.target.closest("[data-borrar]");
  if (borrar) {
    cambiar({ tipo: "borrar", id: Number(borrar.dataset.borrar) });
    pintar();
  }
  if (ev.target.id === "exportar") {
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(new Blob([aCsv(estado.movimientos)], { type: "text/csv" }));
    enlace.download = "cuentas.csv";
    enlace.click();
  }
});

window.addEventListener("hashchange", () => {
  importado = null;
  pintar();
});
pintar();
