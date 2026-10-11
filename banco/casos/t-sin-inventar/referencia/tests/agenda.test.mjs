import { test } from "node:test";
import assert from "node:assert/strict";
import { proximaCita } from "../src/agenda.js";

const citas = [
  { titulo: "dentista", fecha: "2026-10-20T10:00" },
  { titulo: "clase", fecha: "2026-10-12T09:00" },
  { titulo: "cena", fecha: "2026-10-15T21:00" },
];

test("la más temprana desde ahora, aunque la lista esté desordenada", () => {
  assert.deepEqual(proximaCita(citas, "2026-10-13T00:00"), { titulo: "cena", fecha: "2026-10-15T21:00" });
});

test("una cita justo a la hora de ahora cuenta", () => {
  assert.equal(proximaCita(citas, "2026-10-12T09:00").titulo, "clase");
});

test("null si no queda ninguna", () => {
  assert.equal(proximaCita(citas, "2026-11-01T00:00"), null);
  assert.equal(proximaCita([], "2026-01-01T00:00"), null);
});
