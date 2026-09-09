#!/usr/bin/env python3
"""
Edita o <head> estatico das tres paginas do site e mantem sitemap.xml /
robots.txt / .nojekyll em dia.

As paginas NAO sao todas do mesmo tipo:

  index.html            "Bundled Page": <head> estatico + manifest JSON com os
                        assets em base64 + template JSON com o HTML real. ~1 MB,
                        nao comporta edicao manual.
  privacy-policy.html   HTML estatico comum (deixaram de ser Bundled Pages no
  terms-of-service.html commit ec7909a — estavam vindo vazias pra crawler).

O script detecta o tipo por pagina (presenca do manifest) em vez de assumir:
antes ele tratava as tres como bundled e abortava com AttributeError na
primeira pagina legal, depois de ja ter salvado o index.html.

Tudo aqui e ancorado por marcador, nunca por offset, e idempotente: rodar duas
vezes nao duplica tag nem re-substitui asset.

Uso: python scripts/patch-bundle-assets.py
"""

import base64
import json
import re
import struct
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'https://sceneowl.com/'

MANIFEST_RE = re.compile(r'(<script type="__bundler/manifest">)(.*?)(</script>)', re.S)
TEMPLATE_RE = re.compile(r'(<script type="__bundler/template">)(.*?)(</script>)', re.S)

SITE_DESCRIPTION = (
    'SceneOwl is your personal catalog for movies and TV shows: build a watchlist, '
    'rate titles, track episode-by-episode progress, and see what your friends are watching.'
)

# `lang` no <html> estatico: sem isso o Google trata o idioma como indefinido.
# Nas paginas bundled o swap do runtime substitui o documento inteiro, entao
# aqui isso vale pro crawler sem JS e pro estado pre-unpack — que e justamente
# o que a validacao do Google enxerga.
PAGES = {
    'index.html': {
        'url': BASE_URL,
        'lang': 'en',
        # Fallbacks usados so se a tag ainda nao existir no head.
        'title': 'SceneOwl',
        'description': SITE_DESCRIPTION,
    },
    'privacy-policy.html': {
        'url': BASE_URL + 'privacy-policy.html',
        'lang': 'pt-BR',
        'title': 'SceneOwl — Privacy Policy',
        'description': 'How SceneOwl collects, uses, and protects your data.',
    },
    'terms-of-service.html': {
        'url': BASE_URL + 'terms-of-service.html',
        'lang': 'pt-BR',
        'title': 'SceneOwl — Terms of Service',
        'description': 'The terms for using SceneOwl.',
    },
}


# Bytes, nao texto, nos dois sentidos. `read_text`/`write_text` fazem traducao
# de fim de linha (universal newlines na leitura, os.linesep na escrita): no
# Windows isso reescreveria TODA quebra de linha de um arquivo de 1 MB, e o
# diff viria com o arquivo inteiro alterado em vez das poucas linhas do head.
def load_page(name):
    text = (ROOT / name).read_bytes().decode('utf-8')
    # Aborta em vez de "consertar": com o arquivo em CRLF os marcadores deste
    # script param de casar e, pior, o commit sai com o arquivo inteiro no diff.
    # Ja aconteceu duas vezes (index.html e terms-of-service.html) por checkout
    # com core.autocrlf=true. O .gitattributes deste repo (`* -text`) impede a
    # recorrencia; esta barreira pega o caso de um clone anterior a ele.
    if '\r\n' in text:
        raise SystemExit(
            f'{name}: arquivo com CRLF. Restaure os bytes originais com\n'
            f'    python -c "import subprocess;'
            f'open(\'{name}\',\'wb\').write(subprocess.run([\'git\',\'show\',\'HEAD:{name}\'],'
            f'capture_output=True).stdout)"\n'
            '  e confirme que o .gitattributes esta presente antes de rodar de novo.'
        )
    return text


def save_page(name, text):
    (ROOT / name).write_bytes(text.encode('utf-8'))


def is_bundled(text):
    return MANIFEST_RE.search(text) is not None


