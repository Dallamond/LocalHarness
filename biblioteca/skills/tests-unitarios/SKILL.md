---
name: tests-unitarios
description: Escribir tests útiles: un comportamiento por test, casos borde y nada de depender de la red o del reloj
category: Calidad y tests
tags: pytest unittest jest vitest
---

- Usa el framework y el estilo que ya tenga el proyecto (unittest, pytest, vitest, jest…). Mira un test existente
  y copia su estructura.
- Un comportamiento por test, con nombre que lo diga (`test_rechaza_email_sin_arroba`).
- Patrón preparar → actuar → comprobar. Comprueba el resultado, no detalles internos.
- Cubre: caso normal, vacío, límite (0, 1, máximo), entrada inválida y el error esperado.
- Nada de red, reloj real ni orden aleatorio: usa dobles (fakes/mocks) y fija semillas y fechas.
- Archivos temporales en carpetas temporales que se borren solas.
- Ejecuta la suite completa antes de terminar y di cuántos tests pasan.
