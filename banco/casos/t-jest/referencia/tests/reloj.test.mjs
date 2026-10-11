import { test } from "node:test";
import assert from "node:assert/strict";
import { formatear, aSegundos } from "../src/reloj.js";

test("formatea minutos y segundos", () => {
  assert.equal(formatear(75), "01:15");
  assert.equal(formatear(0), "00:00");
});

test("formatea más de una hora en minutos", () => {
  assert.equal(formatear(3725), "62:05");
});

test("pasa de texto a segundos", () => {
  assert.equal(aSegundos("02:30"), 150);
});