def static_head_end(text):
    """Indice do </head> ESTATICO (o primeiro do arquivo).

    O template embutido tem um </head> proprio, mas ele aparece muito depois,
    dentro do JSON. Usar o primeiro garante que estamos no head servido.
    """
    idx = text.find('</head>')
    if idx == -1:
        raise SystemExit('sem </head> estatico — arquivo em formato inesperado')
    return idx


def head_of(text):
    return text[:static_head_end(text)]


def first_group(pattern, head, default=None):
    m = re.search(pattern, head)
    return m.group(1) if m else default


# ---------------------------------------------------------------- <html lang>

def patch_lang(name, text):
    """Garante lang no <html> estatico. Idempotente."""
    lang = PAGES[name]['lang']
    m = re.search(r'<html([^>]*)>', text)
    if not m:
        raise SystemExit(f'{name}: sem <html> estatico')
    if 'lang=' in m.group(1):
        return text
    print(f'  {name}: <html lang="{lang}"> adicionado')
    return text[:m.start()] + f'<html lang="{lang}">' + text[m.end():]


# ------------------------------------------------------------------- <head>

def patch_head(name, text):
    """Completa o <head> estatico com as tags que ainda faltam.

    Tag a tag em vez de um bloco tudo-ou-nada (o guard antigo era um unico
    `if 'og:image' in head`): as paginas legais ja tinham title, description e
    canonical proprios mas nenhuma tag social, e o bloco inteiro era pulado ou
    duplicava o que ja existia. O titulo/descricao ja declarados na pagina
    ganham dos valores de PAGES — eles sao so fallback.
    """
    head = head_of(text)
    page = PAGES[name]

    title = first_group(r'<title>(.*?)</title>', head, page['title'])
    description = first_group(
        r'<meta\s+name="description"\s+content="([^"]*)"', head, page['description']
    )

    # (marcador que prova que a tag ja existe, linha a inserir)
    wanted = [
        ('rel="icon"', '  <link rel="icon" type="image/png" href="favicon.png">'),
        ('apple-touch-icon', '  <link rel="apple-touch-icon" href="apple-touch-icon.png">'),
        ('name="description"', f'  <meta name="description" content="{description}">'),
        ('rel="canonical"', f'  <link rel="canonical" href="{page["url"]}">'),
        ('og:type', '  <meta property="og:type" content="website">'),
        ('og:site_name', '  <meta property="og:site_name" content="SceneOwl">'),
        ('og:title', f'  <meta property="og:title" content="{title}">'),
        ('og:description', f'  <meta property="og:description" content="{description}">'),
        ('og:url', f'  <meta property="og:url" content="{page["url"]}">'),
        ('og:image"', f'  <meta property="og:image" content="{BASE_URL}og-image.jpg">'),
        ('og:image:width', '  <meta property="og:image:width" content="1200">'),
        ('og:image:height', '  <meta property="og:image:height" content="630">'),
        ('og:image:alt',
         '  <meta property="og:image:alt" content="SceneOwl — Every scene. Remembered.">'),
        ('twitter:card', '  <meta name="twitter:card" content="summary_large_image">'),
        ('twitter:image', f'  <meta name="twitter:image" content="{BASE_URL}og-image.jpg">'),
        ('twitter:title', f'  <meta name="twitter:title" content="{title}">'),
        ('twitter:description', f'  <meta name="twitter:description" content="{description}">'),
    ]

    missing = [line for marker, line in wanted if marker not in head]
    if not missing:
        print(f'  {name}: head ja completo, pulando')
        return text

    print(f'  {name}: {len(missing)} tag(s) adicionada(s) no head')
    block = '\n'.join(missing) + '\n'
    end = static_head_end(text)
    return text[:end] + block + text[end:]


# ------------------------------------------------------------------ watchdog

