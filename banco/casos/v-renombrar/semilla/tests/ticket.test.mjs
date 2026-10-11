import { test } from "node:test";
import assert from "node:assert/strict";
import { lineaTicket } from "../src/ticket.js";
import { informe } from "../src/informe.js";

test("línea e informe", () => {
  assert.equal(lineaTicket("pan", 120), "pan: 1,20 €");
  assert.equal(informe([{ nombre: "pan", centimos: 120 }]), "pan: 1,20 €\nTOTAL 1,20 €");
});
