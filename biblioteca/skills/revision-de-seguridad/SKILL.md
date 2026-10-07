---
name: revision-de-seguridad
description: Repasar un cambio buscando fallos de seguridad típicos (OWASP) antes de darlo por bueno
category: Seguridad
tags: owasp vulnerabilidades
---

Revisa el diff con esta lista y di cuáles aplican:
- **Inyección**: SQL con texto concatenado (usa parámetros), comandos de shell con datos del usuario, `eval`.
- **Rutas**: archivos con nombre del usuario sin normalizar (`../`), subidas sin límite de tamaño ni tipo.
- **Autenticación y permisos**: endpoints nuevos sin comprobar quién llama; IDs que se pueden adivinar.
- **Secretos**: claves, tokens o contraseñas en el código, en logs o en respuestas.
- **XSS**: HTML construido con texto del usuario sin escapar (`v-html`, `innerHTML`, `dangerouslySetInnerHTML`).
- **Deserialización** insegura (`pickle`, `yaml.load` sin SafeLoader) de datos de fuera.
- **Dependencias** nuevas: ¿son conocidas y mantenidas?
- **CORS/CSRF** abiertos de más.
Para cada problema: archivo y línea, riesgo (alto/medio/bajo) y arreglo concreto.
