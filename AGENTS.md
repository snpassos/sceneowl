# AGENTS.md — SceneOwl (site institucional e páginas legais)

Contexto de projeto para agentes de código (Claude Code, Codex e similares) trabalhando neste
repositório. Objetivo: menos exploração, menos idas e voltas, menos tokens gastos por tarefa.

## Sobre o projeto

Site público do SceneOwl — landing page + política de privacidade + termos de serviço.
Publicado em **https://sceneowl.com** por **GitHub Pages direto da branch `main`** do repo
`snpassos/sceneowl` (o `CNAME` na raiz aponta o domínio). **Não há workflow de build: o repo
já é o site**, então todo push na `main` é um deploy.

Ele não existe por vaidade — é requisito externo. A validação de **Branding do Google Play** e
a **OAuth consent screen do Google Cloud** exigem um site público que mostre a identidade do
app e hospede a política de privacidade. Boa parte do histórico do repo é reprovação nessa
validação e correção (ver `git log`: conteúdo que só aparecia via JS, título errado no head
estático, nome do app dividido em dois nós de texto).

O app em si vive no repo irmão **`sceneowl-app`** (`../sceneowl-app`, Expo/React Native), e o
painel admin local em **`sceneowl-ds`** (`../sceneowl-ds`).

## Estrutura

| Arquivo | O que é | Editável à mão? |
|---|---|---|
| `index.html` (~1,1 MB) | Landing page — uma **"Bundled Page"** gerada por ferramenta externa | **NÃO** |
| `privacy-policy.html` (~16 KB) | HTML estático comum | Sim |
| `terms-of-service.html` (~10 KB) | HTML estático comum | Sim |
| `assets/screens/*.webp` | Prints do app usados na landing | Gerados (ver abaixo) |
| `assets/logo-96.png`, `assets/wordmark.png` | Marca | Gerados (ver abaixo) |
| `favicon.png`, `apple-touch-icon.png`, `og-image.jpg` | Ícones e card social | Gerados |
| `scripts/patch-bundle-assets.py` | Único jeito seguro de editar `index.html`; também gera `sitemap.xml`/`robots.txt`/`.nojekyll` | Sim |
| `scripts/verify-pages.py` | Verificação de runtime das 3 páginas (Playwright) | Sim |
| `sitemap.xml`, `robots.txt`, `.nojekyll` | Indexação — **gerados**, não editar à mão | Não |
| `.gitattributes` | `* -text`: desliga conversão de fim de linha (ver Armadilhas) | Sim |

Sem `package.json`, sem `node_modules`, sem framework, sem passo de build. Os únicos scripts
são Python.

## A regra que mais importa: `index.html` não se edita à mão

`index.html` é uma **Bundled Page**: um arquivo autocontido com três partes —

1. um `<head>` **estático** (o único que um crawler sem JS enxerga, e o único que vale antes
   do unpack);
2. `<script type="__bundler/manifest">` — um JSON com **todos os assets em base64**;
3. `<script type="__bundler/template">` — um JSON com o **HTML real da página**;

...mais um loader marcado `GENERATED ... do not edit`, que no `DOMContentLoaded` monta blob
URLs a partir do manifest e injeta o template. Nós não controlamos o loader.

Consequências práticas:

- Uma linha desse arquivo tem centenas de KB. Ler/editar por linha não funciona, e um erro de
  escape no JSON quebra a página inteira em silêncio.
- **Toda alteração passa por `scripts/patch-bundle-assets.py`**, que é ancorado por marcador
  (regex sobre `__bundler/manifest` / `__bundler/template` e sobre o `alt` das imagens), nunca
  por offset, e é **idempotente** — rodar duas vezes não duplica tag nem re-substitui asset.
- O script lê/escreve **bytes**, nunca `read_text`/`write_text`: no Windows a tradução de fim
  de linha reescreveria o arquivo inteiro e o diff viria com ~1 MB alterado em vez das poucas
  linhas do head.
- Antes de salvar, `verify()` roda 6 barreiras estruturais (manifest e template reparseáveis,
  template byte-idêntico, conjunto de uuids inalterado, nenhum uuid órfão, assinatura binária
  batendo com o mime). Qualquer falha aborta **antes** de gravar. Não afrouxar essas barreiras
  pra fazer uma mudança passar.

