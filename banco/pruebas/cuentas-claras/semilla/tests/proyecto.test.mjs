import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

test("el proyecto tiene encargo y changelog", () => {
  assert.ok(existsSync("ENCARGO.md"));
  assert.ok(existsSync("CHANGELOG.md"));
});

test("cada línea del CHANGELOG lleva número, fecha y descripción", () => {
  const lineas = readFileSync("CHANGELOG.md", "utf8").split("\n").filter((l) => l.startsWith("- Parche"));
  for (const l of lineas) {
    assert.match(l, /^- Parche \d{3} · \d{2}\/\d{2}\/\d{4} · .+/, l);
  }
});
