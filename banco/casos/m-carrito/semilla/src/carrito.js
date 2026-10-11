// Carrito: {lineas: [{sku, precio (céntimos), cantidad}]}. Las funciones no modifican el carrito que reciben.
export function crearCarrito() {
  return { lineas: [] };
}

export function anadir(carrito, sku, precio, cantidad = 1) {
  const hay = carrito.lineas.find((l) => l.sku === sku);
  const lineas = hay
    ? carrito.lineas.map((l) => (l.sku === sku ? { ...l, cantidad: l.cantidad + cantidad } : l))
    : [...carrito.lineas, { sku, precio, cantidad }];
  return { ...carrito, lineas };
}

export function subtotal(carrito) {
  return carrito.lineas.reduce((a, l) => a + l.precio * l.cantidad, 0);
}

export function total(carrito) {
  return subtotal(carrito);
}
