// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("lo que ya hacía sigue igual", async () => {
  verde(4);
  const { crearCarrito, anadir, subtotal, total } = await src("src/carrito.js");
  const c = anadir(anadir(anadir(crearCarrito(), "a", 300), "b", 50, 4), "a", 300);
  assert.deepEqual(c.lineas, [{ sku: "a", precio: 300, cantidad: 2 }, { sku: "b", precio: 50, cantidad: 4 }]);
  assert.equal(subtotal(c), 800);
  assert.equal(total(c), 800);
});

test("cupón DIEZ quita el 10 % redondeado", async () => {
  const { crearCarrito, anadir, aplicarCupon, subtotal, total } = await src("src/carrito.js");
  const c = aplicarCupon(anadir(crearCarrito(), "a", 1999), "DIEZ");
  assert.equal(c.cupon, "DIEZ");
  assert.equal(subtotal(c), 1999);
  assert.equal(total(c), 1799);
});

test("cupón ENVIO no baja de 0", async () => {
  const { crearCarrito, anadir, aplicarCupon, total } = await src("src/carrito.js");
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 1000), "ENVIO")), 501);
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 300), "ENVIO")), 0);
});

test("cupón que no existe y sin modificar el carrito", async () => {
  const { crearCarrito, anadir, aplicarCupon } = await src("src/carrito.js");
  const c = anadir(crearCarrito(), "a", 100);
  Object.freeze(c);
  Object.freeze(c.lineas);
  assert.throws(() => aplicarCupon(c, "GRATIS"), /cupón no válido/);
  assert.equal(aplicarCupon(c, "DIEZ").cupon, "DIEZ");
  assert.equal(c.cupon, undefined);
});
