---
name: tdd
description: Desarrollo guiado por tests: rojo, verde, refactor en ciclos cortos
category: Calidad y tests
tags: test driven
---

Para cada comportamiento nuevo:
1. **Rojo**: escribe el test más pequeño que describa el comportamiento y comprueba que FALLA por la razón correcta.
2. **Verde**: escribe el código mínimo para que pase. Nada de adelantar funciones que ningún test pide.
3. **Refactor**: limpia el código y los tests con todo en verde.
Repite con el siguiente caso (borde, error…). Al final, ejecuta la suite completa.
Si un test es difícil de escribir, suele indicar que el diseño está demasiado acoplado: sepáralo.
