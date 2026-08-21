#!/usr/bin/env python3
"""Extrai as areas de midia de um site que ja existe (nao de um canvas do /design).

Uso:
    python ferramentas/ler_site.py <pasta-do-projeto | arquivo>
    python ferramentas/ler_site.py --url http://localhost:3000
    python ferramentas/ler_site.py . --json briefing_site.json --plano midias.json

Serve para o caso "meu site esta rodando e quero gerar imagem/video para as areas dele".
Para cada slot de midia devolve: dimensao de exibicao, se o arquivo apontado existe,
a copy vizinha (o texto do card, que e o que ancora o prompt) e os design tokens do CSS.

Le .html, .jsx/.tsx, .vue, .svelte, .astro, .php e background-image de .css/.scss.
Nao depende de biblioteca externa. A leitura e defensiva: em arquivo de framework a
marcacao nao e HTML valido, entao a extracao cai para varredura por expressao regular.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from html.parser import HTMLParser

# a copy do site vem acentuada; sem isto o console do Windows quebra os acentos
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ------------------------------------------------------------------ padroes

HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
CSS_VAR = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+)")
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
GOOGLE_FONT = re.compile(r"family=([^&\"']+)")
SIZE_IN_STYLE = re.compile(r"(?<![\w-])(width|height|aspect-ratio)\s*:\s*([^;]+)", re.I)
PX = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*px\s*$", re.I)
NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")
RAZAO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[/:]\s*(\d+(?:\.\d+)?)\s*$")

# tags de midia em arquivo de framework (JSX, Vue, Svelte, Astro, PHP)
TAG_MIDIA = re.compile(
    r"<\s*(img|video|source|Image|NuxtImg|picture)\b([^>]*?)/?>", re.I)
ATRIBUTO = re.compile(r"([\w:@\-\.]+)\s*=\s*(\"[^\"]*\"|'[^']*'|\{[^}]*\})")
CSS_BG = re.compile(
    r"([^{}]+)\{([^{}]*background(?:-image)?\s*:[^;}]*url\(\s*['\"]?([^'\")]+)['\"]?\s*\)[^}]*)\}",
    re.I)
TAG_QUALQUER = re.compile(r"<[^>]+>")
CHAVES_JSX = re.compile(r"\{[^{}]*\}")

EXT_MARCACAO = (".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".php")
EXT_ESTILO = (".css", ".scss", ".sass", ".less")
EXT_IMAGEM = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")
EXT_VIDEO = (".mp4", ".webm", ".mov", ".m4v")
IGNORAR = (".git", "node_modules", "dist", "build", ".next", ".nuxt", ".svelte-kit",
           "vendor", "coverage", "__pycache__")

CABECALHOS = ("h1", "h2", "h3", "h4")
TEXTO_UTIL = CABECALHOS + ("p", "li", "figcaption", "blockquote", "span", "strong")


def kebab(texto, padrao="midia"):
    s = re.sub(r"[^\w\s-]", "", (texto or "").strip().lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return (s[:40].strip("-") or padrao)


def px(valor):
    """'320px' | '320' -> 320. Porcentagem, vw, calc() e afins viram None."""
    if not valor:
        return None
    for padrao in (PX, NUM):
        m = padrao.match(str(valor))
        if m:
            return int(round(float(m.group(1))))
    return None


def razao_de(largura, altura, texto_aspect=None):
    if texto_aspect:
        m = RAZAO.match(texto_aspect)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if b:
                return normalizar_razao(a, b)
    if largura and altura:
        return normalizar_razao(largura, altura)
    return None


def normalizar_razao(a, b):
    conhecidas = {"16:9": 16 / 9, "4:3": 4 / 3, "3:2": 3 / 2, "1:1": 1.0,
                  "4:5": 0.8, "2:3": 2 / 3, "9:16": 9 / 16, "21:9": 21 / 9,
                  "3:4": 0.75, "5:4": 1.25}
    alvo = a / b
    nome, dist = min(((n, abs(v - alvo)) for n, v in conhecidas.items()),
                     key=lambda t: t[1])
    return nome if dist < 0.04 else "%.3f:1" % alvo


# ------------------------------------------------------------------ indice de CSS

class IndiceCSS(object):
    """Dimensoes declaradas no CSS, por seletor simples (.classe / #id)."""

    def __init__(self):
        self.regras = {}          # ".hero-media" -> {"width": "...", "aspect-ratio": "..."}
        self.variaveis = {}
        self.cores = Counter()
        self.fontes = Counter()
        self.backgrounds = []     # slots vindos de background-image

    def alimentar(self, css, arquivo="<inline>"):
        self.cores.update(c.lower() for c in HEX_COLOR.findall(css))
        self.variaveis.update({n: v.strip() for n, v in CSS_VAR.findall(css)})
        self.fontes.update(f.strip() for f in FONT_FAMILY.findall(css))

        for bloco in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            seletores, corpo = bloco.group(1), bloco.group(2)
            dims = {p.lower(): v.strip() for p, v in SIZE_IN_STYLE.findall(corpo)}
            if not dims:
                continue
            for sel in seletores.split(","):
                sel = sel.strip()
                # so o ultimo token simples interessa: ".card .media" -> ".media"
                alvo = sel.split()[-1] if sel.split() else sel
                alvo = re.sub(r"::?[\w-]+(\([^)]*\))?$", "", alvo)
                if alvo.startswith((".", "#")) and re.match(r"^[.#][\w-]+$", alvo):
                    self.regras.setdefault(alvo, {}).update(dims)

        for m in CSS_BG.finditer(css):
            seletor, corpo, url = m.group(1).strip(), m.group(2), m.group(3)
            dims = {p.lower(): v.strip() for p, v in SIZE_IN_STYLE.findall(corpo)}
            self.backgrounds.append({"seletor": seletor, "url": url,
                                     "dimensoes": dims, "arquivo": arquivo})

    def dimensoes_de(self, classes, ident):
        for chave in (["#" + ident] if ident else []) + \
                     ["." + c for c in (classes or "").split() if c]:
            if chave in self.regras:
                return self.regras[chave], "css:%s" % chave
        return {}, None


# ------------------------------------------------------------------ leitura de HTML

class LeitorHTML(HTMLParser):
    """Coleta midias e a copy vizinha preservando a ordem de leitura da pagina."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.fluxo = []           # ("midia", dict) | ("texto", tag, texto) | ("secao", nome)
        self.css = []
        self.google_fonts = []
        self._em_style = False
        self._texto_atual = None
        self._secao = None

    @staticmethod
    def _attrs(attrs):
        return {k.lower(): (v or "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        a = self._attrs(attrs)

        if tag == "style":
            self._em_style = True
            return
        if tag == "link" and "fonts.googleapis.com" in a.get("href", ""):
            self.google_fonts.extend(f.replace("+", " ") for f in GOOGLE_FONT.findall(a["href"]))
            return
        if a.get("style"):
            self.css.append("x{%s}" % a["style"])

        if tag in ("section", "main", "article", "header", "footer"):
            nome = a.get("id") or a.get("class", "").split(" ")[0] or tag
            self._secao = nome
            self.fluxo.append(("secao", nome))

        if tag in ("img", "video", "source"):
            self.fluxo.append(("midia", {
                "tag": tag,
                "src": a.get("src") or a.get("poster") or a.get("srcset", "").split(" ")[0],
                "poster": a.get("poster", ""),
                "alt": a.get("alt", ""),
                "classes": a.get("class", ""),
                "id": a.get("id", ""),
                "attr_largura": a.get("width", ""),
                "attr_altura": a.get("height", ""),
                "style": a.get("style", ""),
                "secao": self._secao,
                "linha": self.getpos()[0],
            }))

        if tag in TEXTO_UTIL:
            self._texto_atual = tag

    def handle_endtag(self, tag):
        if tag == "style":
            self._em_style = False
        if tag in TEXTO_UTIL:
            self._texto_atual = None

    def handle_data(self, data):
        if self._em_style:
            self.css.append(data)
        elif self._texto_atual:
            texto = " ".join(data.split())
            if len(texto) > 1:
                self.fluxo.append(("texto", self._texto_atual, texto[:180]))


def copy_vizinha(fluxo, posicao):
    """Titulo mais proximo antes do slot + textos ate a proxima midia."""
    antes = []
    for tipo, *resto in reversed(fluxo[:posicao]):
        if tipo == "midia":
            break
        if tipo == "texto" and resto[0] in CABECALHOS:
            antes.append(resto[1])
            break
    depois = []
    for tipo, *resto in fluxo[posicao + 1:]:
        if tipo == "midia" or len(depois) >= 4:
            break
        if tipo == "texto":
            depois.append(resto[1])
    # titulo de secao anterior, para dar contexto de bloco
    secao = None
    for tipo, *resto in reversed(fluxo[:posicao]):
        if tipo == "secao":
            secao = resto[0]
            break
    return list(OrderedDict.fromkeys(antes + depois)), secao


# ------------------------------------------------------------------ leitura de framework

def ler_framework(bruto, arquivo):
    """Varredura por regex para JSX/Vue/Svelte/Astro/PHP, onde o HTML nao e valido."""
    achados = []
    for m in TAG_MIDIA.finditer(bruto):
        tag, cru = m.group(1), m.group(2)
        a = {}
        for chave, valor in ATRIBUTO.findall(cru):
            a[chave.lower().lstrip(":@")] = valor.strip("\"'")
        src = a.get("src") or a.get("poster") or ""
        dinamico = src.startswith("{") or src.startswith("$") or "{" in src

        # a janela de copy para na proxima midia: sem isso o texto do card seguinte
        # vaza para dentro deste slot e contamina o prompt
        janela = bruto[m.end():m.end() + 900]
        proxima = TAG_MIDIA.search(janela)
        if proxima:
            janela = janela[:proxima.start()]
        texto = TAG_QUALQUER.sub("\n", CHAVES_JSX.sub(" ", janela))
        copy = [t.strip() for t in re.split(r"[\n\r]+", texto) if len(t.strip()) > 3][:4]

        achados.append({
            "tag": tag.lower(),
            "src": "" if dinamico else src,
            "src_dinamico": dinamico,
            "expressao_src": src if dinamico else "",
            "poster": a.get("poster", ""),
            "alt": a.get("alt", ""),
            "classes": a.get("class") or a.get("classname", ""),
            "id": a.get("id", ""),
            "attr_largura": a.get("width", ""),
            "attr_altura": a.get("height", ""),
            "style": a.get("style", ""),
            "secao": None,
            "linha": bruto.count("\n", 0, m.start()) + 1,
            "copy": copy,
        })
    return achados


# ------------------------------------------------------------------ montagem dos slots

def resolver_dimensoes(m, indice):
    largura = px(m.get("attr_largura"))
    altura = px(m.get("attr_altura"))
    origem = "atributo" if (largura or altura) else None
    aspecto = None

    estilo = {p.lower(): v.strip() for p, v in SIZE_IN_STYLE.findall(m.get("style", ""))}
    if not largura and px(estilo.get("width")):
        largura, origem = px(estilo["width"]), origem or "style"
    if not altura and px(estilo.get("height")):
        altura, origem = px(estilo["height"]), origem or "style"
    aspecto = estilo.get("aspect-ratio") or aspecto

    if not (largura and altura):
        css_dims, de_onde = indice.dimensoes_de(m.get("classes"), m.get("id"))
        if css_dims:
            achou = False
            if not largura and px(css_dims.get("width")):
                largura, achou = px(css_dims["width"]), True
            if not altura and px(css_dims.get("height")):
                altura, achou = px(css_dims["height"]), True
            if not aspecto and css_dims.get("aspect-ratio"):
                aspecto, achou = css_dims["aspect-ratio"], True
            if achou:
                origem = origem or de_onde

    razao = razao_de(largura, altura, aspecto)
    if largura and not altura and razao and ":" in razao:
        a, b = razao.split(":")
        altura = int(round(largura * float(b) / float(a)))
        origem = (origem or "") + "+aspect-ratio"
    return largura, altura, razao, (origem or "desconhecida")


def caminho_local(src, arquivo, raiz):
    """Traduz o src para um caminho em disco, quando for asset local."""
    if not src or src.startswith(("http://", "https://", "//", "data:", "blob:")):
        return None
    limpo = src.split("?")[0].split("#")[0]
    candidatos = []
    if limpo.startswith("/"):
        for pasta in ("", "public", "static", "assets", "dist", "src"):
            candidatos.append(os.path.join(raiz, pasta, limpo.lstrip("/")))
    else:
        candidatos.append(os.path.join(os.path.dirname(arquivo), limpo))
        candidatos.append(os.path.join(raiz, limpo))
    for c in candidatos:
        if os.path.exists(c):
            return os.path.normpath(c)
    return os.path.normpath(candidatos[0])


def tipo_de(m):
    src = (m.get("src") or "").lower()
    if m.get("tag") == "video" or src.endswith(EXT_VIDEO):
        return "video"
    return "imagem"


def montar_slot(m, arquivo, raiz, indice, usados):
    largura, altura, razao, origem_dim = resolver_dimensoes(m, indice)
    src = m.get("src", "")
    destino = caminho_local(src, arquivo, raiz)
    existe = os.path.exists(destino) if destino else None

    # o nome do arquivo vem antes do alt: gera id curto e casa com o asset que ja existe
    semente = (m.get("id") or
               (os.path.splitext(os.path.basename(src.split("?")[0]))[0] if src else "") or
               (m.get("classes") or "").split(" ")[0] or
               (m.get("secao") or "") or
               " ".join((m.get("alt") or "").split()[:4]) or
               m.get("tag"))
    ident = kebab(semente)
    n = 2
    while ident in usados:
        ident = "%s-%d" % (kebab(semente), n)
        n += 1
    usados.add(ident)

    return {
        "id": ident,
        "tipo": tipo_de(m),
        "arquivo": os.path.relpath(arquivo, raiz).replace("\\", "/"),
        "linha": m.get("linha"),
        "tag": m.get("tag"),
        "secao": m.get("secao"),
        "src": src or m.get("expressao_src", ""),
        "src_dinamico": bool(m.get("src_dinamico")),
        "arquivo_existe": existe,
        "caminho_local": (os.path.relpath(destino, raiz).replace("\\", "/")
                          if destino else None),
        "alt": m.get("alt", ""),
        "largura": largura,
        "altura": altura,
        "aspect_ratio": razao,
        "origem_dimensao": origem_dim,
        "copy": m.get("copy", []),
    }


def analisar_projeto(raiz, arquivos):
    indice = IndiceCSS()
    for caminho in arquivos:
        if caminho.lower().endswith(EXT_ESTILO):
            with open(caminho, "r", encoding="utf-8", errors="replace") as f:
                indice.alimentar(f.read(), os.path.relpath(caminho, raiz).replace("\\", "/"))

    slots, usados, google_fonts = [], set(), []
    for caminho in arquivos:
        if caminho.lower().endswith(EXT_ESTILO):
            continue
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            bruto = f.read()

        if caminho.lower().endswith((".html", ".htm")):
            leitor = LeitorHTML()
            try:
                leitor.feed(bruto)
            except Exception as e:
                # marcacao quebrada nao pode sumir em silencio: o que veio antes do
                # erro fica, mas o usuario precisa saber que o arquivo foi truncado
                sys.stderr.write("aviso: %s parou no parsing (%s: %s). "
                                 "Slots depois desse ponto nao foram lidos.\n"
                                 % (os.path.relpath(caminho, raiz), type(e).__name__, e))
            indice.alimentar("\n".join(leitor.css), os.path.relpath(caminho, raiz))
            google_fonts.extend(leitor.google_fonts)
            for i, (tipo, *resto) in enumerate(leitor.fluxo):
                if tipo != "midia":
                    continue
                m = resto[0]
                m["copy"], secao = copy_vizinha(leitor.fluxo, i)
                m["secao"] = m.get("secao") or secao
                slots.append(montar_slot(m, caminho, raiz, indice, usados))
        else:
            indice.alimentar(bruto, os.path.relpath(caminho, raiz))
            for m in ler_framework(bruto, caminho):
                slots.append(montar_slot(m, caminho, raiz, indice, usados))

    for bg in indice.backgrounds:
        destino = caminho_local(bg["url"], os.path.join(raiz, bg["arquivo"]), raiz)
        ident = kebab(bg["seletor"] or os.path.basename(bg["url"]))
        n = 2
        while ident in usados:
            ident, n = "%s-%d" % (kebab(bg["seletor"]), n), n + 1
        usados.add(ident)
        largura = px(bg["dimensoes"].get("width"))
        altura = px(bg["dimensoes"].get("height"))
        slots.append({
            "id": ident, "tipo": "imagem", "arquivo": bg["arquivo"], "linha": None,
            "tag": "css-background", "secao": bg["seletor"], "src": bg["url"],
            "src_dinamico": False,
            "arquivo_existe": os.path.exists(destino) if destino else None,
            "caminho_local": (os.path.relpath(destino, raiz).replace("\\", "/")
                              if destino else None),
            "alt": "", "largura": largura, "altura": altura,
            "aspect_ratio": razao_de(largura, altura, bg["dimensoes"].get("aspect-ratio")),
            "origem_dimensao": "css:%s" % bg["seletor"], "copy": [],
        })

    return {
        "raiz": raiz,
        "arquivos_lidos": [os.path.relpath(a, raiz).replace("\\", "/") for a in arquivos],
        "slots": slots,
        "google_fonts": sorted(set(google_fonts)),
        "tokens": indice.variaveis,
        "paleta": [{"cor": c, "ocorrencias": n} for c, n in indice.cores.most_common(16)],
        "fontes": [f for f, _ in indice.fontes.most_common(8)],
    }


# ------------------------------------------------------------------ entradas

def coletar_arquivos(alvo):
    if os.path.isfile(alvo):
        return os.path.dirname(os.path.abspath(alvo)) or ".", [os.path.abspath(alvo)]
    if not os.path.isdir(alvo):
        sys.exit("Erro: '%s' nao encontrado." % alvo)
    raiz = os.path.abspath(alvo)
    achados = []
    for pasta, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s not in IGNORAR and not s.startswith(".")]
        for nome in sorted(arquivos):
            baixo = nome.lower()
            # .dc.html e canvas do /design (use ler_design.py) e o inventario e
            # artefato das ferramentas - nenhum dos dois e uma pagina do site
            if baixo.endswith(".dc.html") or baixo.startswith("inventario_midias"):
                continue
            if baixo.endswith(EXT_MARCACAO + EXT_ESTILO):
                achados.append(os.path.join(pasta, nome))
    if not achados:
        sys.exit("Erro: nenhum arquivo de marcacao ou estilo em '%s'." % alvo)
    return raiz, achados


def baixar(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "design-to-mcp/ler_site"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def analisar_url(urls, raiz):
    indice = IndiceCSS()
    slots, usados, fontes, cascas = [], set(), [], []
    for url in urls:
        try:
            html = baixar(url)
        except Exception as e:
            sys.exit("Erro ao buscar %s: %s" % (url, e))
        leitor = LeitorHTML()
        try:
            leitor.feed(html)
        except Exception as e:
            sys.stderr.write("aviso: %s parou no parsing (%s: %s).\n"
                             % (url, type(e).__name__, e))
        indice.alimentar("\n".join(leitor.css), url)
        fontes.extend(leitor.google_fonts)
        antes = len(slots)
        for i, (tipo, *resto) in enumerate(leitor.fluxo):
            if tipo != "midia":
                continue
            m = resto[0]
            m["copy"], secao = copy_vizinha(leitor.fluxo, i)
            m["secao"] = m.get("secao") or secao
            slot = montar_slot(m, os.path.join(raiz, "url.html"), raiz, indice, usados)
            slot["arquivo"] = url
            slots.append(slot)
        if len(slots) == antes and re.search(r'<div id="(root|app|__next)"', html):
            cascas.append(url)
    return {
        "raiz": raiz, "slots": slots, "google_fonts": sorted(set(fontes)),
        "tokens": indice.variaveis,
        "paleta": [{"cor": c, "ocorrencias": n} for c, n in indice.cores.most_common(16)],
        "fontes": [f for f, _ in indice.fontes.most_common(8)],
        "cascas_vazias": cascas,
    }


# ------------------------------------------------------------------ saidas

def imprimir(rel, so_faltando):
    slots = rel["slots"]
    if so_faltando:
        slots = [s for s in slots if s["arquivo_existe"] is False or s["src_dinamico"]]

    print("\n" + "=" * 72)
    print("SLOTS DE MIDIA (%d%s)" % (len(slots), " sem arquivo" if so_faltando else ""))
    if rel.get("arquivos_lidos"):
        print("lidos: %s" % ", ".join(rel["arquivos_lidos"][:8]) +
              (" (+%d)" % (len(rel["arquivos_lidos"]) - 8)
               if len(rel["arquivos_lidos"]) > 8 else ""))
    print("=" * 72)
    for i, s in enumerate(slots, 1):
        dim = ("%sx%s" % (s["largura"], s["altura"])
               if s["largura"] and s["altura"] else "dimensao nao declarada")
        estado = {True: "ok", False: "ARQUIVO NAO EXISTE", None: "externo/dinamico"}[s["arquivo_existe"]]
        print("\n  %2d. %-22s %-8s %s  [%s]" % (i, s["id"], s["tipo"], dim, estado))
        print("      %s:%s  <%s>" % (s["arquivo"], s["linha"] or "?", s["tag"]))
        if s["src"]:
            print("      src: %s%s" % (s["src"], "  (expressao dinamica)" if s["src_dinamico"] else ""))
        if s["aspect_ratio"]:
            print("      razao: %s  (dimensao via %s)" % (s["aspect_ratio"], s["origem_dimensao"]))
        if s["alt"]:
            print("      alt atual: %s" % s["alt"])
        if s["copy"]:
            print("      copy do bloco:")
            for t in s["copy"]:
                print("        - %s" % t)

    if rel.get("cascas_vazias"):
        print("\n  AVISO: %s devolveu uma casca vazia (SPA renderizada no cliente)."
              % ", ".join(rel["cascas_vazias"]))
        print("         Rode o extractor na pasta do projeto, ou capture o DOM ja renderizado")
        print("         pelo navegador e salve num .html antes de ler.")

    if rel["tokens"]:
        print("\n-- Design tokens (levam a grade de cor do prompt) --")
        for nome, valor in list(rel["tokens"].items())[:24]:
            print("   %s: %s" % (nome, valor))
    if rel["paleta"]:
        print("\n-- Paleta por frequencia --")
        print("   " + "  ".join("%s(%dx)" % (c["cor"], c["ocorrencias"]) for c in rel["paleta"][:10]))
    if rel["google_fonts"]:
        print("\n-- Google Fonts --\n   " + ", ".join(rel["google_fonts"]))

    faltando = [s for s in rel["slots"] if s["arquivo_existe"] is False]
    print("\n" + "=" * 72)
    print("TOTAL: %d slot(s); %d sem arquivo em disco; %d sem dimensao declarada."
          % (len(rel["slots"]), len(faltando),
             sum(1 for s in rel["slots"] if not (s["largura"] and s["altura"]))))
    print("=" * 72)


def pasta_de_saida(rel):
    """Onde os assets do projeto ja moram - e para la que os novos devem ir."""
    pastas = Counter(os.path.dirname(s["caminho_local"])
                     for s in rel["slots"]
                     if s.get("caminho_local") and s.get("arquivo_existe"))
    if pastas:
        return pastas.most_common(1)[0][0].replace("\\", "/")
    for candidata in ("public/assets", "public/img", "public/images", "static/img",
                      "assets/img", "public", "static", "assets"):
        if os.path.isdir(os.path.join(rel["raiz"], candidata)):
            return candidata
    return "public/assets"


def esqueleto_plano(rel, slots, destino):
    itens = []
    for s in slots:
        item = OrderedDict()
        item["id"] = s["id"]
        item["tipo"] = s["tipo"]
        item["largura"] = s["largura"] or 1024
        item["altura"] = s["altura"] or 1024
        if s["aspect_ratio"]:
            item["aspect_ratio"] = s["aspect_ratio"]
        if s["tipo"] == "video":
            item["duracao_s"] = 4
            item["resolucao"] = "720p"
        contexto = " | ".join(s["copy"][:3]) if s["copy"] else "sem copy detectada"
        item["nota"] = "%s:%s  %s" % (s["arquivo"], s["linha"] or "?", contexto)
        if s["tipo"] == "video":
            item["nota"] += "  [4s em 720p: 1080p no Veo exige 8s]"
        item["prompt"] = ""
        item["aceite"] = ""
        if not (s["largura"] and s["altura"]):
            item["revisar"] = "dimensao nao declarada no site - confirme antes de gerar"
        itens.append(item)

    plano = OrderedDict()
    plano["provedor"] = "google-midia"
    plano["saida"] = pasta_de_saida(rel)
    plano["inventario"] = "inventario_midias.html"
    plano["referencias"] = []
    plano["itens"] = itens
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(plano, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return len(itens)


def main():
    ap = argparse.ArgumentParser(
        description="Extrai as areas de midia de um site existente.")
    ap.add_argument("alvo", nargs="?", default=".", help="pasta do projeto ou arquivo")
    ap.add_argument("--url", action="append",
                    help="le do servidor rodando (pode repetir para varias rotas)")
    ap.add_argument("--json", dest="saida_json", help="grava o briefing estruturado")
    ap.add_argument("--plano", help="grava um esqueleto de midias.json com os slots")
    ap.add_argument("--so-faltando", action="store_true",
                    help="so os slots cujo arquivo nao existe ou cujo src e dinamico")
    ap.add_argument("--forcar", action="store_true", help="sobrescreve o --plano existente")
    args = ap.parse_args()

    if args.url:
        raiz = os.path.abspath(args.alvo if os.path.isdir(args.alvo) else ".")
        rel = analisar_url(args.url, raiz)
    else:
        raiz, arquivos = coletar_arquivos(args.alvo)
        rel = analisar_projeto(raiz, arquivos)

    imprimir(rel, args.so_faltando)

    if args.saida_json:
        with open(args.saida_json, "w", encoding="utf-8") as f:
            json.dump(rel, f, ensure_ascii=False, indent=2)
        print("Briefing estruturado gravado em %s" % args.saida_json)

    if args.plano:
        if os.path.exists(args.plano) and not args.forcar:
            print("AVISO: '%s' ja existe. Nada foi escrito - use --forcar para sobrescrever."
                  % args.plano)
        else:
            escolhidos = [s for s in rel["slots"]
                          if not args.so_faltando
                          or s["arquivo_existe"] is False or s["src_dinamico"]]
            n = esqueleto_plano(rel, escolhidos, args.plano)
            print("Esqueleto do plano gravado em %s (%d item(ns), prompt em branco)."
                  % (args.plano, n))


if __name__ == "__main__":
    main()
