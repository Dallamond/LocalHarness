// Examen oculto de «Supersalto»: los casos exactos de autopilot/mario.md, en tests que los modelos no ven.
// Se corre contra una copia del proyecto con PROYECTO=<ruta> (lo hace examenes/puntuar.mjs).
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const RAIZ = process.env.PROYECTO;
if (!RAIZ) throw new Error("falta PROYECTO=<ruta del proyecto>");

/** Importa src/<nombre>.js del proyecto examinado (si no carga, el test que lo usa falla). */
export const src = (nombre) => import(pathToFileURL(join(RAIZ, "src", `${nombre}.js`)).href);

export const cerca = (a, b) => Math.abs(a - b) < 1e-9;

/** Cuerpo 16×16 quieto, con lo que se le cambie. */
export const cuerpo = (o) => ({ ancho: 16, alto: 16, vx: 0, vy: 0, enSuelo: false, ...o });
