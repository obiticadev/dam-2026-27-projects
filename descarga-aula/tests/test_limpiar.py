import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from limpiar import (
    Cleaner, code_language, converter, fix_encoding, meaningful_body,
    normalize_code, page_code_blocks, readable_title, relative_link,
)


class CleanupTests(unittest.TestCase):
    def test_encoding_and_titles(self):
        self.assertEqual(fix_encoding('IntroducciÃ³n a C#'), 'Introducción a C#')
        self.assertEqual(readable_title('Border Archivo'), 'Border')
        self.assertEqual(readable_title('Mi Página de ejemplo'), 'Mi Página de ejemplo')

    def test_pdf_names_keep_ra(self):
        cleaner = object.__new__(Cleaner)
        self.assertEqual(cleaner.pdf_name(Path('5c95c643a0-TEMA 1 RA1f.pdf')),
                         'TEMA 1 RA1f - Eventos y controladores de acciones.pdf')

    def test_code_preserved_in_visual_transcript(self):
        soup = BeautifulSoup('''<div data-study-image="assets/demo.png" data-study-title="Vista">
        <pre data-lang="csharp"><code>var x = "a_b";
if (x != null) { Console.WriteLine(x); }</code></pre></div>''', 'html.parser')
        result = converter().convert(str(soup))
        self.assertIn('![Vista](assets/demo.png)', result)
        engine = MarkdownIt('commonmark', {'html': True})
        codes = [normalize_code(t.content) for t in engine.parse(result) if t.type == 'fence']
        self.assertEqual(codes, [normalize_code(soup.pre.get_text())])

    def test_nested_markup_does_not_change_code(self):
        result = converter().convert('<pre data-lang="xml"><code>&lt;Label Text="a_b" /&gt;</code></pre>')
        self.assertIn('```xml\n<Label Text="a_b" />\n```', result)

    def test_moodle_page_is_preserved_without_navigation(self):
        soup = BeautifulSoup('''<section id="region-main"><div class="activity-header">Ruido</div>
        <div role="main"><div class="no-overflow"><h2>Requisitos de finalización</h2><p>Apuntes reales</p></div></div>
        <nav class="activity-navigation">Anterior</nav></section>''', 'html.parser')
        body = meaningful_body(soup, True)
        self.assertIn('Apuntes reales', body.get_text())
        self.assertNotIn('Requisitos', body.get_text())
        self.assertNotIn('Anterior', body.get_text())

    def test_code_paragraphs_become_fences(self):
        soup = BeautifulSoup('<div><p><em><strong>switch (numero)</strong></em><br/><strong>{</strong><br/><strong>    case 1: break;</strong><br/><strong>}</strong></p></div>', 'html.parser')
        page_code_blocks(soup.div, soup)
        self.assertEqual(soup.pre.get_text(), 'switch (numero)\n{\n    case 1: break;\n}')
        self.assertEqual(code_language(soup.pre), 'csharp')

    def test_links_with_hash_and_spaces_are_encoded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.assertEqual(relative_link(folder / 'Tema' / 'C# y XAML.md', folder / 'INDICE.md'), 'Tema/C%23%20y%20XAML.md')

    def test_original_fragment_anchors_survive(self):
        result = converter().convert('<a data-study-anchor="intro"></a><h2>Introducción</h2><a href="#intro">Ir</a>')
        self.assertIn('<a id="intro"></a>', result)
        self.assertIn('[Ir](#intro)', result)

    def test_generic_types_are_not_treated_as_html(self):
        result = converter().convert('<h3>List&lt;string&gt;</h3><p>Task&lt;FileResult&gt; y permiso &lt;uses-permission CAMERA&gt;</p>')
        rendered = MarkdownIt('commonmark').render(result)
        text = BeautifulSoup(rendered, 'html.parser').get_text()
        self.assertIn('List<string>', text)
        self.assertIn('Task<FileResult>', text)
        self.assertIn('CAMERA', text)

    def test_inline_code_classes_become_real_code(self):
        result = converter().convert('<span class="inline-code">List&lt;string&gt;</span>')
        self.assertEqual(result.strip(), '`List<string>`')

    def test_pipe_inside_table_code_does_not_create_columns(self):
        source = '<table><thead><tr><th>Valor</th><th>Ejemplo</th></tr></thead><tbody><tr><td>Estilo</td><td><code>Bold|Italic</code></td></tr></tbody></table>'
        result = converter().convert(source)
        rendered = BeautifulSoup(MarkdownIt('commonmark').enable('table').render(result), 'html.parser')
        self.assertEqual([len(row.find_all(['td', 'th'], recursive=False)) for row in rendered.select('tr')], [2, 2])
        self.assertIn('Bold|Italic', rendered.get_text())


if __name__ == '__main__':
    unittest.main()
