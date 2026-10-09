// Examen oculto de «Cuentas claras»: los modelos no lo ven. Se corre con PROYECTO=<ruta> (banco/puntuar.mjs).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const RAIZ = process.env.PROYECTO;
if (!RAIZ) throw new Error("falta PROYECTO=<ruta del proyecto>");

/** Importa src/<nombre>.js del proyecto examinado (si no carga, el test que lo usa falla). */
export const src = (nombre) => import(pathToFileURL(join(RAIZ, "src", `${nombre}.js`)).href);

export const ejemplo = () => readFileSync(join(RAIZ, "docs", "ejemplo.csv"), "utf8");

/** Movimiento ya creado, sin pasar por crearMovimiento. */
export const mov = (id, fecha, centimos, categoria = "comida", concepto = `m${id}`) =>
  ({ id, fecha, concepto, centimos, categoria });

export const cuenta = (texto, trozo) => texto.split(trozo).length - 1;
