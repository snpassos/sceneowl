#!/usr/bin/env python3
"""
Edita as tres paginas da landing (que sao "Bundled Pages": <head> estatico +
manifest JSON com os assets em base64 + template JSON com o HTML real).

O arquivo maior tem 10 MB e nao comporta edicao manual. Tudo aqui e ancorado
por marcador, nunca por offset, e idempotente: rodar duas vezes nao duplica
tag nem re-substitui asset.

Uso: python scripts/patch-bundle-assets.py
"""

import base64
import json
import re
import struct
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


# Cada entrada do manifest tem a forma
#   "<uuid>":{"mime":"image/png","compressed":false,"data":"<base64>"}
# A troca e cirurgia de string ancorada no uuid, nao re-serializacao do JSON:
# assim tudo que nao e o alvo sai byte-identico.
def entry_re(uuid):
    return re.compile(
        r'("' + re.escape(uuid) + r'":\{"mime":")([^"]+)("[^{}]*?"data":")([^"]*)(")'
    )


# alt text -> arquivo novo. E o alt que identifica cada print no template;
# hardcodar uuid quebraria em silencio se a pagina fosse regerada.
SCREEN_BY_ALT = {
    'SceneOwl app home screen': ('assets/screens/home.webp', 'image/webp'),
    'SceneOwl watchlist screen': ('assets/screens/watchlist.webp', 'image/webp'),
    'SceneOwl profile screen': ('assets/screens/profile.webp', 'image/webp'),
    'SceneOwl title details screen': ('assets/screens/title-details.webp', 'image/webp'),
}
LOGO_ALT = 'SceneOwl'
LOGO_FILE = ('assets/logo-96.png', 'image/png')


def png_size(raw):
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return struct.unpack('>II', raw[16:24])


def find_targets(manifest, template_html):
    """Descobre uuid -> (arquivo novo, mime novo) pelo alt no template."""
    targets = {}
    for uuid, alt in re.findall(r'<img[^>]*src="([0-9a-f-]{36})"[^>]*alt="([^"]*)"', template_html):
        if alt in SCREEN_BY_ALT:
            targets[uuid] = SCREEN_BY_ALT[alt]
        elif alt == LOGO_ALT:
            # So o logo mestre: 917x958. Se ja foi trocado, e 96x96 e sai fora.
            raw = base64.b64decode(manifest[uuid]['data'])
            if png_size(raw) == (917, 958):
                targets[uuid] = LOGO_FILE
    return targets


def patch_assets(name, text):
    man_match = MANIFEST_RE.search(text)
    tpl_match = TEMPLATE_RE.search(text)
    if not man_match or not tpl_match:
        raise SystemExit(f'{name}: manifest ou template nao encontrado')

    manifest = json.loads(man_match.group(2))
    template_html = json.loads(tpl_match.group(2))
    targets = find_targets(manifest, template_html)

    if not targets:
        print(f'  {name}: nenhum asset pesado restante, pulando')
        return text

    man_raw = man_match.group(2)
    for uuid, (rel_path, mime) in targets.items():
        data = base64.b64encode((ROOT / rel_path).read_bytes()).decode('ascii')
        pattern = entry_re(uuid)
        if len(pattern.findall(man_raw)) != 1:
            raise SystemExit(f'{name}: entrada do manifest para {uuid} nao casou exatamente uma vez')
        man_raw = pattern.sub(
            lambda m: m.group(1) + mime + m.group(3) + data + m.group(5),
            man_raw,
            count=1,
        )
        print(f'  {name}: {uuid[:8]} -> {rel_path}')

    return text[:man_match.start(2)] + man_raw + text[man_match.end(2):]


def verify(name, text, template_before, keys_before):
    """Barreiras estruturais. Qualquer falha aqui aborta antes de salvar."""
    man_match = MANIFEST_RE.search(text)
    tpl_match = TEMPLATE_RE.search(text)
    manifest = json.loads(man_match.group(2))          # 1. manifest reparseavel
    template_html = json.loads(tpl_match.group(2))     # 2. template reparseavel

    # 3. o template saiu byte-identico: nada aqui deveria te-lo tocado
    if tpl_match.group(2) != template_before:
        raise SystemExit(f'{name}: o template mudou — nenhuma alteracao nele estava prevista')

    # 4. nenhuma entrada criada nem perdida. Esta e a checagem exata de "nenhum
    # uuid ficou orfao": trocamos conteudo, nunca o conjunto de chaves.
    # NAO tentar deduzir orfaos varrendo o template — ha 2 entradas
    # text/javascript por pagina que legitimamente nao aparecem nele, e a
    # versao ingenua aborta na primeira execucao.
    if set(manifest) != keys_before:
        raise SystemExit(f'{name}: o conjunto de uuids do manifest mudou')

    # 5. todo uuid citado no template existe no manifest
    used = set(re.findall(r'src="([0-9a-f-]{36})"', template_html))
    missing = used - set(manifest)
    if missing:
        raise SystemExit(f'{name}: uuid citado no template e ausente do manifest: {missing}')

    # 6. todo data decodifica e imagem tem assinatura batendo com o mime
    for uuid, entry in manifest.items():
        raw = base64.b64decode(entry['data'])
        if entry['mime'].startswith('image/'):
            sig = {
                'image/png': raw[:8] == b'\x89PNG\r\n\x1a\n',
                'image/jpeg': raw[:2] == b'\xff\xd8',
                'image/webp': raw[:4] == b'RIFF' and raw[8:12] == b'WEBP',
            }.get(entry['mime'])
            if not sig:
                raise SystemExit(f'{name}: {uuid} tem mime {entry["mime"]} mas assinatura invalida')

    print(f'  {name}: verificacao ok ({len(manifest)} entradas, {len(used)} referenciadas)')


def main():
    for name in PAGES:
        text = load_page(name)
        before = len(text)
        template_before = TEMPLATE_RE.search(text).group(2)
        keys_before = set(json.loads(MANIFEST_RE.search(text).group(2)))

        text = patch_head(name, text)
        text = patch_assets(name, text)
        verify(name, text, template_before, keys_before)

        save_page(name, text)
        print('{}: {:,} -> {:,} bytes\n'.format(name, before, len(text)))


if __name__ == '__main__':
    main()
