import { test } from "node:test";
import assert from "node:assert/strict";
import { hex, rgb, aclarar } from "../src/color.js";

test("hex y rgb", () => {
  assert.equal(hex(255, 0, 128), "#ff0080");
  assert.deepEqual(rgb("#ff0080"), [255, 0, 128]);
});

test("aclarar", () => {
  assert.equal(aclarar("#000000", 50), "#808080");
  assert.equal(aclarar("#ffffff", 30), "#ffffff");
});
