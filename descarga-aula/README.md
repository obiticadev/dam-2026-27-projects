# descarga-aula

Exportador local para cursos Moodle de EducaMadrid (por defecto, el curso 929 de Desarrollo de interfaces) y generador de una copia de estudio depurada. **Solo descarga lo que tu cuenta puede ver**. Requiere iniciar sesión manualmente y revisar el registro de recursos omitidos tras cada exportación.

Consta de dos programas:

- `descargar.py`: descarga los recursos del curso a `materiales/`.
- `limpiar.py`: genera, sin conexión, una copia limpia en `materiales-limpios/` a partir de `materiales/`.

> El material descargado (`materiales/`, `materiales-*/`) **no se sube al repositorio**: es contenido del profesorado y contiene URLs y datos internos del aula. Está excluido en `.gitignore`.

## Instalación (PowerShell, Windows)

Desde esta carpeta:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Para usar también `limpiar.py`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-limpieza.txt
```

## Descarga del curso

Primero es recomendable probar tres recursos:

```powershell
.\.venv\Scripts\python.exe descargar.py --limite 3 --salida materiales-prueba
```

Después, para el curso completo:

```powershell
.\.venv\Scripts\python.exe descargar.py
```

Se abre un navegador nuevo. Inicia sesión **en ese navegador**, verifica que ves el curso y pulsa Intro en la terminal. No basta con tener la sesión abierta en tu Chrome habitual. La sesión se mantiene solo durante esa ejecución: no se exportan cookies, contraseñas ni perfiles a disco. No compartas credenciales en el chat.

El resultado queda en `materiales/`, con un `index.html`, un `INDICE.md` y un `registro.json`. Cada tema contiene carpetas con el identificador y el título de las actividades. No se borran archivos existentes; una segunda ejecución vuelve a descargar y puede sobrescribir los archivos generados con el mismo nombre. No edites los originales descargados: trabaja sobre copias.

Otra ubicación: `--salida "C:\ruta\apuntes"`. Otro curso: `--curso "https://.../course/view.php?id=..."`. Pausa entre peticiones: `--pausa 1`.

### Qué descarga

- Archivos originales: PDF, ZIP, documentos, código, etc.
- Recursos HTML: copia local inerte, dependencias locales accesibles y versión Markdown.
- Páginas Moodle y libros: contenido HTML/Markdown y capítulos enlazados en el índice del libro.
- Carpetas: archivos enlazados y visibles en su página.
- Secciones del curso: descubre las actividades en la página inicial y los enlaces a secciones presentes en ella.
- Enlaces: guarda la página del recurso y registra destinos externos; **no rastrea webs externas**.

Las descargas HTML referenciadas desde la página de una actividad se guardan como `recurso-….html`; no solo se guarda la página contenedora de Moodle.

### Límites importantes

- No envía formularios, tareas, respuestas de cuestionarios ni mensajes. Acceder a un recurso puede marcarlo como visto en Moodle, igual que abrirlo manualmente.
- Foros, tareas, cuestionarios, SCORM, H5P y otros tipos no compatibles quedan registrados como omitidos. Los adjuntos dentro de esas actividades tampoco se recorren.
- No se garantiza una réplica visual exacta: se eliminan scripts y formularios; interactividad, contenido generado con JavaScript, vídeos, recursos externos, CSS con `@import` y algunas imágenes adaptativas pueden requerir conexión o revisión manual. Los marcos se sustituyen por enlaces.
- Las versiones HTML de una actividad y sus archivos se enlazan desde el índice general. No se convierten todos los enlaces internos entre páginas en enlaces locales.
- Solo sigue descargas y redirecciones del mismo origen del aula. SSO externo requiere acceso manual en el navegador. No intenta eludir permisos, restricciones ni DRM.
- No hay garantía de descubrir secciones ocultas tras controles JavaScript que no dejen enlaces en el documento. Revisa el listado y los avisos frente al curso antes de dar la copia por completa.
- Se hacen peticiones secuenciales con 0,5 segundos de pausa. Hay un límite de 300 páginas/archivos por actividad.
- El navegador y sus peticiones de red cargan normalmente la página de acceso. El programa no exporta la sesión, pero los archivos descargados y `registro.json` sí pueden contener información privada: guárdalos de forma segura y respeta las condiciones del aula y los derechos del material.

## Copia de estudio depurada

`limpiar.py` genera una carpeta independiente `materiales-limpios/`, sin modificar ni borrar nada en `materiales/`. El punto de entrada es `materiales-limpios/INDICE.md`.

- Regenera los Markdown desde los HTML reales y conserva las dos páginas Moodle con apuntes propios.
- Omite contenedores redundantes y reúne las referencias externas en `Recursos/Enlaces útiles.md`.
- Captura las representaciones HTML/CSS con Chromium como PNG locales. Cada imagen incluye su transcripción textual desplegable.
- Conserva y renombra PDF (incluidos RA1a–RA1g), ZIP e instalador; no ejecuta adjuntos.
- Verifica código, texto, tablas, anclas, enlaces, capturas y huellas de los originales. Los resultados y límites quedan en `INFORME.md` y `MANIFIESTO.json`.
- No usa conexión a Internet durante la limpieza. Las interacciones que ya perdieron sus scripts en la descarga no se reconstruyen ni se presentan como recuperadas.

Para repetir el proceso en **otra carpeta nueva**:

```powershell
.\.venv\Scripts\python.exe limpiar.py --salida materiales-limpios-nueva-copia
```

Opciones: `--origen` (por defecto `materiales/`) y `--salida` (por defecto `materiales-limpios/`). Se requiere Chromium instalado con Playwright. El programa rechaza carpetas de salida existentes para no sobrescribir ediciones propias. Los nombres RA y las descripciones de estos documentos se revisaron para esta exportación; otro curso necesitará adaptar las reglas.

## Pruebas locales (sin acceso al aula)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
