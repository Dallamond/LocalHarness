// Guardar y cargar la lista en un almacén con getItem/setItem (localStorage en el navegador).
export const CLAVE = "tareas-v1";

export function guardar(almacen, tareas) {
  almacen.setItem(CLAVE, JSON.stringify(tareas));
}

export function cargar(almacen) {
  try {
    const datos = JSON.parse(almacen.getItem(CLAVE));
    return Array.isArray(datos) ? datos : [];
  } catch {
    return [];
  }
}
