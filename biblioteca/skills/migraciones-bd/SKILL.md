---
name: migraciones-bd
description: Cambiar el esquema de una base de datos sin perder datos ni romper la versión anterior
category: Datos
tags: esquema alembic
---

- Cada cambio de esquema, en una migración versionada (la herramienta del proyecto: Alembic, Prisma, una tabla
  de versiones propia…), nunca a mano.
- Las migraciones deben poder ejecutarse sobre una base con datos reales: añade columnas con valor por defecto o
  nulas, rellena después, y solo entonces pon restricciones.
- No borres ni renombres columnas en el mismo paso en que dejas de usarlas.
- Prueba la migración sobre una copia con datos y, si existe, la vuelta atrás.
