---
name: api-rest
description: Diseñar y cambiar endpoints REST coherentes: rutas, códigos de estado, validación y compatibilidad
category: Programación
tags: endpoints http backend
---

- Rutas con sustantivos en plural (`/api/tareas/{id}`), verbos HTTP con su significado (GET no cambia nada).
- Códigos: 200 OK, 201 creado, 204 sin contenido, 400/422 entrada mala, 404 no existe, 409 conflicto de estado,
  401/403 permisos, 500 solo para fallos inesperados.
- Valida el cuerpo con el sistema del framework (Pydantic, zod, DTOs) y devuelve errores con un mensaje legible.
- Mantén la forma de las respuestas existentes; si cambias un campo, piensa en los clientes que ya lo leen.
- Nada de secretos ni rutas internas en las respuestas.
- Cada endpoint nuevo, con al menos un test del caso bueno y uno de error.
- Si hay documentación de la API (OpenAPI, README), actualízala en el mismo cambio.
