---
name: rendimiento
description: Mejorar el rendimiento midiendo primero: perfilar, atacar el cuello de botella y comparar
category: Programación
tags: velocidad optimizar perfilar
---

1. **Mide antes de tocar**: tiempo, memoria o consultas, con una orden reproducible. Sin medida no hay mejora.
2. **Perfila** para encontrar dónde se va el tiempo (cProfile, `--inspect`, el profiler del navegador, EXPLAIN en SQL).
3. Ataca lo más gordo primero. Lo típico: consultas N+1, bucles que repiten trabajo, leer archivos enteros,
   falta de índices, serializar de más, renders innecesarios.
4. Un cambio cada vez y vuelve a medir. Si no mejora, deshazlo.
5. No sacrifiques legibilidad por microoptimizaciones que no se notan.

Informa con números: antes → después y cómo se midió.
