// Lista de tareas: [{id, texto, hecha}]. Las funciones devuelven listas nuevas.
export function anadir(tareas, texto, id) {
  const t = texto.trim();
  if (!t) throw new Error("texto vacío");
  return [...tareas, { id, texto: t, hecha: false }];
}

export function completar(tareas, id) {
  return tareas.map((t) => (t.id === id ? { ...t, hecha: !t.hecha } : t));
}

export function borrar(tareas, id) {
  return tareas.filter((t) => t.id !== id);
}

export function filtrar(tareas, filtro) {
  if (filtro === "pendientes") return tareas.filter((t) => !t.hecha);
  if (filtro === "hechas") return tareas.filter((t) => t.hecha);
  return tareas;
}

export function contar(tareas) {
  const hechas = tareas.filter((t) => t.hecha).length;
  return { total: tareas.length, pendientes: tareas.length - hechas, hechas };
}
