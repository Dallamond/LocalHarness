import { aCentimos } from "./dinero.js";
import { anadir, borrar, crearMovimiento, ordenar } from "./movimientos.js";
import { deCsv } from "./csv.js";

export function reducir(estado, accion) {
  switch (accion.tipo) {
    case "anadir": {
      const mov = crearMovimiento(accion.datos, estado.siguienteId);
      return { ...estado, movimientos: anadir(estado.movimientos, mov), siguienteId: estado.siguienteId + 1 };
    }
    case "borrar":
      return { ...estado, movimientos: borrar(estado.movimientos, accion.id) };
    case "editar": {
      const mov = crearMovimiento(accion.datos, accion.id);
      return { ...estado, movimientos: ordenar(estado.movimientos.map((m) => (m.id === accion.id ? mov : m))) };
    }
    case "presupuesto": {
      const presupuestos = { ...estado.presupuestos };
      const limite = accion.importe === "" || accion.importe == null ? 0 : aCentimos(accion.importe);
      if (limite > 0) presupuestos[accion.categoria] = limite;
      else delete presupuestos[accion.categoria];
      return { ...estado, presupuestos };
    }
    case "importar": {
      const { movimientos } = deCsv(accion.texto, estado.siguienteId);
      return { ...estado, movimientos: ordenar([...estado.movimientos, ...movimientos]),
        siguienteId: estado.siguienteId + movimientos.length };
    }
    default:
      throw new Error("acción desconocida");
  }
}
