"""Exportador local de recursos Moodle. No recoge contraseñas ni exporta cookies."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
from markdownify import markdownify


DEFAULT_COURSE = "https://aulavirtual3.educa.madrid.org/ies.alonsodeavellan.alcala/course/view.php?id=929"
SUPPORTED = {"resource", "page", "book", "folder", "url"}


def safe_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    # Recortar antes de limpiar los extremos: Windows elimina espacios y puntos
    # finales al crear carpetas y la ruta guardada dejaría de existir.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)[:90].strip(" .")
    if not value:
        return "sin-titulo"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


def clean_url(url: str) -> str:
    return urldefrag(url)[0]


def origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def module(url: str) -> str | None:
    match = re.search(r"/mod/([^/]+)/view\.php$", urlsplit(url).path)
    return match.group(1) if match else None


def activity_key(url: str) -> tuple[str | None, str | None]:
    return module(url), parse_qs(urlsplit(url).query).get("id", [None])[0]


def discover(soup: BeautifulSoup, base: str) -> list[dict]:
    found = {}
    for anchor in soup.select('a[href]'):
        url = clean_url(urljoin(base, anchor["href"]))
        kind, identifier = activity_key(url)
        if origin(url) != origin(base) or not kind or not identifier:
            continue
        # Ignore navigation blocks and links embedded in instructional text.
        activity = anchor.find_parent(class_=lambda c: c and "activity" in c.split())
        if activity is None:
            continue
        section = activity.find_parent(["li", "section"], class_=lambda c: c and "section" in c.split())
        heading = section.select_one('.sectionname, h3, h2') if section else None
        title_node = activity.select_one('.instancename, .activityname')
        title = (title_node or anchor).get_text(" ", strip=True) or f"{kind}-{identifier}"
        found.setdefault((kind, identifier), {
            "title": title, "section": heading.get_text(" ", strip=True) if heading else "General",
            "url": url, "type": kind,
        })
    return list(found.values())


class Exporter:
    def __init__(self, context, course: str, output: Path, delay: float = 0.5):
        self.context = context
        self.course = course
        self.output = output
        self.delay = delay
        self.cache = {}
        self.count = 0
        self.output.mkdir(parents=True, exist_ok=True)

    def fetch(self, url: str):
        """Follow redirects manually: never send authenticated requests off-site."""
        for _ in range(10):
            if origin(url) != origin(self.course):
                raise ValueError(f"Enlace externo (no descargado): {url}")
            if "/login/" in urlsplit(url).path:
                raise RuntimeError("La sesión ha caducado o el recurso requiere otro acceso")
            time.sleep(self.delay)
            response = self.context.request.get(url, max_redirects=0, timeout=60000)
            status, headers = response.status, response.headers
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                response.dispose()
                if not location:
                    raise RuntimeError("Redirección sin destino")
                url = urljoin(url, location)
                continue
            if not response.ok:
                response.dispose()
                raise RuntimeError(f"HTTP {status}: {url}")
            body = response.body()
            response.dispose()
            # Los archivos subidos (pluginfile.php) son material del profesorado y pueden
            # contener ejemplos de login; si la sesión caduca, Moodle redirige a /login/.
            if "text/html" in headers.get("content-type", "") and "/pluginfile.php/" not in urlsplit(url).path:
                check = BeautifulSoup(body, "html.parser")
                if check.select_one('input[name="password"], input[name="logintoken"], form#login'):
                    raise RuntimeError("Se ha recibido la página de acceso; inicia sesión de nuevo")
            return url, headers, body
        raise RuntimeError("Demasiadas redirecciones")

    def asset(self, url: str, folder: Path, warnings: list[str], depth=0) -> Path | None:
        url = clean_url(url)
        key = (str(folder), url)
        if key in self.cache:
            return self.cache[key]
        if origin(url) != origin(self.course) or depth > 5:
            warnings.append(f"Dependencia no descargada: {url}")
            return None
        try:
            final, headers, body = self.fetch(url)
            if "text/html" in headers.get("content-type", ""):
                warnings.append(f"Dependencia HTML no incrustada: {url}")
                return None
            name = safe_name(unquote(Path(urlsplit(final).path).name))
            digest = hashlib.sha256(url.encode()).hexdigest()[:12]
            if "text/css" in headers.get("content-type", "") and not name.endswith(".css"):
                name += ".css"
            target = folder / "assets" / f"{digest}-{name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            self.cache[key] = target
            if "text/css" in headers.get("content-type", ""):
                css = body.decode("utf-8", errors="replace")

                def replace(match):
                    address = match.group(2).strip()
                    if address.startswith(("data:", "#")):
                        return match.group(0)
                    saved = self.asset(urljoin(final, address), folder, warnings, depth + 1)
                    return f'url("{saved.name}")' if saved else match.group(0)

                css = re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', replace, css)
                body = css.encode("utf-8")
            target.write_bytes(body)
            return target
        except Exception as exc:
            self.cache.pop(key, None)
            warnings.append(f"No se pudo guardar {url}: {exc}")
            return None

    def save_html(self, body: bytes, base: str, folder: Path, stem: str, warnings: list[str], moodle=False):
        soup = BeautifulSoup(body, "html.parser")
        if moodle:
            content = soup.select_one('.book_content, .resourcecontent, [role="main"], #region-main')
            if content:
                wrapper = BeautifulSoup('<html><head><meta charset="utf-8"></head><body></body></html>', "html.parser")
                wrapper.body.append(content.extract())
                soup = wrapper
        base_tag = soup.find("base", href=True)
        base = urljoin(base, base_tag["href"]) if base_tag else base
        # Offline exports are inert: do not run copied scripts or submit forms.
        for tag in soup.select('script, base, form, meta[http-equiv="refresh"]'):
            tag.decompose()
        for tag in soup.find_all(True):
            for attr in list(tag.attrs):
                if attr.lower().startswith("on") or attr == "srcdoc":
                    del tag[attr]
            for attr in ("href", "src", "action", "data"):
                if str(tag.get(attr, "")).strip().lower().startswith("javascript:"):
                    del tag[attr]
        for tag in soup.select('img[src], link[rel="stylesheet"][href], source[src], video[poster], audio[src]'):
            attr = "href" if tag.name == "link" else "poster" if tag.name == "video" else "src"
            address = tag[attr]
            if address.startswith("data:"):
                continue
            absolute = urljoin(base, address)
            saved = self.asset(absolute, folder, warnings)
            tag[attr] = saved.relative_to(folder).as_posix() if saved else absolute
            tag.attrs.pop("srcset", None)
            tag.attrs.pop("integrity", None)
            tag.attrs.pop("crossorigin", None)
        def replace_inline(match):
            address = match.group(2).strip()
            if address.startswith(("data:", "#")):
                return match.group(0)
            absolute = urljoin(base, address)
            saved = self.asset(absolute, folder, warnings)
            return f'url("{saved.relative_to(folder).as_posix() if saved else absolute}")'

        for tag in soup.select('[style]'):
            tag['style'] = re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', replace_inline, tag['style'])
        for tag in soup.select('style'):
            tag.string = re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', replace_inline, tag.get_text())
        for tag in soup.select('a[href], iframe[src], embed[src], object[data]'):
            attr = "href" if tag.name == "a" else "data" if tag.name == "object" else "src"
            if not tag[attr].startswith("#"):
                tag[attr] = urljoin(base, tag[attr])
        for tag in soup.select('iframe, embed, object'):
            attr = "data" if tag.name == "object" else "src"
            address = tag.get(attr)
            link = soup.new_tag('a', href=address or base)
            link.string = "Abrir contenido incrustado (requiere conexión)"
            tag.replace_with(link)
        (folder / f"{stem}.html").write_text(str(soup), encoding="utf-8")
        for tag in soup.select('style, link, head'):
            tag.decompose()
        text = markdownify(str(soup), heading_style="ATX")
        (folder / f"{stem}.md").write_text(f"Fuente: {base}\n\n{text}", encoding="utf-8")
        return f"{stem}.html"

    def export(self, item: dict):
        identifier = activity_key(item['url'])[1]
        folder = self.output / safe_name(item['section']) / f"{identifier}-{safe_name(item['title'])}"
        folder.mkdir(parents=True, exist_ok=True)
        warnings = item['warnings'] = []
        queue = [(item['url'], 'contenido')]
        seen = set()
        files = item['files'] = []
        while queue:
            url, stem = queue.pop(0)
            if clean_url(url) in seen:
                continue
            seen.add(clean_url(url))
            if len(seen) > 300:
                warnings.append("Límite de 300 páginas/archivos por actividad alcanzado")
                break
            try:
                final, headers, body = self.fetch(url)
                is_html = "html" in headers.get('content-type', '').lower() or body.lstrip().lower().startswith((b'<!doctype html', b'<html'))
                if not is_html:
                    name = safe_name(unquote(Path(urlsplit(final).path).name))
                    disposition = headers.get('content-disposition', '')
                    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"|filename=([^;]+)", disposition, re.I)
                    if match:
                        name = safe_name(unquote(next(g for g in match.groups() if g)))
                    target = folder / f"{hashlib.sha256(final.encode()).hexdigest()[:10]}-{name}"
                    target.write_bytes(body)
                    files.append(target.relative_to(self.output).as_posix())
                    continue
                soup = BeautifulSoup(body, 'html.parser')
                is_moodle = '/mod/' in urlsplit(final).path
                local = self.save_html(body, final, folder, stem, warnings, moodle=is_moodle)
                files.append((folder / local).relative_to(self.output).as_posix())
                if not is_moodle:
                    continue
                content = soup.select_one('[role="main"], #region-main') or soup
                candidates = content.select('a[href], iframe[src], embed[src], object[data]')
                if item['type'] == 'book':
                    candidates += soup.select('.book_toc a[href], .block_book_toc a[href]')
                for tag in candidates:
                    address = tag.get('href') or tag.get('src') or tag.get('data')
                    target = clean_url(urljoin(final, address))
                    path = urlsplit(target).path
                    if origin(target) != origin(self.course):
                        if tag.name != 'a' or item['type'] == 'url':
                            warnings.append(f"Enlace externo conservado: {target}")
                        continue
                    chapter = item['type'] == 'book' and activity_key(target) == activity_key(item['url']) and 'chapterid' in parse_qs(urlsplit(target).query)
                    attached = '/pluginfile.php/' in path and '/mod_' in path
                    if (chapter or attached) and target not in seen:
                        digest = hashlib.sha256(target.encode()).hexdigest()[:10]
                        queue.append((target, f"capitulo-{digest}" if chapter else f"recurso-{digest}"))
            except Exception as exc:
                warnings.append(f"{url}: {exc}")
        item['status'] = 'guardado' if files else 'error'
        if warnings and files:
            item['status'] = 'guardado con avisos'

    def index(self, items: list[dict]):
        (self.output / 'registro.json').write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = ['# Desarrollo de interfaces', '', f'Curso: {self.course}', '', 'Los avisos y enlaces externos figuran en `registro.json`.', '']
        for item in items:
            lines.append(f"## {item['section']} — {item['title']}")
            lines.append(f"Estado: {item['status']} · [Original]({item['url']})")
            for file in item.get('files', []):
                lines.append(f"- [{Path(file).name}](<{file}>)")
            for warning in item.get('warnings', []):
                lines.append(f"- Aviso: {warning}")
            lines.append('')
        (self.output / 'INDICE.md').write_text('\n'.join(lines), encoding='utf-8')
        entries = []
        for item in items:
            links = ' '.join(f'<a href="{html.escape(file, quote=True)}">{html.escape(Path(file).name)}</a>' for file in item.get('files', []))
            entries.append(f"<li><strong>{html.escape(item['section'])} — {html.escape(item['title'])}</strong><br>{html.escape(item['status'])}<br>{links}</li>")
        (self.output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Desarrollo de interfaces</title><h1>Materiales del curso</h1><p>Consulta registro.json para ver avisos y recursos omitidos.</p><ul>' + '\n'.join(entries) + '</ul>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--curso', default=DEFAULT_COURSE)
    parser.add_argument('--salida', type=Path, default=Path(__file__).parent / 'materiales')
    parser.add_argument('--limite', type=int, help='Prueba con los primeros N recursos compatibles')
    parser.add_argument('--pausa', type=float, default=0.5)
    args = parser.parse_args()
    if origin(args.curso)[0] != 'https' or not parse_qs(urlsplit(args.curso).query).get('id'):
        parser.error('Usa la dirección HTTPS del curso con su parámetro id')
    if args.pausa < 0 or (args.limite is not None and args.limite < 1):
        parser.error('--pausa debe ser >= 0 y --limite debe ser >= 1')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=False)
        try:
            page = context.new_page()
            page.goto(args.curso, wait_until='domcontentloaded')
            print('\nInicia sesión en el navegador y comprueba que ves el curso completo.')
            input('Después pulsa INTRO aquí para comenzar (Ctrl+C para cancelar): ')
            exporter = Exporter(context, args.curso, args.salida, args.pausa)
            # Read through the authenticated request context, without navigating
            # the browser again: Moodle/SSO may still be redirecting that tab.
            # This also avoids waiting for networkidle on a live Moodle page.
            while True:
                try:
                    course_url, _, course_body = exporter.fetch(args.curso)
                    break
                except RuntimeError as exc:
                    if 'sesión' not in str(exc) and 'página de acceso' not in str(exc):
                        raise
                    print(f'Acceso todavía no disponible: {exc}')
                    input('Termina de iniciar sesión, espera a ver el curso y pulsa INTRO para reintentar: ')
            soup = BeautifulSoup(course_body, 'html.parser')
            items = {activity_key(item['url']): item for item in discover(soup, course_url)}
            course_id = parse_qs(urlsplit(args.curso).query)['id'][0]
            sections = set()
            for anchor in soup.select('a[href]'):
                url = clean_url(urljoin(args.curso, anchor['href']))
                parts = urlsplit(url)
                query = parse_qs(parts.query)
                if origin(url) != origin(args.curso):
                    continue
                if (parts.path.endswith('/course/view.php') and query.get('id') == [course_id] and 'section' in query) or parts.path.endswith('/course/section.php'):
                    # Section IDs are taken only from this course's own page.
                    sections.add(url)
            for section_url in sorted(sections):
                try:
                    final, _, body = exporter.fetch(section_url)
                    for item in discover(BeautifulSoup(body, 'html.parser'), final):
                        items.setdefault(activity_key(item['url']), item)
                except Exception as exc:
                    print(f'AVISO: No se pudo leer la sección {section_url}: {exc}')
                    items[('section', section_url)] = {'title': 'Sección no leída', 'section': 'Avisos', 'url': section_url, 'type': 'section', 'status': 'omitido', 'warnings': [str(exc)]}
            records = list(items.values())
            if not records:
                raise RuntimeError('No se han encontrado actividades. Comprueba la sesión y que el curso contiene recursos visibles.')
            for item in records:
                item.setdefault('status', 'pendiente')
            print(f'Detectados {len(records)} recursos/actividades.')
            exported = 0
            for item in records:
                if item['type'] not in SUPPORTED:
                    item['status'] = 'omitido'
                    item.setdefault('warnings', ['Actividad no descargada: no se envían formularios ni se recorren tareas, foros o cuestionarios.'])
                elif args.limite is not None and exported >= args.limite:
                    item.update(status='pendiente (límite de prueba)', warnings=[])
                else:
                    print(f"Descargando: {item['section']} / {item['title']}")
                    exporter.export(item)
                    exported += 1
                exporter.index(records)
            print(f'\nTerminado. Abre: {args.salida.resolve() / "index.html"}')
            print('Revisa registro.json: puede haber recursos omitidos o dependencias que requieran conexión.')
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelado. Los archivos ya guardados se conservan.')
