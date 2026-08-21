#!/usr/bin/env python3
"""Extrai o briefing estrutural de um canvas do /design (artboards .dc.html).

Uso:
    python ferramentas/ler_design.py <arquivo.dc.html | pasta> [--json briefing.json]

Nao depende de bibliotecas externas. A leitura e deliberadamente defensiva:
o formato dos artboards pode mudar, entao a extracao se apoia em sinais
genericos de HTML/CSS (tags de midia, dimensoes inline, custom properties)
em vez de um schema fixo.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser

MEDIA_HINT = re.compile(r"placeholder|media|image|imagem|photo|foto|video|hero|thumb|poster", re.I)
SIZE_IN_STYLE = re.compile(r"(?<![\w-])(width|height|aspect-ratio)\s*:\s*([^;]+)", re.I)
HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_COLOR = re.compile(r"rgba?\([^)]*\)")
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
CSS_VAR = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+)")
GOOGLE_FONT = re.compile(r"family=([^&\"']+)")
ARTBOARD_CLASS = re.compile(r"\bartboard\b|\bframe\b|\bscreen\b", re.I)
QUOTES = "'" + '"'


class ColetorDeArtboards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.artboards = []       # secoes de topo do canvas
        self.midias = []          # img / video / divs com cara de placeholder
        self.css = []             # conteudo de <style> e atributos style
        self.google_fonts = []    # <link href=fonts.googleapis.com>
        self.textos = []          # blocos de copy visiveis
        self._pilha = []
        self._em_style = False
        self._captura_texto = None

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _attrs(attrs):
        return {k.lower(): (v or "") for k, v in attrs}

    @staticmethod
    def _dimensoes(a):
        dim = {}
        for chave in ("width", "height"):
            if a.get(chave):
                dim[chave] = a[chave].strip()
        for prop, valor in SIZE_IN_STYLE.findall(a.get("style", "")):
            dim[prop.lower()] = valor.strip()
        return dim

    @staticmethod
    def _rotulo(a, tag):
        for chave in ("data-artboard", "data-name", "data-label", "aria-label",
                      "alt", "title", "id"):
            if a.get(chave):
                return a[chave].strip()
        return a.get("class", "").strip() or tag

    # -- parser ----------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = self._attrs(attrs)
        assinatura = " ".join([tag, a.get("class", ""), a.get("id", ""),
                               " ".join(k for k in a if k.startswith("data-"))])

        if tag == "style":
            self._em_style = True
        elif tag == "link" and "fonts.googleapis.com" in a.get("href", ""):
            self.google_fonts.extend(
                f.replace("+", " ") for f in GOOGLE_FONT.findall(a["href"])
            )

        if tag in ("img", "video", "picture", "canvas") or (
            tag not in ("style", "script", "link", "meta") and MEDIA_HINT.search(assinatura)
        ):
            self.midias.append({
                "tag": tag,
                "rotulo": self._rotulo(a, tag),
                "src": a.get("src") or a.get("poster") or "",
                "alt": a.get("alt", ""),
                "classes": a.get("class", ""),
                "dimensoes": self._dimensoes(a),
                "artboard": self._pilha[-1] if self._pilha else None,
            })

        eh_artboard = "data-artboard" in a or ARTBOARD_CLASS.search(a.get("class", ""))
        if eh_artboard or (tag in ("section", "header", "footer", "main") and not self._pilha):
            nome = self._rotulo(a, tag)
            self.artboards.append({"nome": nome, "tag": tag, "dimensoes": self._dimensoes(a)})
            self._pilha.append(nome)

        if tag in ("h1", "h2", "h3", "p", "button"):
            self._captura_texto = tag

        if a.get("style"):
            self.css.append(a["style"])

    def handle_endtag(self, tag):
        if tag == "style":
            self._em_style = False
        if self._pilha and tag in ("section", "header", "footer", "main", "div"):
            self._pilha.pop()
        self._captura_texto = None

    def handle_data(self, data):
        if self._em_style:
            self.css.append(data)
        elif self._captura_texto:
            texto = " ".join(data.split())
            if texto:
                self.textos.append({"tag": self._captura_texto, "texto": texto[:160]})


def analisar_arquivo(caminho):
    with open(caminho, "r", encoding="utf-8", errors="replace") as f:
        bruto = f.read()

    p = ColetorDeArtboards()
    p.feed(bruto)
    css = "\n".join(p.css)

    cores = Counter(c.lower() for c in HEX_COLOR.findall(css))
    cores.update(c.replace(" ", "") for c in RGB_COLOR.findall(css))
    fontes = Counter(
        ", ".join(t.strip().strip(QUOTES) for t in pilha.split(","))
        for pilha in FONT_FAMILY.findall(css)
    )
    variaveis = {nome: valor.strip() for nome, valor in CSS_VAR.findall(css)}

    return {
        "arquivo": os.path.basename(caminho),
        "caminho": caminho,
        "artboards": p.artboards,
        "midias": p.midias,
        "google_fonts": sorted(set(p.google_fonts)),
        "font_family_declaradas": [f for f, _ in fontes.most_common(12)],
        "paleta": [{"cor": c, "ocorrencias": n} for c, n in cores.most_common(16)],
        "css_variaveis": variaveis,
        "copy": p.textos[:40],
    }


def coletar_arquivos(alvo):
    if os.path.isfile(alvo):
        return [alvo]
    if not os.path.isdir(alvo):
        sys.exit("Erro: '%s' nao encontrado." % alvo)
    achados = []
    for raiz, _, arquivos in os.walk(alvo):
        if any(parte in raiz for parte in (".git", "node_modules", "public")):
            continue
        for nome in sorted(arquivos):
            if nome.endswith((".dc.html", ".html", ".htm")):
                achados.append(os.path.join(raiz, nome))
    if not achados:
        sys.exit("Erro: nenhum .dc.html/.html encontrado em '%s'." % alvo)
    return achados


def imprimir_briefing(relatorios):
    for r in relatorios:
        print("\n" + "=" * 68)
        print("ARTBOARD FILE: " + r["arquivo"])
        print("=" * 68)

        print("\n-- Secoes (%d) --" % len(r["artboards"]))
        for i, ab in enumerate(r["artboards"], 1):
            dim = ", ".join("%s=%s" % (k, v) for k, v in ab["dimensoes"].items())
            print("  %2d. %s  [%s]" % (i, ab["nome"], dim or "sem dimensao explicita"))

        print("\n-- Placeholders de midia (%d) --" % len(r["midias"]))
        for i, m in enumerate(r["midias"], 1):
            dim = ", ".join("%s=%s" % (k, v) for k, v in m["dimensoes"].items()) or "?"
            ctx = (" @ " + m["artboard"]) if m["artboard"] else ""
            print("  %2d. <%s> %s%s" % (i, m["tag"], m["rotulo"], ctx))
            print("      dimensoes: %s" % dim)
            if m["src"]:
                print("      src atual: %s" % m["src"])
            if m["alt"]:
                print("      alt: %s" % m["alt"])

        if r["google_fonts"]:
            print("\n-- Google Fonts --\n  " + ", ".join(r["google_fonts"]))
        if r["font_family_declaradas"]:
            print("\n-- font-family no CSS --")
            for f in r["font_family_declaradas"]:
                print("  " + f)
        if r["paleta"]:
            print("\n-- Paleta (por frequencia) --")
            for c in r["paleta"]:
                print("  %-24s %dx" % (c["cor"], c["ocorrencias"]))
        if r["css_variaveis"]:
            print("\n-- Design tokens (custom properties) --")
            for nome, valor in list(r["css_variaveis"].items())[:30]:
                print("  %s: %s" % (nome, valor))
        if r["copy"]:
            print("\n-- Copy detectada --")
            for t in r["copy"][:15]:
                print("  <%s> %s" % (t["tag"], t["texto"]))


def main():
    ap = argparse.ArgumentParser(description="Extrai briefing de artboards do /design.")
    ap.add_argument("alvo", nargs="?", default=".", help="arquivo .dc.html ou pasta")
    ap.add_argument("--json", dest="saida_json", help="grava o briefing estruturado neste caminho")
    args = ap.parse_args()

    relatorios = [analisar_arquivo(c) for c in coletar_arquivos(args.alvo)]
    imprimir_briefing(relatorios)

    total = sum(len(r["midias"]) for r in relatorios)
    print("\n" + "=" * 68)
    print("TOTAL: %d arquivo(s), %d placeholder(s) de midia." % (len(relatorios), total))
    print("=" * 68)

    if args.saida_json:
        with open(args.saida_json, "w", encoding="utf-8") as f:
            json.dump(relatorios, f, ensure_ascii=False, indent=2)
        print("Briefing estruturado gravado em " + args.saida_json)


if __name__ == "__main__":
    main()
