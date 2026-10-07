# Instalar LocalHarness en otro PC (p. ej. el del instituto)

Pensado para Windows y PowerShell. Sin GPU, los modelos locales no funcionan, pero todo lo demás sí.

## 1. Programas que hacen falta (una vez)
| Programa | Para qué | Cómo comprobarlo |
|---|---|---|
| Git | bajar el código | `git --version` |
| Python 3.10 o superior | servidor | `py -3 --version` o `python --version` |
| Node.js 20 o superior | compilar la web | `node --version` |
| Claude Code (opcional) | agentes Claude | `claude --version` |

- Sin permisos de administrador: el instalador de Python de python.org se instala «solo para mí» (marca *Add python.exe to PATH*).
  Node.js tiene una versión en .zip (nodejs.org → *Windows Binary (.zip)*): descomprímela y añade la carpeta a la sesión con
  `$env:Path = "C:\ruta\node;" + $env:Path`.
- Claude Code: `npm install -g @anthropic-ai/claude-code` y luego `claude` para iniciar sesión con tu cuenta de Claude.
  **Es tu suscripción en un PC compartido: al terminar, `claude auth logout`.** Si no quieres loguearte allí, no crees agentes
  Claude reales (las pruebas usan una CLI falsa y no la necesitan).

## 2. Bajar el código (una vez)
Todo está en `main` (desde el 07/10/2026 las ramas se unificaron; se trabaja siempre en `main`).
```powershell
cd $HOME\Documents
git clone https://github.com/Dallamond/LocalHarness.git
cd LocalHarness
```
Si ya lo tenías clonado y estabas en otra rama:
```powershell
git checkout -- web/package-lock.json   # si npm lo modificó
git checkout main
git pull origin main
```
PowerShell 5 no acepta `&&`: una orden por línea (o separadas con `;`).

## 3. Preparar (una vez, y tras cada `git pull`)
```powershell
py -3 -m venv .venv                                  # si `py` no existe: python -m venv .venv
.venv\Scripts\python -m pip install -e .[server]
cd web; npm install; npm run build; cd ..
.venv\Scripts\python -m unittest discover -s tests -t .   # 136 pruebas; NUNCA llaman a Claude de verdad
```

## 4. Arrancar
```powershell
.venv\Scripts\python -m localharness sandbox     # opcional: repo de pruebas en tu carpeta de usuario + agentes de ejemplo
.venv\Scripts\python -m localharness serve       # abre http://127.0.0.1:8095
```
La base de datos (`data/`) es de cada PC y no se sube a GitHub: en el instituto empiezas sin agentes ni tareas.

## 5. Problemas típicos
- La web se ve antigua: no hiciste `npm run build` o estás en `main` (`git branch` lo dice). Recarga con Ctrl+F5.
- `pip install -e .` falla con «Multiple top-level packages»: estás en una versión vieja (`git pull`).
- PowerShell bloquea scripts (`Activate.ps1`): no hace falta activar el venv, usa siempre `.venv\Scripts\python ...`.
- Un proxy del instituto corta `npm install` o `pip`: prueba con la red del móvil o pide los puertos al profesor.
- Para el servidor: Ctrl+C en su terminal.
