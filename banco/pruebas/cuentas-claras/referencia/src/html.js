const CAMBIOS = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export const escapar = (texto) => String(texto ?? "").replace(/[&<>"']/g, (c) => CAMBIOS[c]);
