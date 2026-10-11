import { test } from "node:test";
import assert from "node:assert/strict";
import { crearCarrito, anadir, subtotal, total } from "../src/carrito.js";

test("añadir junta el mismo sku", () => {
  const c = anadir(anadir(crearCarrito(), "a", 100), "a", 100, 2);
  assert.deepEqual(c.lineas, [{ sku: "a", precio: 100, cantidad: 3 }]);
});

test("subtotal y total", () => {
  const c = anadir(anadir(crearCarrito(), "a", 250, 2), "b", 99);
  assert.equal(subtotal(c), 599);
  assert.equal(total(c), 599);
});

test("cupón DIEZ", async () => {
  const { aplicarCupon } = await import("../src/carrito.js");
  assert.equal(total(aplicarCupon(anadir(crearCarrito(), "a", 1999), "DIEZ")), 1799);
});
