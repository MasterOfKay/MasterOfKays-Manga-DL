"""
Light novel chapters (a list of text paragraphs) saved as a file the user's reader
understands: EPUB (default, Komga/Kavita read it), PDF, Word, HTML, Markdown or text.

Everything is written by hand - no extra dependencies. EPUB and DOCX are zip files
of a few XML documents; the PDF uses the built-in Helvetica font, so it needs no
font files (characters outside Windows-1252 become '?').
"""

import hashlib
import html
import io
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List

from ..sites.base import save_file
from .models import NOVEL_FORMATS


@dataclass
class NovelChapter:
    series: str
    number: str
    title: str                       # chapter name without "Chapter N" ('' if none)
    paragraphs: List[str]
    author: str = ''
    language: str = 'en'
    cover_path: str = ''             # series cover, embedded in EPUBs
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def heading(self) -> str:
        return f"Chapter {self.number}" + (f": {self.title}" if self.title else '')

    @property
    def full_title(self) -> str:
        return f"{self.series} - {self.heading}"


def extension(fmt: str) -> str:
    return NOVEL_FORMATS.get(fmt, NOVEL_FORMATS['epub'])[1]


def write_chapter(path: str, fmt: str, chapter: NovelChapter) -> str:
    """Write the chapter to `path` (extension included) in the given format. Returns the path."""
    builder: Callable[[NovelChapter], bytes] = _BUILDERS.get(fmt, _epub)
    save_file(path, builder(chapter))
    return path


# ------------------------------------------------------------------ text formats
def _txt(ch: NovelChapter) -> bytes:
    lines = [ch.full_title, '=' * min(len(ch.full_title), 72), '']
    for paragraph in ch.paragraphs:
        lines += [paragraph, '']
    return '\n'.join(lines).encode('utf-8')


def _md(ch: NovelChapter) -> bytes:
    def escape(text: str) -> str:
        # Keep scene breaks ("***") as rules, stop other lines from turning into headings/lists.
        if text.strip() in ('***', '* * *', '---'):
            return '---'
        return ('\\' + text) if text[:1] in '#>-+*' or text[:2].rstrip('.').isdigit() and text[1:2] == '.' else text
    body = '\n\n'.join(escape(p) for p in ch.paragraphs)
    return f"# {ch.full_title}\n\n{body}\n".encode('utf-8')


def _xhtml_body(ch: NovelChapter) -> str:
    parts = [f"<h1>{html.escape(ch.heading)}</h1>"]
    for paragraph in ch.paragraphs:
        if paragraph.strip() in ('***', '* * *'):
            parts.append('<hr/>')
        else:
            parts.append(f"<p>{html.escape(paragraph)}</p>")
    return '\n'.join(parts)


_CSS = ("body { font-family: Georgia, serif; line-height: 1.6; margin: 0 auto; max-width: 42em; padding: 1em; }\n"
        "h1 { font-size: 1.5em; margin: 1em 0; }\np { margin: 0 0 0.9em; text-align: justify; }\n"
        "hr { border: 0; text-align: center; margin: 1.5em 0; }\nhr:after { content: '* * *'; }\n")


def _html(ch: NovelChapter) -> bytes:
    return (f"<!DOCTYPE html>\n<html lang=\"{html.escape(ch.language)}\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>{html.escape(ch.full_title)}</title>\n<style>\n{_CSS}</style>\n</head>\n<body>\n"
            f"<p><small>{html.escape(ch.series)}</small></p>\n{_xhtml_body(ch)}\n</body>\n</html>\n").encode('utf-8')


# ------------------------------------------------------------------------- EPUB
def _epub(ch: NovelChapter) -> bytes:
    uid = 'urn:uuid:' + _uuid(f"{ch.series}|{ch.number}")
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    cover = _read_cover(ch.cover_path)
    esc = html.escape
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="css" href="style.css" media-type="text/css"/>',
                '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>']
    cover_meta = ''
    if cover:
        name, media = cover[0], cover[1]
        manifest.append(f'<item id="cover" href="{name}" media-type="{media}" properties="cover-image"/>')
        cover_meta = '<meta name="cover" content="cover"/>'
    position = ch.number if ch.number.replace('.', '', 1).isdigit() else ''
    series_meta = (f'<meta property="belongs-to-collection" id="series">{esc(ch.series)}</meta>\n'
                   '<meta refines="#series" property="collection-type">series</meta>\n'
                   + (f'<meta refines="#series" property="group-position">{position}</meta>\n' if position else '')
                   + f'<meta name="calibre:series" content="{esc(ch.series)}"/>\n'
                   + (f'<meta name="calibre:series_index" content="{position}"/>\n' if position else ''))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="{esc(ch.language)}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">{uid}</dc:identifier>
<dc:title>{esc(ch.full_title)}</dc:title>
<dc:language>{esc(ch.language)}</dc:language>
{f'<dc:creator>{esc(ch.author)}</dc:creator>' if ch.author else ''}
<meta property="dcterms:modified">{modified}</meta>
{series_meta}{cover_meta}
</metadata>
<manifest>
{chr(10).join(manifest)}
</manifest>
<spine>
<itemref idref="chapter"/>
</spine>
</package>
"""
    page = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{esc(ch.language)}">
<head><title>{esc(ch.heading)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{_xhtml_body(ch)}
</body>
</html>
"""
    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{esc(ch.heading)}</title></head>
