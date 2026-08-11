#!/usr/bin/env python3
"""
Edita as tres paginas da landing (que sao "Bundled Pages": <head> estatico +
manifest JSON com os assets em base64 + template JSON com o HTML real).

O arquivo maior tem 10 MB e nao comporta edicao manual. Tudo aqui e ancorado
por marcador, nunca por offset, e idempotente: rodar duas vezes nao duplica
tag nem re-substitui asset.

Uso: python scripts/patch-bundle-assets.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'https://snpassos.github.io/sceneowl/'

MANIFEST_RE = re.compile(r'(<script type="__bundler/manifest">)(.*?)(</script>)', re.S)
TEMPLATE_RE = re.compile(r'(<script type="__bundler/template">)(.*?)(</script>)', re.S)

# Metas comuns as tres paginas. O <head> estatico e o unico que crawler sem JS
# enxerga, e e tambem o unico que vale antes do unpack.
COMMON_TAGS = """  <link rel="icon" type="image/png" href="favicon.png">
  <link rel="apple-touch-icon" href="apple-touch-icon.png">
  <meta property="og:type" content="website">
  <meta property="og:image" content="{base}og-image.jpg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="SceneOwl — Every scene. Remembered.">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{base}og-image.jpg">
""".format(base=BASE_URL)

SITE_DESCRIPTION = (
    'SceneOwl is your personal catalog for movies and TV shows: build a watchlist, '
    'rate titles, track episode-by-episode progress, and see what your friends are watching.'
)

PAGES = {
    'index.html': {
        'url': BASE_URL,
        'twitter_title': 'SceneOwl',
        'twitter_description': SITE_DESCRIPTION,
        # index.html ja tem title, og:title, og:site_name e og:description no
        # <head> estatico — nao duplicar.
        'extra': '',
    },
    'privacy-policy.html': {
        'url': BASE_URL + 'privacy-policy.html',
        'twitter_title': 'SceneOwl — Privacy Policy',
        'twitter_description': 'How SceneOwl collects, uses, and protects your data.',
        'extra': """  <meta name="description" content="How SceneOwl collects, uses, and protects your data.">
  <meta property="og:title" content="SceneOwl — Privacy Policy">
  <meta property="og:site_name" content="SceneOwl">
  <meta property="og:description" content="How SceneOwl collects, uses, and protects your data.">
""",
        'title': 'SceneOwl — Privacy Policy',
    },
    'terms-of-service.html': {
        'url': BASE_URL + 'terms-of-service.html',
        'twitter_title': 'SceneOwl — Terms of Service',
        'twitter_description': 'The terms for using SceneOwl.',
        'extra': """  <meta name="description" content="The terms for using SceneOwl.">
  <meta property="og:title" content="SceneOwl — Terms of Service">
  <meta property="og:site_name" content="SceneOwl">
  <meta property="og:description" content="The terms for using SceneOwl.">
""",
        'title': 'SceneOwl — Terms of Service',
    },
}


# Bytes, nao texto, nos dois sentidos. `read_text`/`write_text` fazem traducao
# de fim de linha (universal newlines na leitura, os.linesep na escrita): no
# Windows isso reescreveria TODA quebra de linha de um arquivo de 10 MB, e o
# diff viria com o arquivo inteiro alterado em vez das poucas linhas do head.
def load_page(name):
    return (ROOT / name).read_bytes().decode('utf-8')


def save_page(name, text):
    (ROOT / name).write_bytes(text.encode('utf-8'))


def static_head_end(text):
    """Indice do </head> ESTATICO (o primeiro do arquivo).

    O template embutido tem um </head> proprio, mas ele aparece muito depois,
    dentro do JSON. Usar o primeiro garante que estamos no head servido.
    """
    idx = text.find('</head>')
    if idx == -1:
        raise SystemExit('sem </head> estatico — arquivo em formato inesperado')
    return idx


def patch_head(name, text):
    """Injeta as metas no <head> estatico. Idempotente."""
    end = static_head_end(text)
    head = text[:end]

    if 'og:image' in head:
        print(f'  {name}: head ja tem og:image, pulando')
        return text

    page = PAGES[name]
    block = COMMON_TAGS + page['extra']
    block += f'  <meta property="og:url" content="{page["url"]}">\n'
    block += f'  <meta name="twitter:title" content="{page["twitter_title"]}">\n'
    block += f'  <meta name="twitter:description" content="{page["twitter_description"]}">\n'

    # As paginas legais anunciam "Bundled Page" no title estatico — e o que a
    # aba mostra antes do unpack, e o que um crawler sem JS indexa. O <helmet>
    # interno continua sobrescrevendo com "SceneOwl" depois.
    if 'title' in page:
        text, n = re.subn(r'<title>Bundled Page</title>',
                          f'<title>{page["title"]}</title>', text, count=1)
        if n != 1:
            raise SystemExit(f'{name}: nao achei <title>Bundled Page</title> pra trocar')
        end = static_head_end(text)

    print(f'  {name}: {block.count(chr(10))} tags no head')
    return text[:end] + block + text[end:]


def main():
    for name in PAGES:
        text = load_page(name)
        before = len(text)
        text = patch_head(name, text)
        save_page(name, text)
        print(f'{name}: {before:,} -> {len(text):,} bytes')


if __name__ == '__main__':
    main()
