---
name: sql-seguro
description: Consultas SQL correctas y seguras: parámetros, índices y transacciones
category: Datos
tags: sql base de datos
---

- Siempre consultas parametrizadas (`?`, `%s`, `:nombre`); nunca concatenar texto del usuario.
- Selecciona solo las columnas que necesitas; pagina los listados grandes.
- Mira el plan (`EXPLAIN`) de las consultas nuevas sobre tablas grandes y añade índices si hace falta.
- Varias escrituras que deben ir juntas, en una transacción.
- Cuidado con `NULL` en comparaciones y con zonas horarias en fechas.
- Prueba las consultas con datos vacíos y con duplicados.