### O script trata os dois tipos de página

Nem todas as páginas são bundled: `privacy-policy.html` e `terms-of-service.html` voltaram a
ser **HTML estático comum** no commit `ec7909a`. O script detecta o tipo por página (presença
do `__bundler/manifest`) em vez de assumir — antes ele tratava as três como bundled e abortava
com `AttributeError` na primeira página legal, **depois de já ter salvado o `index.html`**.

Para página estática ele só completa o `<head>`; watchdog e troca de asset são exclusivos das
bundled. O preenchimento do head é **tag a tag** (não um bloco tudo-ou-nada): título e
descrição que a página já declara ganham dos valores em `PAGES`, que são só fallback.

## Fluxos comuns

### Trocar um print / a logo da landing

1. No repo `sceneowl-app`: `npm run generate-landing-assets` → gera em `docs/landing-assets/`
   (a partir de `assets/images/logo.png` e dos screenshots en-US da Play Store, reusando o
   pipeline de marca de `scripts/generate-brand-icons.js`).
2. Copiar a saída para a raiz **deste** repo (`assets/…`).
3. `python scripts/patch-bundle-assets.py` — ele descobre o uuid de cada imagem pelo `alt` no
   template (`SCREEN_BY_ALT` / `LOGO_ALT`), compara os bytes atuais com o arquivo-fonte e só
   troca o que mudou. Nunca hardcodar uuid: a página pode ser regerada e a quebra seria
   silenciosa.
4. `python scripts/verify-pages.py`.

### Mudar o texto legal (política / termos)

**A fonte da verdade é o app, não este repo.** O texto vive em
`sceneowl-app/src/locales/{pt-BR,en-US}.ts` (chaves `legal.privacy` / `legal.terms`) e foi
copiado à mão pra cá porque estas páginas são HTML estático e o app é TypeScript — há um
comentário no topo de `privacy-policy.html` dizendo exatamente isso. **Editar nos dois lugares
ou eles divergem.** Mudança de coleta de dados (ex.: a entrada do Sentry, commit `b40b674`)
precisa refletir aqui também.

### Verificar antes de dar push

```bash
python scripts/verify-pages.py    # requer: pip install playwright && playwright install chromium
```

Ele abre as 3 páginas com Playwright, espera `networkidle` + todas as imagens completas, e
reprova se houver erro de console real, imagem com `naturalWidth === 0`, ou conteúdo no sink
`#__bundler_err`. Navega por **`file://` de propósito**: servir por HTTP local se mostrou
não-confiável neste ambiente para um `index.html` de ~1 MB (respostas vazias intermitentes), e
a Bundled Page é autocontida por design. Há uma allowlist de erros benignos conhecidos
(`KNOWN_BENIGN_ERRORS`) — badges de loja cujo `src` é um placeholder `{{ t.… }}` resolvido
depois do unpack; isso é pré-existente e não é regressão.

## Indexação no Google (sitemap / robots)

Search Console reportava **"Nenhum sitemap de referência foi detectado"**: o repo simplesmente
não tinha `sitemap.xml` nem `robots.txt` — ambos davam 404 em produção (confirmado em
2026-09-09). Agora os dois são **gerados por `patch-bundle-assets.py`** a partir do mesmo dict
`PAGES`, então a lista de URLs tem uma fonte só:

- `sitemap.xml` — as 3 URLs com `lastmod` vindo da data do último commit que tocou cada arquivo
  (ou hoje, se o arquivo tem mudança não commitada).
- `robots.txt` — `Allow: /` mais a linha `Sitemap:`. **É o único mecanismo de descoberta
  automática do sitemap**: um `sitemap.xml` na raiz sem essa linha é invisível pro Google.
- `.nojekyll` — GitHub Pages roda Jekyll por padrão. Arquivo sem front matter passa intacto,
  então hoje não quebra nada, mas o `index.html` é cheio de `{{ t.chave }}`, que é exatamente
  a sintaxe do Liquid. Desligar o Jekyll tira o risco e acelera o build do Pages.

O resto do checklist de indexação **já estava certo** e não precisa de ação: `canonical` nas 3
páginas, conteúdo estático real no `<body>` pra crawler sem JS, links internos da home para as
páginas legais, e nenhum `noindex` (o `verify_head()` do script barra os três casos). O
`lang` no `<html>` estático foi adicionado — faltava no `index.html`.

