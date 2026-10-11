// Inventario: {sku: unidades}. Las funciones devuelven un inventario nuevo, sin tocar el que reciben.
export function crearInventario() {
  return {};
}

function comprobar(n) {
  if (!Number.isInteger(n) || n <= 0) throw new Error("cantidad no válida");
}

export function anadir(inv, sku, n) {
  comprobar(n);
  return { ...inv, [sku]: (inv[sku] ?? 0) + n };
}

export function quitar(inv, sku, n) {
  comprobar(n);
  const hay = inv[sku] ?? 0;
  if (hay < n) throw new Error("no hay bastante");
  const nuevo = { ...inv };
  if (hay === n) delete nuevo[sku];
  else nuevo[sku] = hay - n;
  return nuevo;
}

export function total(inv) {
  return Object.values(inv).reduce((a, b) => a + b, 0);
}
