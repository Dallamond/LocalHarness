---
name: depurar-sistematico
description: Encontrar la causa real de un fallo antes de tocar código: reproducir, aislar, explicar y arreglar
category: Programación
tags: bugs errores traza
---

Cuando algo falla, NO cambies código a ciegas. Sigue este orden:

1. **Reproduce**: consigue el fallo con una orden concreta (un test, un script). Si no se reproduce, dilo y para.
2. **Lee el error entero**: tipo, mensaje y la traza hasta la primera línea que sea del proyecto (no de librerías).
3. **Formula una hipótesis** en una frase («falla porque X es None cuando Y»). Escríbela.
4. **Compruébala** con la mínima evidencia: leer el código implicado, un print/log temporal o un test pequeño.
   Si la hipótesis cae, vuelve al paso 3 con lo aprendido. Máximo 3 hipótesis antes de resumir lo que sabes.
5. **Arregla la causa, no el síntoma**: nada de `try/except` que se trague el error ni comprobaciones de None
   puestas «por si acaso» si no entiendes por qué llega None.
6. **Añade un test** que fallaba antes y pasa ahora (si el proyecto tiene tests).
7. **Limpia**: quita prints y logs temporales.

Al terminar explica: causa raíz (1-2 frases), arreglo, y cómo lo has comprobado.
