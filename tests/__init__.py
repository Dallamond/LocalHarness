import os

# Los roles de roles/*.md se convierten en agentes al planificar y al arrancar la API: en las pruebas se apagan
# (cada prueba de roles pasa su propia carpeta) para que no se mezclen con los agentes falsos.
os.environ["LOCALHARNESS_ROLES_DIR"] = ""