# Watchdog defensivo: relatado um caso real (Firefox, so na primeira visita,
# nao reproduzido depois) onde imagens e CSS carregaram mas nenhum texto
# apareceu ate o usuario recarregar manualmente. Investigacao (comparacao de
# hash entre o manifest antes/depois deste patch) confirmou que os blobs do
# runtime/React/ReactDOM sao byte-identicos a versao anterior a qualquer
# mudanca desta sessao — nao e regressao deste script.
#
# Causa reproduzida deliberadamente (Chromium com DecompressionStream
# removido via init script, pra simular a API ausente/falhando): o loader
# gerado pela ferramenta (nao editavel por nos, marcado "GENERATED... do not
# edit") so descomprime os blobs do runtime/React/ReactDOM (gzip) se
# `DecompressionStream` existir; se nao existir OU a descompressao falhar por
# qualquer motivo transitorio, cai num console.warn/catch SEM fallback,
# entao esses tres scripts nunca executam de verdade — mas o resto do
# unpack (que so faz atob() em base64, sem depender de DecompressionStream)
# segue normal. Como o corpo da pagina inteiro e template ({{ t.chave }}),
# sem o runtime pra resolver esses tokens o body.innerText fica cheio de
# placeholders literais tipo "{{ t.heroTitle }}" em vez de texto de verdade
# — NAO fica vazio, entao um limiar por tamanho de texto nunca dispararia;
# o sinal certo e a presenca do padrao "{{ t." ainda visivel no corpo.
#
# So faz sentido em pagina bundled: as paginas legais sao HTML estatico, sem
# template pra resolver.
WATCHDOG_MARKER = 'sceneowl_dc_reload_once'
WATCHDOG_SCRIPT = f"""  <script>
  (function () {{
    try {{
      var KEY = '{WATCHDOG_MARKER}';
      if (sessionStorage.getItem(KEY)) return;
      setTimeout(function () {{
        var text = (document.body && document.body.innerText || '');
        if (text.indexOf('{{{{ t.') !== -1) {{
          sessionStorage.setItem(KEY, '1');
          location.reload();
        }}
      }}, 12000);
    }} catch (e) {{
      // sessionStorage bloqueado (modo privado estrito etc.) — melhor nao
      // arriscar reload em loop do que insistir sem conseguir marcar a tentativa.
    }}
  }})();
  </script>
"""


WATCHDOG_BLOCK_RE = re.compile(
    r'  <script>\n  \(function \(\) \{.*?' + re.escape(WATCHDOG_MARKER) + r'.*?\n  </script>\n',
    re.S,
)


def patch_watchdog(name, text):
    """Injeta (ou atualiza) o watchdog de reload no <head> estatico.

    Substitui pelo conteudo atual em vez de so pular quando o marcador ja
    existe: assim uma correcao na logica do watchdog se propaga ao rodar de
    novo, igual ao find_targets() comparando bytes em vez de so presenca.
    """
    end = static_head_end(text)
    head = text[:end]

    if WATCHDOG_MARKER not in head:
        print(f'  {name}: watchdog de reload adicionado')
        return text[:end] + WATCHDOG_SCRIPT + text[end:]

    # O marcador esta la mas o bloco nao casou: quase sempre e fim de linha
    # convertido pra CRLF por um checkout com core.autocrlf (o .gitattributes
    # deste repo existe pra impedir isso). Antes dava um AttributeError cru.
    match = WATCHDOG_BLOCK_RE.search(head)
    if match is None:
        crlf = '\r\n' in head
        raise SystemExit(
            f'{name}: marcador do watchdog presente mas o bloco nao casou com o padrao'
            + (' — o arquivo esta com CRLF; restaure com `git show HEAD:{0} > {0}` '
               'e confira o .gitattributes'.format(name) if crlf else '')
        )

    if match.group(0) == WATCHDOG_SCRIPT:
        print(f'  {name}: watchdog ja atualizado, pulando')
        return text

    print(f'  {name}: watchdog de reload atualizado')
    new_head, n = WATCHDOG_BLOCK_RE.subn(WATCHDOG_SCRIPT, head, count=1)
    if n != 1:
        raise SystemExit(f'{name}: watchdog antigo nao casou com o padrao esperado pra substituicao')
    return new_head + text[end:]


# -------------------------------------------------------------------- assets

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