<body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">{esc(ch.heading)}</a></li></ol></nav></body>
</html>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', nav)
        z.writestr('OEBPS/chapter.xhtml', page)
        z.writestr('OEBPS/style.css', _CSS)
        if cover:
            z.writestr(f'OEBPS/{cover[0]}', cover[2], compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def _read_cover(path: str):
    """(file name, media type, bytes) of the series cover, None if missing or too big."""
    if not path or not os.path.isfile(path) or os.path.getsize(path) > 3 * 1024 * 1024:
        return None
    ext = os.path.splitext(path)[1].lower()
    media = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
             '.gif': 'image/gif'}.get(ext)
    if not media:
        return None
    with open(path, 'rb') as f:
        return f"cover{ext}", media, f.read()


def _uuid(seed: str) -> str:
    h = hashlib.md5(seed.encode('utf-8')).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ------------------------------------------------------------------------- DOCX
def _docx(ch: NovelChapter) -> bytes:
    esc = html.escape

    def para(text: str, size: int = 0, bold: bool = False, center: bool = False) -> str:
        props = ''.join(['<w:b/>' if bold else '', f'<w:sz w:val="{size}"/>' if size else ''])
        ppr = '<w:pPr><w:jc w:val="center"/></w:pPr>' if center else '<w:pPr><w:spacing w:after="160"/></w:pPr>'
        return (f'<w:p>{ppr}<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}'
                f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')

    body = [para(ch.series, 20), para(ch.heading, 36, bold=True)]
    for paragraph in ch.paragraphs:
        scene = paragraph.strip() in ('***', '* * *')
        body.append(para('* * *' if scene else paragraph, center=scene))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + ''.join(body) +
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
                '</w:body></w:document>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title>{esc(ch.full_title)}</dc:title><dc:creator>{esc(ch.author)}</dc:creator>'
            '</cp:coreProperties>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/docProps/core.xml" '
             'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
            '</Relationships>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', document)
        z.writestr('docProps/core.xml', core)
    return buffer.getvalue()


# -------------------------------------------------------------------------- PDF
# Helvetica glyph widths (1/1000 em) for ASCII 32..126, from the standard AFM metrics.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_EXTRA = {'‘': 222, '’': 222, '“': 333, '”': 333, '–': 556, '—': 1000, '…': 1000, '•': 350}
_PAGE_W, _PAGE_H, _MARGIN = 595, 842, 64          # A4 in points


def _width(text: str, size: float, bold: bool = False) -> float:
    total = 0
    for char in text:
        code = ord(char)
        total += _HELV[code - 32] if 32 <= code <= 126 else _HELV_EXTRA.get(char, 556)
    return total * size / 1000 * (1.06 if bold else 1.0)


def _wrap(text: str, size: float, width: float, bold: bool = False) -> List[str]:
    lines, line = [], ''
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if _width(candidate, size, bold) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or ['']


def _pdf_text(text: str) -> bytes:
    raw = text.encode('cp1252', errors='replace')
    return raw.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')


def _pdf(ch: NovelChapter) -> bytes:
    width = _PAGE_W - 2 * _MARGIN
    # (font, size, text, gap before) for every line, then laid out on pages.
    items = [('F1', 9, line, 0) for line in _wrap(ch.series, 9, width)]
    items += [('F2', 17, line, 14 if i == 0 else 0) for i, line in enumerate(_wrap(ch.heading, 17, width, True))]
    for paragraph in ch.paragraphs:
        if paragraph.strip() in ('***', '* * *'):
            items.append(('F1', 11, '*   *   *', 12))
            continue
        for i, line in enumerate(_wrap(paragraph, 11, width)):
            items.append(('F1', 11, line, 9 if i == 0 else 0))

    pages: List[bytes] = []
    stream = io.BytesIO()
    y = _PAGE_H - _MARGIN
    for font, size, text, gap in items:
        leading = size * 1.4
        if y - gap - leading < _MARGIN:
            pages.append(stream.getvalue())
            stream = io.BytesIO()
            y = _PAGE_H - _MARGIN
            gap = 0
        y -= gap + leading
        x = _MARGIN + ((width - _width(text, size)) / 2 if text.startswith('*   *') else 0)
        stream.write(b'BT /%s %d Tf %.2f %.2f Td (' % (font.encode(), size, x, y) + _pdf_text(text) + b') Tj ET\n')
    pages.append(stream.getvalue())

    objects: List[bytes] = []
    page_ids = [5 + 2 * i for i in range(len(pages))]
    objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    objects.append(b'<< /Type /Pages /Kids [%s] /Count %d >>'
                   % (b' '.join(b'%d 0 R' % i for i in page_ids), len(pages)))
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
    for i, content in enumerate(pages):
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                       b'/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>'
                       % (_PAGE_W, _PAGE_H, page_ids[i] + 1))
        objects.append(b'<< /Length %d >>\nstream\n' % len(content) + content + b'endstream')
    info_id = len(objects) + 1
    objects.append(b'<< /Title (' + _pdf_text(ch.full_title) + b') /Author (' + _pdf_text(ch.author) + b') >>')

    out = io.BytesIO()
    out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for offset in offsets:
        out.write(b'%010d 00000 n \n' % offset)
    out.write(b'trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n'
              % (len(objects) + 1, info_id, xref))
    return out.getvalue()


_BUILDERS: Dict[str, Callable[[NovelChapter], bytes]] = {
    'epub': _epub, 'pdf': _pdf, 'docx': _docx, 'html': _html, 'md': _md, 'txt': _txt,
}
