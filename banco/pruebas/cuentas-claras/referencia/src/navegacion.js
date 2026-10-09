import { crearRuta, VISTAS } from "./rutas.js";

const NOMBRES = { resumen: "Resumen", movimientos: "Movimientos", nuevo: "Nuevo", presupuestos: "Presupuestos",
  importar: "Importar" };

export function navegacion(vistaActual) {
  const enlaces = VISTAS.map((v) => `<a href="${crearRuta(v)}"${v === vistaActual ? ' aria-current="page"' : ""}>`
    + `${NOMBRES[v]}</a>`);
  return `<nav>${enlaces.join("")}</nav>`;
}