# DUAS imagens diferentes usam alt="SceneOwl": o icone quadrado da nav e a marca
# bicolor (wordmark) que o commit 2bfc9e3 colocou no lugar do texto plano. Mapear
# as duas para o mesmo arquivo pelo alt faz o wordmark 917x157 ser sobrescrito
# pelo icone 96x96 — ou seja, reverte o 2bfc9e3 em silencio, sem erro nenhum.
# O discriminador e a forma da imagem que ja esta no slot: quadrada = icone,
# larga = wordmark.
LOGO_ALT = 'SceneOwl'
LOGO_SQUARE = ('assets/logo-96.png', 'image/png')
LOGO_WORDMARK = ('assets/wordmark.png', 'image/png')


def image_dims(raw, mime):
    """(largura, altura) de PNG/WebP simples, ou None se nao der pra ler."""
    try:
        if mime == 'image/png' and raw[:8] == b'\x89PNG\r\n\x1a\n':
            return struct.unpack('>II', raw[16:24])
        if mime == 'image/webp' and raw[:4] == b'RIFF' and raw[12:16] == b'VP8 ':
            return struct.unpack('<HH', raw[26:30])
        if mime == 'image/webp' and raw[12:16] == b'VP8L':
            bits = int.from_bytes(raw[21:25], 'little')
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    except Exception:
        pass
    return None


def pick_logo(current_bytes):
    dims = image_dims(current_bytes, 'image/png')
    if dims is None:
        return None
    width, height = dims
    return LOGO_SQUARE if width == height else LOGO_WORDMARK


def find_targets(manifest, template_html):
    """Descobre uuid -> (arquivo novo, mime novo) pelo alt no template.

    Compara bytes atuais do manifest contra o arquivo-fonte (nao um check de
    tamanho fixo): idempotente por natureza — se ja bate, sai sozinho da
    lista — e continua funcionando se o arquivo-fonte for atualizado de novo
    no futuro (ex.: correcao de um asset ja trocado antes).
    """
    targets = {}
    for uuid, alt in re.findall(r'<img[^>]*src="([0-9a-f-]{36})"[^>]*alt="([^"]*)"', template_html):
        current_bytes = base64.b64decode(manifest[uuid]['data'])
        candidate = SCREEN_BY_ALT.get(alt)
        if candidate is None and alt == LOGO_ALT:
            candidate = pick_logo(current_bytes)
        if candidate is None:
            continue
        rel_path, mime = candidate
        new_bytes = (ROOT / rel_path).read_bytes()
        if current_bytes != new_bytes:
            check_same_shape(uuid, rel_path, current_bytes, new_bytes, manifest[uuid]['mime'], mime)
            targets[uuid] = candidate
    return targets


def check_same_shape(uuid, rel_path, current_bytes, new_bytes, current_mime, new_mime):
    """Aborta se a substituicao mudaria drasticamente a proporcao da imagem.

    Rede de seguranca pro tipo de erro que ja aconteceu de verdade: trocar um
    wordmark 917x157 por um icone 96x96 nao gera erro nenhum — a pagina so fica
    visualmente errada, e ninguem percebe ate olhar. Proporcao e o sinal que
    distingue "atualizei o mesmo asset" de "coloquei o asset errado no slot".
    """
    old = image_dims(current_bytes, current_mime)
    new = image_dims(new_bytes, new_mime)
    if not old or not new:
        return
    old_ratio, new_ratio = old[0] / old[1], new[0] / new[1]
    if abs(old_ratio - new_ratio) / old_ratio > 0.10:
        raise SystemExit(
            f'{uuid[:8]}: {rel_path} tem proporcao {new[0]}x{new[1]} contra {old[0]}x{old[1]} '
            f'no slot atual — asset errado pra este uuid, nao vou sobrescrever'
        )


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


# ------------------------------------------------------------------ barreiras

def verify_head(name, text):
    """Vale pras tres paginas: o head estatico e o que crawler sem JS le."""
    head = head_of(text)
    for tag, pattern in (
        ('<title>', r'<title>'),
        ('meta description', r'<meta\s+name="description"'),
        ('canonical', r'<link\s+rel="canonical"'),
        ('og:title', r'property="og:title"'),
    ):
        n = len(re.findall(pattern, head))
        if n != 1:
            raise SystemExit(f'{name}: esperava exatamente 1 {tag} no head estatico, achei {n}')

    canonical = first_group(r'<link\s+rel="canonical"\s+href="([^"]*)"', head)
    if canonical != PAGES[name]['url']:
        raise SystemExit(f'{name}: canonical {canonical!r} != {PAGES[name]["url"]!r}')

    if re.search(r'<meta[^>]*name="robots"[^>]*noindex', head, re.I):
        raise SystemExit(f'{name}: head tem noindex — a pagina nao seria indexada')


