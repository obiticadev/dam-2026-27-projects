# dam-2026-27-projects

Colección de pequeños proyectos y utilidades de interés para el curso **DAM 2 (2026-27)**. Cada proyecto vive en su propia carpeta, es independiente y tiene su propio `README.md` con instrucciones de instalación y uso.

## Proyectos

| Proyecto | Descripción | Tecnología |
|---|---|---|
| [`descarga-aula/`](descarga-aula/) | Exporta a local los recursos de un curso Moodle (EducaMadrid) visibles para tu cuenta y genera una copia de estudio depurada en Markdown. | Python, Playwright |

## Estructura

```
dam-2026-27-projects/
├── README.md        ← este índice
├── AGENTS.md        ← normas para agentes de IA (Claude Code, opencode…)
├── CLAUDE.md        ← redirige a AGENTS.md
├── .gitignore       ← reglas comunes a todos los proyectos
└── <proyecto>/
    ├── README.md
    └── .gitignore   ← reglas propias (opcional)
```

## Repositorio público

Este repositorio es **público**. No se suben credenciales, cookies, ficheros `.env`, entornos virtuales ni material descargado del aula virtual (apuntes, PDF, prácticas del profesorado). Cada proyecto ignora sus datos generados en su propio `.gitignore`.

## Licencia

[MIT](LICENSE) para el código de este repositorio. No cubre los materiales de terceros que las herramientas puedan descargar en local.
