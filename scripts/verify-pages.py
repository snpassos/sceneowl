"""
Verificacao de runtime das 3 paginas da landing. As "Bundled Pages" montam
blob URLs no DOMContentLoaded, entao um mime errado no manifest so aparece
aqui, nao em nenhuma checagem estatica (essa fica em patch-bundle-assets.py).

Navega via file:// em vez de servir por HTTP: um servidor local (testado com
`python -m http.server`) se mostrou nao-confiavel neste ambiente para o
index.html (~1MB) — respostas vazias intermitentes sem relacao com o
conteudo da pagina. As "Bundled Pages" sao autocontidas por design (o loader
monta blobs a partir do manifest embutido, sem depender de rede), entao
file:// e equivalente para este proposito.

Requer Playwright para Python (`pip install playwright && playwright install
chromium`).

Uso: python scripts/verify-pages.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGES = ['index.html', 'privacy-policy.html', 'terms-of-service.html']

# As paginas tem badges Google Play / App Store cujo src e um placeholder de
# template ({{ t.googlePlayBadgeUrl }}) resolvido por um passo de i18n QUE
# RODA DEPOIS do unpack do bundler. O navegador tenta buscar a string crua
# como URL antes dessa resolucao, gera este erro de console, e a imagem se
# autocorrige em seguida — confirmado pre-existente comparando contra a
# versao do repo anterior a este patch (mesmo erro, mesmas 0 imagens
# quebradas). Nao e uma regressao deste script, entao nao deve reprovar a
# verificacao.
KNOWN_BENIGN_ERRORS = (
    'ERR_FILE_NOT_FOUND',
    'ERR_NAME_NOT_RESOLVED',
    'Failed to load resource: net::ERR_FILE_NOT_FOUND',
)


def is_known_benign(msg):
    return any(k in msg for k in KNOWN_BENIGN_ERRORS)


def main():
    failed = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name in PAGES:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(str(e)))

            page.goto((ROOT / name).as_uri(), wait_until='networkidle')
            page.wait_for_function(
                "() => [...document.images].length > 0 && [...document.images].every(i => i.complete)",
                timeout=15000,
            )

            broken = page.evaluate(
                "() => [...document.images].filter(i => i.naturalWidth === 0)"
                ".map(i => i.alt || i.src.slice(0, 40))"
            )
            sink = page.locator('#__bundler_err').count()
            title = page.title()
            real_errors = [e for e in errors if not is_known_benign(e)]

            ok = len(real_errors) == 0 and len(broken) == 0 and sink == 0
            if not ok:
                failed = True
            print(f'{"OK  " if ok else "FALHA"} {name} | title="{title}" | '
                  f'imgs quebradas: {len(broken)} | erros reais: {len(real_errors)} '
                  f'(benignos conhecidos ignorados: {len(errors) - len(real_errors)}) | '
                  f'sink #__bundler_err: {sink}')
            for e in real_errors:
                print('    console:', e)
            for b in broken:
                print('    img sem naturalWidth:', b)

            page.close()
        browser.close()

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