def verify_bundle(name, text, template_before, keys_before):
    """Barreiras estruturais da Bundled Page. Falha aqui aborta antes de salvar."""
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


# --------------------------------------------------- sitemap / robots / pages

def git_lastmod(name):
    """Data do ultimo commit que tocou o arquivo (YYYY-MM-DD).

    Se o arquivo tem mudanca nao commitada, usa hoje: o proximo commit e hoje.
    Qualquer problema com o git cai em hoje tambem — um lastmod levemente
    otimista nao quebra nada, um sitemap ausente sim.
    """
    try:
        dirty = subprocess.run(
            ['git', 'status', '--porcelain', '--', name],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if dirty:
            return date.today().isoformat()
        out = subprocess.run(
            ['git', 'log', '-1', '--format=%cs', '--', name],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or date.today().isoformat()
    except Exception:
        return date.today().isoformat()


def write_if_changed(rel_path, content):
    """Escreve so se mudou, pra nao sujar o git diff a cada execucao."""
    path = ROOT / rel_path
    new = content.encode('utf-8')
    if path.exists() and path.read_bytes() == new:
        print(f'  {rel_path}: ja atualizado, pulando')
        return False
    path.write_bytes(new)
    print(f'  {rel_path}: escrito')
    return True


def write_sitemap():
    """sitemap.xml a partir do proprio PAGES — uma fonte de URLs so.

    Sem sitemap o Search Console reporta "Nenhum sitemap de referencia foi
    detectado" e a descoberta das paginas fica dependendo so de crawl.
    """
    urls = ''.join(
        f'  <url>\n'
        f'    <loc>{page["url"]}</loc>\n'
        f'    <lastmod>{git_lastmod(name)}</lastmod>\n'
        f'  </url>\n'
        for name, page in PAGES.items()
    )
    return write_if_changed(
        'sitemap.xml',
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{urls}'
        '</urlset>\n',
    )


def write_robots():
    """robots.txt e o unico jeito de o sitemap ser descoberto sem submissao
    manual no Search Console. Sem ele, um sitemap.xml na raiz e invisivel."""
    return write_if_changed(
        'robots.txt',
        'User-agent: *\n'
        'Allow: /\n'
        '\n'
        f'Sitemap: {BASE_URL}sitemap.xml\n',
    )


def write_nojekyll():
    """GitHub Pages roda Jekyll por padrao. Arquivo sem front matter passa
    intacto, entao hoje isso nao quebra nada — mas o index.html e cheio de
    `{{ t.chave }}`, que e exatamente a sintaxe do Liquid. Desligar o Jekyll
    tira esse risco de vez e acelera o build do Pages."""
    return write_if_changed('.nojekyll', '')


# ----------------------------------------------------------------------- main

def main():
    for name in PAGES:
        text = load_page(name)
        before = len(text)
        bundled = is_bundled(text)
        print(f'{name} ({"bundled" if bundled else "estatica"}):')

        template_before = keys_before = None
        if bundled:
            template_before = TEMPLATE_RE.search(text).group(2)
            keys_before = set(json.loads(MANIFEST_RE.search(text).group(2)))

        text = patch_lang(name, text)
        text = patch_head(name, text)
        if bundled:
            text = patch_watchdog(name, text)
            text = patch_assets(name, text)

        verify_head(name, text)
        if bundled:
            verify_bundle(name, text, template_before, keys_before)

        save_page(name, text)
        print('  {:,} -> {:,} bytes\n'.format(before, len(text)))

    print('arquivos de indexacao:')
    write_sitemap()
    write_robots()
    write_nojekyll()


if __name__ == '__main__':
    main()
