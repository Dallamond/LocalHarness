import { crearMovimiento } from "./movimientos.js";

export const CABECERA = "fecha;concepto;importe;categoria";

export function importeCsv(centimos) {
  const abs = Math.abs(centimos);
  return `${centimos < 0 ? "-" : ""}${Math.floor(abs / 100)},${String(abs % 100).padStart(2, "0")}`;
}

const campo = (t) => (/[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t);

export function aCsv(lista) {
  const filas = lista.map((m) => [m.fecha, campo(m.concepto), importeCsv(m.centimos), m.categoria].join(";"));
  return [CABECERA, ...filas].join("\n") + "\n";
}

export function partirLinea(linea) {
  const campos = [];
  let actual = "";
  let comillas = false;
  for (let i = 0; i < linea.length; i++) {
    const c = linea[i];
    if (comillas) {
      if (c === '"' && linea[i + 1] === '"') {
        actual += '"';
        i++;
      } else if (c === '"') comillas = false;
      else actual += c;
    } else if (c === '"') comillas = true;
    else if (c === ";") {
      campos.push(actual);
      actual = "";
    } else actual += c;
  }
  campos.push(actual);
  return campos;
}

export function deCsv(texto, primerId = 1) {
  const lineas = String(texto).replace(/^﻿/, "").split(/\r?\n/);
  const movimientos = [];
  const errores = [];
  let cabecera = false;
  let id = primerId;
  for (let i = 0; i < lineas.length; i++) {
    if (!lineas[i].trim()) continue;
    if (!cabecera) {
      if (lineas[i].trim().toLowerCase() !== CABECERA) {
        return { movimientos: [], errores: [{ linea: i + 1, motivo: "cabecera no válida" }] };
      }
      cabecera = true;
      continue;
    }
    const c = partirLinea(lineas[i]);
    if (c.length < 4) {
      errores.push({ linea: i + 1, motivo: "faltan columnas" });
      continue;
    }
    try {
      movimientos.push(crearMovimiento({ fecha: c[0].trim(), concepto: c[1], importe: c[2], categoria: c[3].trim() }, id));
      id++;
    } catch (e) {
      errores.push({ linea: i + 1, motivo: e.message });
    }
  }
  return { movimientos, errores };
}
