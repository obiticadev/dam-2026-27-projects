"""Depura una exportación Moodle en una carpeta nueva, sin conexión ni cambios en el origen."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import MarkdownConverter

from descargar import safe_name


ROOT = Path(__file__).resolve().parent
VISUAL_SELECTORS = (
    '.visual, .flow-diagram, .flujo-binding, .file-tree, .firma-anotada, '
    '.layouts-visual, .shape-grid, .diagram-container, .compare-radio-check, '
    '.cell-types, .before-after, .leyenda, .legend, .platform-cards, .lab, .form-cards'
)
SECTION_NAMES = {
    '1.- Confección de interfaces de usuario': '1. Confección de interfaces de usuario',
    'Recursos. Platforms. Layouts. Estilo global, de página y de control.': 'Recursos, Platforms, layouts y estilos',
}
RA_DESCRIPTIONS = {
    'a': 'Creación del proyecto con asistentes de Visual Studio',
    'b': 'Edición de XAML y ubicación de componentes',
    'c': 'Propiedades de los componentes en XAML',
    'd': 'Análisis del código generado en MAUI',
    'e': 'Modificación del código y personalización de la aplicación',
    'f': 'Eventos y controladores de acciones',
    'g': 'Compilación, ejecución y depuración de la aplicación',
}
PDF_NAMES = {
    'Introducción a Desarrollo de Interfaces.pdf': 'Introducción a Desarrollo de Interfaces - Curso 2026-2027.pdf',
    'Instalar Visual Studio y elegir las características preferidas _ Microsoft Learn.pdf': 'Visual Studio - Instalación y selección de características.pdf',
    'basico POOC.pdf': 'POO en C# - Conceptos básicos y diseño de clases.pdf',
    'Introducción a C#.PDF': 'Introducción a C# - Manual del estudiante.pdf',
    'C-sharp-Java.pdf': 'C# vs Java - Comparativa de lenguajes.pdf',
    'Diferencias entre Java y C#.pdf': 'Java y C# - Diferencias básicas de sintaxis.pdf',
    'Tema 1 Maui.pdf': 'TEMA 1 - Introducción a .NET MAUI y entorno de desarrollo.pdf',
}
RESOURCE_INFO = {
    '101491': ('Documentación', 'Microsoft Learn', 'Itinerarios y módulos de aprendizaje para .NET y sus herramientas.'),
    '101492': ('Documentación', 'API de .NET', 'Consulta de tipos, métodos y espacios de nombres. El enlace del aula apunta a .NET Framework 4.8; comprueba la versión antes de aplicarlo a MAUI.'),
    '101493': ('Iconos y gráficos', 'Flaticon', 'Búsqueda de iconos para interfaces. Revisa la licencia y los requisitos de atribución.'),
    '101494': ('Iconos y gráficos', 'Iconfactory', 'Colecciones de iconos y recursos gráficos; comprueba sus condiciones de uso.'),
    '101495': ('Iconos y gráficos', 'Freeicons', 'Catálogo de iconos para prototipos e interfaces; comprueba la licencia de cada recurso.'),
    '101496': ('Vídeos', 'Evolución de los lenguajes de programación', 'Vídeo de contexto sobre la evolución de los lenguajes.'),
    '207832': ('Vídeos', 'Vídeos explicativos de Visual Studio', 'Vídeo y lista de reproducción de apoyo para el uso del entorno de desarrollo.'),
    '207838': ('Ejercicios', 'Práctica con C# — W3Schools', 'Tutorial y ejercicios de sintaxis de C# para practicar los fundamentos.'),
    '208001': ('Documentación', 'Grid en Microsoft Learn', 'Referencia del layout Grid: filas, columnas, tamaños y colocación de controles en .NET MAUI 9.'),
    '214761': ('Documentación', 'Controles de .NET MAUI 9', 'Catálogo oficial de controles, propiedades y ejemplos para contrastar los apuntes.'),
}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fix_encoding(value: str) -> str:
    # Downloaded Content-Disposition filenames contain UTF-8 interpreted as Latin-1.
    if 'Ã' in value or 'Â' in value:
        try:
            return value.encode('latin-1').decode('utf-8')
        except (UnicodeError, ValueError):
            pass
    return value


def readable_title(value: str) -> str:
    return re.sub(r'\s+(Archivo|URL|Página|Carpeta)$', '', fix_encoding(value)).strip()


def slug(value: str) -> str:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:65] or 'visual'


def relative_link(target: Path, document: Path) -> str:
    path = Path(os.path.relpath(target, document.parent)).as_posix()
    return quote(path, safe='/-._~')


def identifier(record: dict) -> str:
    return parse_qs(urlsplit(record['url']).query).get('id', ['sin-id'])[0]


def normalize_code(value: str) -> str:
    return '\n'.join(line.rstrip() for line in value.replace('\r\n', '\n').strip('\n').splitlines())


def code_language(tag: Tag) -> str:
    explicit = str(tag.get('data-lang', ''))
    classes = ' '.join(tag.get('class', []))
    if not explicit and tag.code:
        classes += ' ' + ' '.join(tag.code.get('class', []))
    match = re.search(r'(?:language-|code-)([\w#+]+)', classes)
    language = explicit or (match.group(1) if match else '')
    if language:
        return {'cs': 'csharp', 'c#': 'csharp', 'xaml': 'xml'}.get(language.lower(), language.lower())
    text = tag.get_text().strip()
    if text.startswith(('<', '&lt;')):
        return 'xml'
    if re.search(r'\b(using|class|namespace|private|public|void|var|await|Task|return|Console)\b', text):
        return 'csharp'
    if re.search(r'(=|;|\{|\})', text) and not text.startswith(('{"', '{\n  "')):
        return 'csharp'
    return 'text'


class StudyConverter(MarkdownConverter):
    def escape(self, text, parent_tags):
        # Generic types and literal XAML must not become raw HTML in Markdown.
        return super().escape(html.escape(text, quote=False), parent_tags)

    def convert_span(self, el, text, parent_tags):
        if 'inline-code' in el.get('class', []) and '_noformat' not in parent_tags:
            return self.convert_code(el, el.get_text(), parent_tags)
        return text

    def convert_td(self, el, text, parent_tags):
        return super().convert_td(el, text.replace('|', r'\|'), parent_tags)

    def convert_th(self, el, text, parent_tags):
        return super().convert_th(el, text.replace('|', r'\|'), parent_tags)

    def convert_pre(self, el, text, parent_tags):
        # Read the DOM directly: no Markdown escaping/highlighting may change code.
        code = el.get_text().strip('\r\n')
        fence = '`' * max(3, 1 + max((len(x) for x in re.findall(r'`+', code)), default=0))
        return f'\n\n{fence}{code_language(el)}\n{code}\n{fence}\n\n'

    def convert_div(self, el, text, parent_tags):
        image = el.get('data-study-image')
        if image:
            title = el['data-study-title']
            alt = title.replace('[', '(').replace(']', ')').replace('\n', ' ')
            return (f'\n\n![{alt}]({image})\n\n'
                    '<details>\n<summary>Contenido textual de la representación</summary>\n\n'
                    f'{text.strip()}\n\n</details>\n\n')
        return super().convert_div(el, text, parent_tags)

    def convert_details(self, el, text, parent_tags):
        # Solutions remain visible in Markdown even when their HTML was collapsed.
        return '\n\n' + text.strip() + '\n\n'

    def convert_summary(self, el, text, parent_tags):
        return f'\n\n**{text.strip()}**\n\n'

    def convert_button(self, el, text, parent_tags):
        return f'\n\n- {text.strip()}\n\n' if text.strip() else ''

    def convert_input(self, el, text, parent_tags):
        value = el.get('value') or el.get('placeholder')
        return f' `{value}` ' if value else ''

    def convert_dt(self, el, text, parent_tags):
        return f'\n\n**{text.strip()}**\n\n'

    def convert_dd(self, el, text, parent_tags):
        return text.strip() + '\n\n'

    def convert_a(self, el, text, parent_tags):
        anchor = el.get('data-study-anchor')
        if anchor:
            return f'\n\n<a id="{html.escape(anchor, quote=True)}"></a>\n\n'
        return super().convert_a(el, text, parent_tags)


def converter() -> StudyConverter:
    return StudyConverter(heading_style='ATX', bullets='-', escape_underscores=False,
                          escape_asterisks=True, wrap=False)


def load_html(path: Path) -> BeautifulSoup:
    return BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')


def meaningful_body(soup: BeautifulSoup, is_page=False) -> Tag:
    if is_page:
        body = soup.select_one('[role="main"] .no-overflow, [role="main"], #region-main') or soup.body or soup
        body = BeautifulSoup(str(body), 'html.parser')
        for tag in body.select('.modified, .activity-header, .activity-information, .activity-navigation, .notifications, .sr-only'):
            tag.decompose()
        for title in body.find_all(re.compile('^h[1-6]$')):
            if title.get_text(strip=True) == 'Requisitos de finalización':
                title.decompose()
        return body
    return soup.body or soup


def page_code_blocks(body: Tag, soup: BeautifulSoup):
    """The break/switch Moodle page formats actual code as bold/italic paragraphs."""
    for paragraph in list(body.select('p')):
        text = paragraph.get_text('\n').replace('\xa0', ' ').strip()
        # Only whole code paragraphs, never prose mentioning a switch.
        if paragraph.find(['strong', 'em']) and (
            re.match(r'^int numero\s*=\s*\d+;', text) or re.match(r'^switch\s*\(', text.replace('\n', ''))
        ):
            # Inline Moodle autolinks split 'switch' and its opening parenthesis.
            for link in paragraph.select('a'):
                link.unwrap()
            text = paragraph.get_text().replace('\xa0', ' ')
            for br in paragraph.select('br'):
                br.replace_with('\n')
            text = paragraph.get_text().replace('\xa0', ' ').strip()
            pre = soup.new_tag('pre', **{'data-lang': 'csharp'})
            code = soup.new_tag('code')
            code.string = text
            pre.append(code)
            paragraph.replace_with(pre)


class Cleaner:
    def __init__(self, source: Path, output: Path):
        self.source = source.resolve()
        self.output = output.resolve()
        self.records = json.loads((self.source / 'registro.json').read_text(encoding='utf-8'))
        self.entries = []
        self.changes = []
        self.warnings = []
        self.pdfs = []
        self.documents = []
        self.links = []
        self.source_to_target = {}
        self.activity_targets = {}
        self.url_targets = {}
        self.snapshots = []
        self.source_hashes = {f.relative_to(self.source).as_posix(): digest(f)
                              for f in self.source.rglob('*') if f.is_file()}

    def section(self, record: dict) -> Path:
        return self.output / safe_name(SECTION_NAMES.get(record['section'], record['section']))

    def add_entry(self, record, source: Path, target: Path | None, action: str, reason=''):
        self.entries.append({
            'original': source.relative_to(self.source).as_posix(),
            'destino': target.relative_to(self.output).as_posix() if target else None,
            'accion': action, 'motivo': reason, 'actividad': record.get('title'),
            'id_moodle': identifier(record) if record.get('url') else None,
        })
        if target:
            self.source_to_target[source.resolve()] = target

    def pdf_name(self, source: Path) -> str:
        name = fix_encoding(re.sub(r'^[0-9a-f]{10}-', '', source.name))
        match = re.search(r'RA1([a-g])', name, re.I)
        if match:
            letter = match.group(1).lower()
            return f'TEMA 1 RA1{letter} - {RA_DESCRIPTIONS[letter]}.pdf'
        return PDF_NAMES.get(name, name[:-4] + '.pdf')

    def unique_target(self, target: Path) -> Path:
        allocated = {p.resolve() for p in self.source_to_target.values()}
        if target.resolve() in allocated:
            raise RuntimeError(f'Nombre de salida duplicado: {target}')
        return target

    def classify(self):
        for record in self.records:
            folder_files = [self.source / f for f in record.get('files', [])]
            for source in list(folder_files):
                if not source.is_file():
                    if source.name == 'contenido.html' and record['type'] != 'page' and any(p.is_file() for p in folder_files if p != source):
                        self.warnings.append(f'El registro menciona un contenedor que ya no está en origen: {source.relative_to(self.source).as_posix()}. Sus archivos reales sí se conservan.')
                        folder_files.remove(source)
                        continue
                    raise FileNotFoundError(f'El registro referencia un archivo inexistente: {source}')
            title = readable_title(record['title'])
            content_target = None
            for source in folder_files:
                if source.suffix.lower() == '.html':
                    if source.name == 'contenido.html' and record['type'] != 'page':
                        continue
                    target = self.unique_target(self.section(record) / (safe_name(title) + '.md'))
                    # There is one actual HTML per activity in this export. Never silently merge others.
                    if content_target:
                        target = self.section(record) / (safe_name(title) + '-' + slug(source.stem) + '.md')
                    self.add_entry(record, source, target, 'convertido a Markdown con gráficos')
                    self.documents.append({'source': source, 'target': target, 'record': record})
                    content_target = content_target or target
                elif source.suffix.lower() == '.pdf':
                    target = self.unique_target(self.section(record) / 'PDF' / self.pdf_name(source))
                    self.add_entry(record, source, target, 'PDF conservado y renombrado')
                    self.pdfs.append({'source': source, 'target': target, 'record': record})
                    content_target = content_target or target
                else:
                    name = fix_encoding(re.sub(r'^[0-9a-f]{10}-', '', source.name))
                    if source.suffix.lower() == '.exe':
                        name = 'Visual Studio 2022 - Instalador Community.exe'
                    elif source.suffix.lower() == '.zip':
                        name = 'Calculadora - Solución actividad 1.zip'
                    target = self.unique_target(self.section(record) / 'Archivos' / name)
                    self.add_entry(record, source, target, 'adjunto conservado (no ejecutado)')
                    content_target = content_target or target

            if record['type'] == 'url':
                destinations = []
                for warning in record.get('warnings', []):
                    match = re.search(r'https?://\S+', warning)
                    if match:
                        destinations.append(match.group(0))
                for source in folder_files:
                    if source.suffix.lower() == '.html':
                        soup = load_html(source)
                        main = soup.select_one('[role="main"]') or soup
                        destinations.extend(a['href'] for a in main.select('a[href]') if urlsplit(a['href']).netloc and 'educa.madrid.org' not in urlsplit(a['href']).netloc)
                destinations = list(dict.fromkeys(destinations))
                info = RESOURCE_INFO.get(identifier(record), ('Otros recursos', title, 'Referencia enlazada desde el aula.'))
                self.links.append({'record': record, 'urls': destinations, 'category': info[0], 'title': info[1], 'description': info[2]})
                content_target = self.output / 'Recursos' / 'Enlaces útiles.md'
                if not destinations:
                    self.warnings.append(f'No se ha encontrado el destino externo de {title}')

            for source in folder_files:
                if source.suffix.lower() != '.html' or source in [d['source'] for d in self.documents]:
                    continue
                # Safety check: discard only known wrapper/folder/link text.
                soup = load_html(source)
                main = soup.select_one('[role="main"]') or soup
                text = main.get_text(' ', strip=True)
                is_wrapper = record['type'] in {'url', 'folder'} or text.startswith('Haga clic en') or (main.select_one('a[href]') and len(text) < 150)
                if not is_wrapper:
                    raise RuntimeError(f'Página contenedora con contenido no reconocido: {source}')
                self.add_entry(record, source, content_target, 'contenedor Moodle omitido', 'El recurso real o enlace se conserva por separado')

            if content_target:
                self.activity_targets[identifier(record)] = content_target
                for source in folder_files:
                    if source.suffix.lower() != '.html':
                        continue
                    md = source.with_suffix('.md')
                    if md.is_file():
                        match = re.match(r'Fuente:\s*(https?://\S+)', md.read_text(encoding='utf-8'))
                        if match:
                            self.url_targets[match.group(1)] = self.source_to_target.get(source.resolve(), content_target)
                        self.add_entry(record, md, self.source_to_target.get(source.resolve(), content_target), 'Markdown sustituido por versión depurada')

    def copy_files(self):
        for entry in self.entries:
            if entry['accion'].startswith(('PDF conservado', 'adjunto conservado')):
                source = self.source / entry['original']
                target = self.output / entry['destino']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        import pymupdf
        for item in self.pdfs:
            with pymupdf.open(item['source']) as doc:
                first_pages = '\n'.join(doc[i].get_text() for i in range(min(2, len(doc))))
                item['pages'] = len(doc)
                item['excerpt'] = first_pages[:1200]
                item['links'] = list(dict.fromkeys(link['uri'] for page in doc for link in page.get_links() if link.get('uri', '').startswith('https://learn.microsoft.com/')))
                printed_urls = re.findall(r'https://learn\.microsoft\.com/\S+', first_pages)
                item['source_url'] = next((url for url in printed_urls if urlsplit(url).path.endswith('/install-visual-studio')), None)
                match = re.search(r'RA1([a-g])', item['target'].name)
                if match and f'RA1{match.group(1)}'.lower() not in first_pages.lower():
                    raise RuntimeError(f'El identificador RA del PDF no coincide con su contenido: {item["source"]}')
            if digest(item['source']) != digest(item['target']):
                raise RuntimeError(f'La copia del PDF no coincide con el original: {item["target"]}')

    def rewrite_links(self, body: Tag, source: Path, target: Path):
        for anchor in body.select('a[href]'):
            address = anchor['href']
            if address.startswith('#'):
                continue
            destination = self.url_targets.get(address)
            parts = urlsplit(address)
            if not destination and '/mod/' in parts.path and 'educa.madrid.org' in parts.netloc:
                resource_id = parse_qs(parts.query).get('id', [None])[0]
                destination = self.activity_targets.get(resource_id)
            if not destination and not parts.scheme:
                destination = self.source_to_target.get((source.parent / unquote(parts.path)).resolve())
            if destination:
                anchor['href'] = relative_link(destination, target) + ('#' + parts.fragment if parts.fragment else '')
        for image in body.select('img[src]'):
            parts = urlsplit(image['src'])
            if parts.scheme or image['src'].startswith('data:'):
                self.warnings.append(f'{target.name}: imagen no local {image["src"]}')
                continue
            original = (source.parent / unquote(parts.path)).resolve()
            if not original.is_relative_to(self.source) or not original.is_file():
                self.warnings.append(f'{target.name}: imagen original no disponible {image["src"]}')
                continue
            saved = target.parent / 'assets' / slug(target.stem) / safe_name(original.name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, saved)
            image['src'] = relative_link(saved, target)

    def render_document(self, page, document: dict):
        source, target, record = document['source'], document['target'], document['record']
        soup = load_html(source)
        is_page = record['type'] == 'page'
        body = meaningful_body(soup, is_page)
        if is_page:
            page_code_blocks(body, soup)
        if identifier(record) == '214772' and body.select_one('a[href="#intro"]') and not body.select_one('[id="intro"]'):
            introduction = body.select_one('.nota')
            if introduction:
                introduction['id'] = 'intro'
                self.changes.append('Colecciones en C#: reparada el ancla #intro, que ya faltaba en el HTML original, enlazándola con la introducción existente.')
        for comment in list(body.find_all(string=lambda text: isinstance(text, Comment))):
            comment.extract()
        for tag in body.select('script, style, .toast'):
            tag.decompose()
        selected = body.select(VISUAL_SELECTORS)
        selected_ids = {id(tag) for tag in selected}
        blocks = [tag for tag in selected if not any(id(parent) in selected_ids for parent in tag.parents)]
        # Mark the same nodes in a separate render copy. No original file is edited.
        render_soup = load_html(source)
        render_body = meaningful_body(render_soup, is_page)
        render_blocks = render_body.select(VISUAL_SELECTORS)
        render_ids = {id(tag) for tag in render_blocks}
        render_blocks = [tag for tag in render_blocks if not any(id(parent) in render_ids for parent in tag.parents)]
        if len(render_blocks) != len(blocks):
            raise RuntimeError(f'No coincide la selección de gráficos de {source}')
        target.parent.mkdir(parents=True, exist_ok=True)
        for i, tag in enumerate(render_blocks, 1):
            tag['data-capture-block'] = str(i)
        for tag in render_soup.select('script, iframe, embed, object'):
            tag.decompose()
        for tag in render_soup.find_all(True):
            for attr in list(tag.attrs):
                if attr.startswith('on'):
                    del tag[attr]
        # Render only local bytes; network requests are blocked by the context.
        page.set_content(str(render_soup), wait_until='domcontentloaded')
        page.add_style_tag(content='html{scroll-behavior:auto!important} *{caret-color:transparent!important} details{content-visibility:visible!important}')
        page.evaluate("""() => { document.querySelectorAll('details').forEach(x => x.open = true); }""")
        page.evaluate('document.fonts.ready')
        document['images'] = []
        for i, (tag, render_tag) in enumerate(zip(blocks, render_blocks), 1):
            title_node = tag.select_one('.visual-title, .lab-title')
            previous = tag.find_previous(re.compile('^h[1-6]$'))
            title = (title_node or previous).get_text(' ', strip=True) if (title_node or previous) else 'Representación visual'
            filename = f'{i:02d}-{slug(title)}.png'
            image = target.parent / 'assets' / slug(target.stem) / filename
            image.parent.mkdir(parents=True, exist_ok=True)
            locator = page.locator(f'[data-capture-block="{i}"]')
            box = locator.bounding_box()
            if not box or box['width'] < 2 or box['height'] < 2:
                raise RuntimeError(f'Gráfico oculto o vacío: {source.name}, bloque {i}')
            # Scrollable file trees may be wider than their box. Capture their full content.
            locator.evaluate("el => { if(el.scrollWidth > el.clientWidth + 2) { el.style.maxWidth='none'; el.style.width=el.scrollWidth+'px'; el.style.overflow='visible'; } }")
            locator.screenshot(path=str(image), animations='disabled', timeout=30000)
            tag['data-study-image'] = relative_link(image, target)
            tag['data-study-title'] = title
            document['images'].append({'path': image.relative_to(self.output).as_posix(), 'title': title, 'classes': tag.get('class', []), 'source_block': i})
            self.snapshots.append(document['images'][-1])

        # Text/code is kept even inside image blocks, as an accessible collapsed transcript.
        self.rewrite_links(body, source, target)
        expected_codes = [normalize_code(pre.get_text()) for pre in body.select('pre')]
        # Preserve explicit source fragment IDs: headings generated by Markdown differ.
        for tag in list(body.select('[id]')):
            if tag['id'] in {'maincontent', 'region-main', 'user-notifications'}:
                continue
            anchor = soup.new_tag('a', **{'data-study-anchor': tag['id']})
            tag.insert_before(anchor)
        text = converter().convert(str(body)).strip()
        if not body.find('h1'):
            text = '# ' + readable_title(record['title']) + '\n\n' + text
        original_md = source.with_suffix('.md')
        source_url = record['url']
        if original_md.exists():
            match = re.match(r'Fuente:\s*(https?://\S+)', original_md.read_text(encoding='utf-8'))
            if match:
                source_url = match.group(1)
        note = ''
        if record['type'] == 'page':
            note += '\n> Página de contenido del aula conservada: no era una página contenedora.\n'
        if identifier(record) == '217064':
            note += ('\n> **Límite de la exportación:** el laboratorio de ToolbarItem perdió sus scripts en la descarga original. '
                     'Se conservan su vista estática, instrucciones y código; los botones generados dinámicamente y la interacción no están disponibles.\n')
            self.warnings.append('ToolbarItem: la exportación original no conserva los botones creados por JavaScript ni la interacción. No se han inventado estados ni resultados.')
        if identifier(record) == '214787':
            note += ('\n> Las soluciones desplegables se muestran como texto. El test final conserva las opciones, '
                     'pero la corrección interactiva no está disponible sin los scripts del original.\n')
            self.warnings.append('Práctica guiada de colecciones: soluciones razonadas conservadas; test final sin corrección interactiva porque los scripts ya no estaban en el HTML exportado.')
        footer = f'\n\n---\n\nFuente: [material original]({source_url}) · [actividad del aula]({record["url"]}).\n'
        if note:
            first, separator, rest = text.partition('\n')
            text = first + '\n' + note + '\n' + rest if separator else text + '\n' + note
        target.write_text(text + footer, encoding='utf-8')
        document['expected_codes'] = expected_codes
        document['expected_text'] = body.get_text(' ', strip=True)
        document['source_url'] = source_url
        print(f'{target.relative_to(self.output)}: {len(blocks)} gráficos, {len(expected_codes)} bloques de código', flush=True)

    def write_links(self):
        target = self.output / 'Recursos' / 'Enlaces útiles.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = ['# Enlaces útiles', '', 'Referencias externas del aula, reunidas sin copiar sus páginas contenedoras. Se conservan los destinos proporcionados por el curso.', '']
        for category in ['Documentación', 'Herramientas', 'Iconos y gráficos', 'Ejercicios', 'Vídeos', 'Otros recursos']:
            group = [entry for entry in self.links if entry['category'] == category]
            if not group and category != 'Herramientas':
                continue
            lines += [f'## {category}', '']
            for item in group:
                lines += [f'### {item["title"]}', '', item['description'], '']
                lines += [f'- [Abrir recurso]({url})' for url in item['urls']]
                lines += [f'- Tema original: {item["record"]["section"].rstrip(".")}.', '']
            if category == 'Herramientas':
                install_pdf = next((p for p in self.pdfs if identifier(p['record']) == '205985'), None)
                if install_pdf:
                    url = install_pdf.get('source_url') or next((u for u in install_pdf['links'] if urlsplit(u).path.endswith('/install-visual-studio')), 'https://learn.microsoft.com/es-es/visualstudio/install/install-visual-studio')
                    lines += ['### Instalación de Visual Studio', '', 'Guía de instalación, elección de edición y selección de cargas de trabajo. El aula aporta una impresión PDF de Microsoft Learn; también se conserva esa copia.', '', f'- [Documentación en Microsoft Learn]({url})', f'- [Copia PDF descargada]({relative_link(install_pdf["target"], target)})', '']
        lines += ['## Archivos de apoyo', '', 'Los documentos se mantienen como archivos originales, sin convertirlos a texto:', '']
        for pdf in self.pdfs:
            if pdf['record']['section'] == 'Recursos':
                lines.append(f'- [{pdf["target"].stem}]({relative_link(pdf["target"], target)}) — {pdf["pages"]} páginas.')
        exe = next((self.output / e['destino'] for e in self.entries if e['destino'] and e['destino'].endswith('.exe')), None)
        if exe:
            lines += ['', f'- [Instalador de Visual Studio Community]({relative_link(exe, target)}): copia descargada del aula; se conserva, **no se ha ejecutado**.']
        target.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def write_indexes(self):
        target = self.output / 'INDICE.md'
        lines = ['# Desarrollo de interfaces — Materiales depurados', '', 'Los apuntes están en Markdown. Sus diagramas y vistas son imágenes locales en las carpetas `assets`; no necesitan los HTML originales.', '', '- [Enlaces útiles](Recursos/Enlaces%20%C3%BAtiles.md)', '- [Informe de limpieza](INFORME.md)', '']
        groups = {}
        for document in self.documents:
            groups.setdefault(document['target'].parent.name, []).append(document['target'])
        for entry in self.entries:
            if entry['accion'].startswith(('PDF conservado', 'adjunto conservado')):
                file = self.output / entry['destino']
                groups.setdefault(file.parent.parent.name, []).append(file)
        for section, files in groups.items():
            lines += [f'## {section}', '']
            for file in sorted(set(files), key=lambda f: f.name.casefold()):
                lines.append(f'- [{file.stem}]({relative_link(file, target)})')
            lines.append('')
        target.write_text('\n'.join(lines), encoding='utf-8')

    def validate(self) -> dict:
        from markdown_it import MarkdownIt
        from PIL import Image
        engine = MarkdownIt('commonmark', {'html': True}).enable('table')
        errors = []
        total_codes = 0
        total_tables = 0
        for document in self.documents:
            target = document['target']
            text = target.read_text(encoding='utf-8')
            tokens = engine.parse(text)
            codes = [normalize_code(token.content) for token in tokens if token.type == 'fence']
            expected = Counter(document['expected_codes'])
            missing = expected - Counter(codes)
            if missing:
                errors.append({'file': target.relative_to(self.output).as_posix(), 'error': 'código perdido o alterado', 'count': sum(missing.values()), 'examples': list(missing)[:2]})
            total_codes += len(codes)
            rendered = BeautifulSoup(engine.render(text), 'html.parser')
            original = meaningful_body(load_html(document['source']), document['record']['type'] == 'page')
            original_tables = len(original.select('table'))
            rendered_tables = len(rendered.select('table'))
            total_tables += rendered_tables
            if rendered_tables != original_tables:
                errors.append({'file': target.name, 'error': 'número de tablas distinto', 'expected': original_tables, 'actual': rendered_tables})
            for table_index, (source_table, rendered_table) in enumerate(zip(original.select('table'), rendered.select('table')), 1):
                source_shape = [len(row.find_all(['td', 'th'], recursive=False)) for row in source_table.select('tr')]
                rendered_shape = [len(row.find_all(['td', 'th'], recursive=False)) for row in rendered_table.select('tr')]
                if source_shape != rendered_shape:
                    errors.append({'file': target.name, 'error': 'estructura de tabla alterada', 'table': table_index, 'expected': source_shape, 'actual': rendered_shape})
            # Match all meaningful source words, including transcripts inside details.
            def words(value):
                return Counter(re.findall(r'[\wÁÉÍÓÚÜÑáéíóúüñ]{3,}', html.unescape(value).casefold()))
            missing_words = words(document['expected_text']) - words(rendered.get_text(' ', strip=True))
            if missing_words:
                errors.append({'file': target.name, 'error': 'texto del HTML ausente', 'words': dict(missing_words)})
            document['validation'] = {'code_blocks': len(codes), 'tables': rendered_tables, 'images': len(document['images']), 'missing_source_words': sum(missing_words.values())}
        for markdown in self.output.rglob('*.md'):
            rendered = BeautifulSoup(engine.render(markdown.read_text(encoding='utf-8')), 'html.parser')
            for tag in rendered.select('a[href], img[src]'):
                address = tag.get('href') or tag.get('src')
                parts = urlsplit(address)
                if parts.scheme or address.startswith('data:'):
                    continue
                file = (markdown.parent / unquote(parts.path)).resolve() if parts.path else markdown
                if not file.is_relative_to(self.output) or not file.is_file():
                    errors.append({'file': markdown.name, 'error': 'enlace local roto', 'url': address})
                elif parts.fragment and file.suffix == '.md':
                    destination = BeautifulSoup(engine.render(file.read_text(encoding='utf-8')), 'html.parser')
                    ids = {tag.get('id') for tag in destination.select('[id]')}
                    if unquote(parts.fragment) not in ids:
                        errors.append({'file': markdown.name, 'error': 'ancla local no conservada', 'url': address})
        for snapshot in self.snapshots:
            with Image.open(self.output / snapshot['path']) as image:
                if min(image.size) < 10:
                    errors.append({'file': snapshot['path'], 'error': 'captura demasiado pequeña'})
                extrema = image.convert('RGB').getextrema()
                if all(low == high for low, high in extrema):
                    errors.append({'file': snapshot['path'], 'error': 'captura vacía'})
        unchanged = all((self.source / name).is_file() and digest(self.source / name) == sha for name, sha in self.source_hashes.items())
        if not unchanged:
            errors.append({'error': 'La exportación original ha cambiado durante la operación'})
        return {'documents': len(self.documents), 'pdfs': len(self.pdfs), 'images': len(self.snapshots), 'code_blocks': total_codes, 'tables': total_tables, 'source_unchanged': unchanged, 'errors': errors}

    def report(self, validation: dict):
        known = {entry['original'] for entry in self.entries}
        for name in self.source_hashes:
            if name not in known:
                self.entries.append({'original': name, 'destino': None, 'accion': 'solo en respaldo original', 'motivo': 'Índice/registro de la exportación o icono de navegación Moodle sin contenido didáctico'})
        report = {
            'version': 1, 'origen': str(self.source), 'salida': str(self.output),
            'validacion': validation, 'avisos': self.warnings, 'reparaciones_estructurales': self.changes,
            'correspondencias': self.entries, 'capturas': self.snapshots,
            'pdfs': [{'original': p['source'].relative_to(self.source).as_posix(), 'destino': p['target'].relative_to(self.output).as_posix(), 'paginas': p['pages'], 'extracto_verificado': p['excerpt']} for p in self.pdfs],
            'sha256_originales': self.source_hashes,
            'documentos': [{'original': d['source'].relative_to(self.source).as_posix(), 'destino': d['target'].relative_to(self.output).as_posix(), 'validacion': d['validation']} for d in self.documents],
        }
        (self.output / 'MANIFIESTO.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        wrappers = sum(entry['accion'] == 'contenedor Moodle omitido' for entry in self.entries)
        lines = ['# Informe de limpieza', '', '## Resultado', '',
                 f'- {len(self.documents)} apuntes Markdown con contenido real.',
                 f'- {len(self.snapshots)} capturas locales de representaciones, diagramas y vistas HTML/CSS.',
                 f'- {len(self.pdfs)} PDF conservados sin alterar sus bytes y renombrados por su contenido.',
                 f'- {len(self.links)} referencias externas reunidas en `Recursos/Enlaces útiles.md`, más la guía de instalación de Microsoft Learn aportada como PDF.',
                 f'- {wrappers} páginas contenedoras Moodle excluidas de la copia limpia.',
                 '- ZIP de la calculadora e instalador de Visual Studio conservados, sin ejecutar.',
                 '- Las dos páginas Moodle con apuntes propios se han conservado: break/switch y tamaño de página.', '',
                 '## Comprobaciones', '',
                 f'- Bloques de código comprobados: {validation["code_blocks"]}.',
                 f'- Tablas comprobadas: {validation["tables"]}.',
                 f'- Errores de validación: {len(validation["errors"])}.',
                 f'- Exportación original sin cambios: {"sí" if validation["source_unchanged"] else "NO"}.',
                 '- Enlaces e imágenes locales, anclas internas, texto del HTML y capturas no vacías comprobados automáticamente.', '',
                 '## Cómo usar los apuntes', '',
                 '- Abre `INDICE.md` y usa la vista previa de Markdown de VS Code.',
                 '- Mantén cada carpeta `assets` junto a los Markdown: contiene los gráficos.',
                 '- Bajo las imágenes puedes desplegar su contenido textual para seleccionar, buscar o copiar texto y código.',
                 '- Los estilos generales de la página no se trasladan al tema del editor, pero las representaciones gráficas conservan su diseño mediante capturas.',
                 '- No se ha cambiado el contenido técnico del profesor, aunque pueda contener imprecisiones o referencias antiguas.',
                 '- Los HTML originales solo están en la exportación de respaldo; los apuntes limpios no dependen de ellos.', '',
                 '## Límites detectados', '']
        lines.extend(f'- {warning}' for warning in self.warnings)
        lines += ['', '## Reparaciones de formato y navegación', '', '- Los genéricos C# y fragmentos XAML escritos fuera de bloques de código se escapan para que Markdown no los interprete como etiquetas HTML.']
        lines.extend(f'- {change}' for change in self.changes)
        lines += ['', 'Los elementos animados se representan en un estado estático. Las actividades no descargadas (tareas, foros, cuestionarios y Jitsi) siguen disponibles solo en el aula; sus avisos permanecen en el registro original.', '',
                  '## Trazabilidad', '', '`MANIFIESTO.json` conserva nombres originales, destinos, motivos de exclusión, verificaciones y huellas SHA-256. No se ha borrado ningún archivo de `materiales`.', '']
        if validation['errors']:
            lines += ['## Errores pendientes', '', '```json', json.dumps(validation['errors'], ensure_ascii=False, indent=2), '```', '']
        (self.output / 'INFORME.md').write_text('\n'.join(lines), encoding='utf-8')

    def run(self):
        self.classify()
        self.copy_files()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1.5, java_script_enabled=True)
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            try:
                # Border first: sample and full course use exactly the same pipeline.
                self.documents.sort(key=lambda d: (identifier(d['record']) != '216432', d['target'].as_posix().casefold()))
                for document in self.documents:
                    self.render_document(page, document)
            finally:
                browser.close()
        self.write_links()
        self.write_indexes()
        (self.output / 'INFORME.md').write_text('# Informe de limpieza\n\nValidación en curso.\n', encoding='utf-8')
        validation = self.validate()
        self.report(validation)
        print(json.dumps(validation, ensure_ascii=False, indent=2), flush=True)
        return not validation['errors']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origen', type=Path, default=ROOT / 'materiales')
    parser.add_argument('--salida', type=Path, default=ROOT / 'materiales-limpios')
    args = parser.parse_args()
    if args.salida.resolve() == args.origen.resolve() or args.salida.resolve().is_relative_to(args.origen.resolve()):
        parser.error('La salida debe estar fuera de la exportación original')
    if args.salida.exists():
        parser.error('La carpeta de salida ya existe. Elige otra con --salida para no sobrescribir trabajo propio.')
    args.salida.mkdir(parents=True)
    cleaner = Cleaner(args.origen, args.salida)
    if not cleaner.run():
        raise SystemExit('Hay errores de validación: consulta INFORME.md antes de usar la copia como definitiva.')


if __name__ == '__main__':
    main()
