// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

const tab = (s) => [...s].map((c) => (c === "." ? null : c));

test("crear y jugar", async () => {
  const { crearTablero, jugar } = await src("src/tablero.js");
  const t = Object.freeze(crearTablero());
  assert.deepEqual(t, Array(9).fill(null));
  assert.deepEqual(jugar(t, 4, "X"), tab("....X...."));
  assert.throws(() => jugar(tab("X........"), 0, "O"), /casilla ocupada/);
});

test("ganador, empate o sigue", async () => {
  const { ganador } = await src("src/tablero.js");
  assert.equal(ganador(tab("XXX.OO...")), "X");
  assert.equal(ganador(tab("O.XO.XO..")), "O");
  assert.equal(ganador(tab("X.O.XO..X")), "X");
  assert.equal(ganador(tab("XOXXOOOXX")), "empate");
  assert.equal(ganador(tab("XO.......")), null);
});

test("la máquina gana si puede y si no bloquea", async () => {
  const { jugadaIA } = await src("src/tablero.js");
  assert.equal(jugadaIA(tab("OO.XX...."), "O"), 2);
  assert.equal(jugadaIA(tab("XX..O...."), "O"), 2);
  assert.equal(jugadaIA(tab("XO..O...."), "X"), 7);
});

test("si no, centro, esquina y la primera libre", async () => {
  const { jugadaIA } = await src("src/tablero.js");
  assert.equal(jugadaIA(tab("X........"), "O"), 4);
  assert.equal(jugadaIA(tab("....X...."), "O"), 0);
  assert.equal(jugadaIA(tab("O...X...."), "O"), 2);
  assert.equal(jugadaIA(tab("X.O.X...O"), "O"), 5); // gana en la columna 2-5-8
});

test("index.html y main.js montan el juego", () => {
  const html = leer("index.html");
  for (const id of ["tablero", "estado", "otra"]) assert.match(html, new RegExp(`id=["']${id}["']`), id);
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?src\/main\.js["']/);
  assert.match(leer("src/main.js"), /from\s+["']\.\/tablero\.js["']/);
});
