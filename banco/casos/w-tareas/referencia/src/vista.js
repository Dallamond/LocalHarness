// vistaLista(tareas): la lista como HTML (el texto, escapado).
export const escapar = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function vistaLista(tareas) {
  const items = tareas.map((t) => `<li data-id="${t.id}" class="${t.hecha ? "hecha" : "pendiente"}">${escapar(t.texto)}</li>`);
  return `<ul class="tareas">${items.join("")}</ul>`;
}
