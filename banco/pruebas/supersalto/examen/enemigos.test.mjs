// Parches 8-9 y 15-17 de mario.md: goomba, marcador, combate, vidas, champi, tamaño, ladrillos, koopa y caparazón.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src } from "./ayuda.mjs";

test("goomba: camina, se da la vuelta, cae y se queda aplastado", async () => {
  const { crearMapa } = await src("mapa");
  const { crearGoomba, actualizarGoomba } = await src("goomba");
  const m = crearMapa(["......", "......", "#....#", "######"]);
  let g = actualizarGoomba(crearGoomba({ x: 32, y: 32 }), m);
  assert.equal(g.x, 31.5);
  assert.equal(g.y, 32);
  g = actualizarGoomba(crearGoomba({ x: 16.2, y: 32 }), m);
  assert.equal(g.x, 16);
  assert.equal(g.vx, 0.5);
  g = crearGoomba({ x: 32, y: 0 });
  for (let i = 0; i < 30; i++) g = actualizarGoomba(g, m);
  assert.equal(g.y, 32);
  const muerto = { ...crearGoomba({ x: 32, y: 32 }), vivo: false };
  const d = actualizarGoomba(muerto, m);
  assert.equal(d.aplastado, 1);
  assert.equal(d.x, 32);
});

test("marcador: textos con ceros y reloj de 60 pasos", async () => {
  const { textoMarcador, crearReloj, ticReloj } = await src("marcador");
  assert.deepEqual(textoMarcador({ puntos: 400, monedas: 3, mundo: "1-1", tiempo: 98, vidas: 3 }),
    { puntos: "000400", monedas: "x03", mundo: "1-1", tiempo: "098", vidas: "x3" });
  let r = crearReloj(400);
  for (let i = 0; i < 59; i++) r = ticReloj(r);
  assert.equal(r.segundos, 400);
  r = ticReloj(r);
  assert.equal(r.segundos, 399);
  r = crearReloj(0);
  for (let i = 0; i < 60; i++) r = ticReloj(r);
  assert.equal(r.segundos, 0);
});

test("combate: pisar da puntos y rebote; de lado se muere", async () => {
  const { resolverChoques } = await src("combate");
  const e = { x: 0, y: 16, ancho: 16, alto: 16, vivo: true };
  let r = resolverChoques({ x: 2, y: 2, ancho: 12, alto: 16, vy: 3 }, [e]);
  assert.equal(r.puntos, 100);
  assert.equal(r.jugador.vy, -5);
  assert.equal(r.enemigos[0].vivo, false);
  assert.equal(r.muere, false);
  r = resolverChoques({ x: 10, y: 16, ancho: 12, alto: 16, vy: 0.5 }, [e]);
  assert.equal(r.muere, true);
  r = resolverChoques({ x: 200, y: 16, ancho: 12, alto: 16, vy: 0 }, [e]);
  assert.equal(r.muere, false);
  assert.equal(r.puntos, 0);
  r = resolverChoques({ x: 10, y: 16, ancho: 12, alto: 16, vy: 0.5 }, [{ ...e, vivo: false }]);
  assert.equal(r.muere, false);
  r = resolverChoques({ x: 2, y: 2, ancho: 12, alto: 16, vy: 3 }, [e, { ...e }]);
  assert.equal(r.puntos, 200);
});

test("vidas: perder vida y caer al vacío", async () => {
  const { perderVida, cayoAlVacio } = await src("vidas");
  assert.deepEqual(perderVida({ vidas: 3, puntos: 500, estado: "jugando" }), { vidas: 2, puntos: 500, estado: "muerto" });
  assert.equal(perderVida({ vidas: 1, puntos: 0, estado: "jugando" }).estado, "fin");
  const m = { alto: 3 };
  assert.equal(cayoAlVacio({ y: 49 }, m), true);
  assert.equal(cayoAlVacio({ y: 40 }, m), false);
});

test("champi: sale encima del bloque y anda a la derecha", async () => {
  const { crearMapa } = await src("mapa");
  const { crearChampi, actualizarChampi } = await src("champi");
  const m = crearMapa(["......", "......", ".....#", "######"]);
  let c = crearChampi(1, 2);
  assert.equal(c.x, 16);
  assert.equal(c.y, 16);
  for (let i = 0; i < 20; i++) c = actualizarChampi(c, m);
  assert.equal(c.y, 32);
  const x0 = c.x;
  c = actualizarChampi(c, m);
  assert.ok(c.x === x0 + 1 || c.vx < 0, "avanza 1 o ya se dio la vuelta en la pared");
  for (let i = 0; i < 80; i++) c = actualizarChampi(c, m);
  assert.ok(c.vx < 0, "se da la vuelta en la pared de la columna 5");
});

test("tamaño: crecer, recibir golpe e invencibilidad", async () => {
  const { crecer, recibirGolpe, bajarInvencible } = await src("tamano");
  const p = { y: 100, alto: 16, grande: false };
  const g = crecer(p);
  assert.equal(g.alto, 32);
  assert.equal(g.y, 84);
  const r = recibirGolpe({ y: 84, alto: 32, grande: true });
  assert.equal(r.muere, false);
  assert.equal(r.jugador.grande, false);
  assert.equal(r.jugador.invencible, 120);
  assert.equal(recibirGolpe({ grande: false, invencible: 0 }).muere, true);
  assert.equal(recibirGolpe({ grande: false, invencible: 50 }).muere, false);
  assert.equal(bajarInvencible({ invencible: 0 }).invencible, 0);
});

test("ladrillos: solo los rompe el grande", async () => {
  const { crearMapa } = await src("mapa");
  const { romperLadrillo, trozosLadrillo } = await src("ladrillo");
  const m = crearMapa(["B#"]);
  const r = romperLadrillo(m, 0, 0, true);
  assert.deepEqual(r.mapa.tiles, [".#"]);
  assert.equal(r.puntos, 50);
  assert.equal(romperLadrillo(m, 0, 0, false).roto, false);
  assert.equal(romperLadrillo(m, 1, 0, true).roto, false);
  const t = trozosLadrillo(2, 3);
  assert.equal(t.length, 4);
  assert.equal(t[0].x, 32);
  assert.equal(t[0].y, 48);
});

test("koopa y caparazón", async () => {
  const { crearMapa } = await src("mapa");
  const { crearKoopa, actualizarKoopa } = await src("koopa");
  const { pisarKoopa, caparazonGolpea } = await src("caparazon");
  const m = crearMapa(["......", "......", "#....#", "######"]);
  const k = crearKoopa({ x: 32, y: 32 });
  assert.equal(k.alto, 24);
  assert.equal(k.y, 24);
  assert.equal(actualizarKoopa(k, m).x, 31.5);
  assert.equal(actualizarKoopa({ ...k, modo: "caparazon", vx: 0 }, m).x, 32);
  const c = pisarKoopa(k, { x: 0 });
  assert.equal(c.koopa.modo, "caparazon");
  assert.equal(c.koopa.alto, 16);
  const l = pisarKoopa(c.koopa, { x: 0 });
  assert.equal(l.koopa.modo, "caparazon_rodando");
  assert.equal(l.koopa.vx, 4);
  assert.equal(l.puntos, 400);
  assert.equal(pisarKoopa(l.koopa, { x: 0 }).koopa.modo, "caparazon");
  const goomba = { x: l.koopa.x, y: l.koopa.y, ancho: 16, alto: 16, vivo: true };
  assert.equal(caparazonGolpea(l.koopa, goomba), true);
  assert.equal(caparazonGolpea(c.koopa, goomba), false);
});
