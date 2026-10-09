export const CLAVE = "cuentas-claras";

export const estadoVacio = () => ({ version: 1, movimientos: [], presupuestos: {}, siguienteId: 1 });

export function cargar(almacen) {
  try {
    const e = JSON.parse(almacen.getItem(CLAVE));
    if (!e || e.version !== 1 || !Array.isArray(e.movimientos)) return estadoVacio();
    return { ...estadoVacio(), ...e };
  } catch {
    return estadoVacio();
  }
}

export function guardar(almacen, estado) {
  almacen.setItem(CLAVE, JSON.stringify(estado));
}
