import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from descargar import Exporter, activity_key, discover, safe_name


class ExportTests(unittest.TestCase):
    def test_windows_names(self):
        self.assertEqual(safe_name('CON'), '_CON')
        self.assertEqual(safe_name('Tema: uno/dos?'), 'Tema_ uno_dos_')
        self.assertEqual(safe_name('...'), 'sin-titulo')

    def test_activity_identity(self):
        self.assertEqual(activity_key('https://a/mod/book/view.php?id=12&chapterid=5'), ('book', '12'))

    def test_discovery_scoped_and_deduplicated(self):
        soup = BeautifulSoup('''<a href="/mod/forum/view.php?id=9">Menú</a>
        <li class="section"><h3 class="sectionname">Controles</h3>
        <li class="activity resource"><a href="/mod/resource/view.php?id=7"><span class="instancename">CheckBox</span></a>
        <a href="/mod/resource/view.php?id=7">Otra vista</a></li>
        <li class="activity"><a href="https://externo/mod/page/view.php?id=8">Fuera</a></li></li>''', 'html.parser')
        items = discover(soup, 'https://a/course/view.php?id=929')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['section'], 'Controles')
        self.assertEqual(items[0]['title'], 'CheckBox')

    def test_inert_html_and_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exporter = Exporter(None, 'https://a/course/view.php?id=929', folder, 0)
            exporter.save_html(b'<html><body onload="bad()"><h1>Ejemplo</h1><script>bad()</script><form>Enviar</form><a href="javascript:bad()">x</a><pre><code>int x = 1;</code></pre></body></html>', 'https://a/file.html', folder, 'contenido', [])
            result = (folder / 'contenido.html').read_text(encoding='utf-8')
            self.assertNotIn('<script', result)
            self.assertNotIn('<form', result)
            self.assertNotIn('onload', result)
            self.assertNotIn('javascript:', result)
            self.assertIn('int x = 1;', (folder / 'contenido.md').read_text(encoding='utf-8'))

    def test_resource_wrapper_downloads_actual_html(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exporter = Exporter(None, 'https://a/course/view.php?id=929', folder, 0)
            resource = 'https://a/mod/resource/view.php?id=7'
            file = 'https://a/pluginfile.php/23/mod_resource/content/2/check.html'
            pages = {
                resource: b'<main role="main"><iframe src="' + file.encode() + b'"></iframe></main>',
                file: b'<html><h1>CheckBox</h1><p>Contenido real</p></html>',
            }
            exporter.fetch = lambda url: (url, {'content-type': 'text/html'}, pages[url])
            item = {'title': 'CheckBox', 'section': 'Controles', 'type': 'resource', 'url': resource}
            exporter.export(item)
            self.assertEqual(len(item['files']), 2)
            self.assertTrue(any('Contenido real' in (folder / file).read_text(encoding='utf-8') for file in item['files']))
            exporter.index([item])
            self.assertTrue((folder / 'index.html').exists())

    def test_offsite_request_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            exporter = Exporter(None, 'https://a/course/view.php?id=929', Path(temp), 0)
            with self.assertRaises(ValueError):
                exporter.fetch('https://externo/archivo.pdf')

    def test_inline_styles_without_style_attributes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exporter = Exporter(None, 'https://a/course/view.php?id=929', folder, 0)
            exporter.fetch = lambda url: (url, {'content-type': 'image/png'}, b'fake-image')
            exporter.save_html(b'<html><head><style>body{background:url("image.png")}</style></head><body>Texto</body></html>', 'https://a/file.html', folder, 'contenido', [])
            result = (folder / 'contenido.html').read_text(encoding='utf-8')
            self.assertIn('assets/', result)
            self.assertEqual(len(list((folder / 'assets').iterdir())), 1)

    def test_external_redirect_not_followed(self):
        class Response:
            status = 302
            headers = {'location': 'https://externo/privado'}

            def dispose(self):
                pass

        class Request:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                return Response()

        class Context:
            request = Request()

        with tempfile.TemporaryDirectory() as temp:
            exporter = Exporter(Context(), 'https://a/course/view.php?id=929', Path(temp), 0)
            with self.assertRaises(ValueError):
                exporter.fetch('https://a/archivo')
            self.assertEqual(exporter.context.request.calls, ['https://a/archivo'])

    def test_login_page_detected_in_authenticated_request(self):
        class Response:
            status = 200
            ok = True
            headers = {'content-type': 'text/html'}

            def body(self):
                return b'<html><input name="password" type="password"></html>'

            def dispose(self):
                pass

        class Request:
            def get(self, url, **kwargs):
                return Response()

        class Context:
            request = Request()

        with tempfile.TemporaryDirectory() as temp:
            exporter = Exporter(Context(), 'https://a/course/view.php?id=929', Path(temp), 0)
            with self.assertRaisesRegex(RuntimeError, 'página de acceso'):
                exporter.fetch(exporter.course)


if __name__ == '__main__':
    unittest.main()
