# AGENTS.md

Instrucciones para agentes de IA (Claude Code, opencode y similares) que trabajen en este repositorio. Claude Code las carga a través de `CLAUDE.md`; opencode lee este fichero directamente.

## Idioma

- Responde, comenta y documenta **en castellano**.
- Los mensajes de commit también en castellano.
- Los identificadores de código siguen el estilo existente en cada proyecto.

## Qué es este repositorio

Un monorrepo **público** de pequeños proyectos independientes para el curso DAM 2 (2026-27). Cada carpeta de primer nivel es un proyecto autónomo:

- Tiene su propio `README.md` (instalación, uso, pruebas).
- Puede tener su propio `.gitignore`, que se suma al `.gitignore` raíz.
- Gestiona sus dependencias dentro de su carpeta (por ejemplo, `.venv/` y `requirements.txt` en Python).

Proyectos actuales:

| Carpeta | Qué hace | Cómo probar |
|---|---|---|
| `descarga-aula/` | Exportador de un curso Moodle (`descargar.py`) y generador de copia de estudio limpia (`limpiar.py`). | `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` desde `descarga-aula/` |

## Cómo moverse

1. Lee el `README.md` raíz para ver la lista de proyectos.
2. Entra en la carpeta del proyecto y lee su `README.md` antes de tocar nada.
3. Ejecuta los comandos **desde la carpeta del proyecto**, no desde la raíz.
4. No mezcles cambios de varios proyectos en un mismo commit salvo que sean cambios globales (README raíz, AGENTS.md, `.gitignore` raíz).

El entorno habitual es Windows con PowerShell. En Python se usa un `.venv` por proyecto: `.\.venv\Scripts\python.exe`.

## Añadir un proyecto nuevo

1. Crea una carpeta en la raíz con un nombre corto en minúsculas y con guiones (`mi-proyecto`).
2. Incluye un `README.md` en castellano: qué hace, requisitos, instalación, uso y pruebas.
3. Añade un `.gitignore` propio si genera datos, descargas o salidas que no deban publicarse.
4. Añade una fila a la tabla de proyectos del `README.md` raíz y a la de este fichero.

## Reglas de publicación (repositorio público)

Antes de cada commit, revisa `git status` y `git diff --cached`. **Nunca** se suben:

- Credenciales, contraseñas, tokens, claves API, cookies o estados de sesión (`.env`, `storage_state*.json`, `cookies*`…).
- Datos personales propios o de terceros (nombres de compañeros, correos, notas, capturas con datos).
- Material descargado del aula virtual o de terceros con derechos (apuntes, PDF, prácticas, soluciones del profesorado). En `descarga-aula/` esto son `materiales/` y cualquier `materiales-*/`.
- Entornos virtuales, dependencias instaladas, compilados ni cachés.

Si detectas algo de lo anterior en el código o en un fichero a punto de subirse, **para y avisa al usuario** antes de hacer commit. Si algo sensible ya se ha subido, no basta con borrarlo en un commit nuevo: avisa de que hay que reescribir el historial y rotar la credencial.

Sí puede quedar a la vista: el código, los tests, los `requirements*.txt`, la documentación y las URLs públicas de las plataformas (las páginas del aula requieren iniciar sesión).

## Git

- Rama principal: `master`. Remoto: `git@github.com:obiticadev/dam-2026-27-projects.git`.
- Commits pequeños y descriptivos, con prefijo del proyecto cuando aplique: `descarga-aula: corrige …`.
- No hagas `push`, `push --force` ni reescribas historial sin que el usuario lo pida expresamente.
- No ejecutes las herramientas que acceden a servicios reales (por ejemplo, `descargar.py` contra el aula) sin permiso: requieren login manual del usuario.