Depois do push, o sitemap ainda precisa ser **enviado uma vez no Search Console**
(Sitemaps → `https://sceneowl.com/sitemap.xml`); o `robots.txt` cobre as descobertas seguintes.

## Armadilhas já pagas (não redescobrir)

- **Dois assets diferentes têm `alt="SceneOwl"`** no template: o ícone quadrado 96×96
  (`assets/logo-96.png`) e a marca bicolor 917×157 (`assets/wordmark.png`, colocada pelo commit
  `2bfc9e3`). O `LOGO_FILE` antigo mapeava os dois para o ícone, então rodar o script
  **sobrescrevia o wordmark com o ícone quadrado e revertia o `2bfc9e3` em silêncio** — sem
  erro, só a página visualmente errada. Hoje o desempate é a forma da imagem que já está no
  slot (quadrada = ícone, larga = wordmark), e `check_same_shape()` aborta se uma substituição
  mudaria a proporção em mais de 10%.
- **CRLF destrói este repo.** Com `core.autocrlf=true` (padrão em muitas máquinas Windows), um
  `git checkout` reescreve toda quebra de linha: os marcadores do script deixam de casar (o
  watchdog dá erro) e qualquer commit vira um diff do arquivo inteiro. Já aconteceu com
  `index.html` e com `terms-of-service.html`. O `.gitattributes` (`* -text`) impede a
  recorrência, `load_page()` aborta com instrução de reparo se ainda encontrar CRLF, e a
  restauração byte a byte é
  `python -c "import subprocess;open('X','wb').write(subprocess.run(['git','show','HEAD:X'],capture_output=True).stdout)"`
  — **não** `git checkout X`, que reintroduz o problema.

- **Página em branco no primeiro load (Firefox, não reproduzível depois).** Causa reproduzida:
  o loader gerado só descomprime os blobs de runtime/React/ReactDOM se `DecompressionStream`
  existir; se não existir ou falhar, cai num `catch` **sem fallback** e esses três scripts
  nunca rodam — mas o resto do unpack (só `atob()`) segue normal. Resultado: o corpo fica com
  os placeholders literais `{{ t.chave }}` em vez de texto, **não fica vazio** — um limiar por
  tamanho de texto nunca dispararia. Por isso existe o **watchdog** injetado no head pelo
  script: 12s depois do load, se `document.body.innerText` ainda contiver `{{ t.`, recarrega
  **uma vez** (guardado por `sessionStorage`, pra nunca virar loop). O `patch_watchdog()`
  substitui o bloco existente em vez de só pular, então corrigir a lógica e rodar de novo
  propaga a correção.
- **Reprovação de Branding do Google:** conteúdo que só existe depois do JS não conta. O
  `<head>` estático precisa carregar título, `description`, `og:*` e o nome do app; e o nome
  "SceneOwl" precisa ser **um único nó de texto** no DOM renderizado (commit `8bec90e`) — não
  dividido em dois `<span>`, mesmo que o wordmark seja bicolor.
- **Flashes visuais** (fallback, back-navigation, `{{ t.x }}` no primeiro paint) já foram
  corrigidos — ver `c6f2ffc`, `b07ebb4`, `d146be4`. Mexer no head estático pode reintroduzi-los.
- As 3 páginas precisam de **`canonical`** (`5d84be8`) e do mesmo idioma entre si (`d146be4`).

## Como trabalhar neste repo

- Uma mudança por vez; `index.html` só via script.
- Depois de qualquer patch: rodar `verify-pages.py` e conferir que o `git diff` tocou **poucas
  linhas** — diff do arquivo inteiro significa que a tradução de fim de linha aconteceu e a
  mudança deve ser descartada.
- Explicar o conceito/abordagem em texto antes de aplicar código quando a mudança não for
  trivial (o dono do projeto vem de infra/SRE, não de frontend).

## Fora de escopo

- Não introduzir build step, bundler, framework ou `node_modules` — o repo é servido cru pelo
  GitHub Pages e a simplicidade é o que sobrevive à validação do Google.
- Não regerar `index.html` pela ferramenta original sem alinhar antes: todas as correções de
  head, watchdog e assets deste repo seriam perdidas.
- Nenhum secret aqui — o site é 100% público e estático.
