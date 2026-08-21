# -*- coding: utf-8 -*-
"""Contrato v2 do plano de midia — o vocabulario comum das tres ferramentas.

Existe por um motivo so: o asset nao tinha identidade no pipeline. O slot da
pagina sabe pasta, nome e extensao; o plano guardava um `id` nu mais UMA pasta
global; e o gerador reconstruia `<public/assets>/<id>.jpg`. Cada salto perdia
uma parte, e o arquivo pago caia onde a pagina nao procura.

Tres principios. Se um patch contrariar um deles, o patch esta errado:

  P1  A identidade do asset e o ARQUIVO QUE A PAGINA PEDE, nao o `id`.
      Esse arquivo se chama `destino`: pasta + nome + extensao, relativo POSIX
      ancorado em `plano["raiz"]`. O `id` e rotulo humano e chave de chamada.
  P2  Quem manda na geracao e a RAZAO, nao o pixel. A API consome aspectRatio +
      tier 1K/2K/4K; o px so decide a reamostragem local.
  P3  O desconhecido e `None` e BARRA a geracao. Nenhuma camada inventa valor:
      nem 1024, nem `public/assets`, nem `.jpg`.

Sem dependencia externa. Escrito em estilo compativel com Python 3.9.
"""
import os
import posixpath
import re

VERSAO_PLANO = 2

# as unicas razoes que a API aceita; qualquer outra vira razao_exibicao + revisar
RAZOES_API = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
QUALIDADES = ["1K", "2K", "4K"]
RESOLUCOES = ["720p", "1080p"]
DURACOES = [4, 6, 8]
CONFIANCAS = ["declarada", "derivada", "medida", "suposta"]

EXT_IMAGEM = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
EXT_VIDEO = (".mp4", ".webm", ".mov", ".m4v")
RAIZES_ESTATICAS = ("", "public", "static", "assets", "dist", "src")

# ai.google.dev/gemini-api/docs/pricing (20/08/2026), USD. Fonte unica: o MCP, o
# fallback e o dry-run leem daqui. Casamento por PREFIXO, senao um id datado
# ('-001', '-11-2026') cai fora da tabela e some do total da PARADA 2.
CUSTO_IMAGEM = {
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-3.1-flash-image": {"1K": 0.067, "2K": 0.101, "4K": 0.151},
    "gemini-2.5-flash-image": {"1K": 0.039, "2K": 0.039, "4K": 0.039},
}
CUSTO_VIDEO_S = {
    "veo-3.1-generate": {"720p": 0.40, "1080p": 0.40},
    "veo-3.1-fast-generate": {"720p": 0.10, "1080p": 0.12},
    "veo-3.1-lite-generate": {"720p": 0.05, "1080p": 0.08},
}

RAZAO_TEXTO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[/:]\s*(\d+(?:\.\d+)?)\s*$")

# alias de bundler: `@/assets/x.png` nao e caminho relativo ao arquivo, e virava
# `components/@/assets/x.png` -- um caminho que nao existe em lugar nenhum
ALIAS_BUNDLER = ("@/", "~/", "~~/", "$lib/", "@@/")
# otimizador de imagem: o arquivo real esta no parametro url=
OTIMIZADOR = re.compile(r"^/(?:_next/image|_vercel/image|cdn-cgi/image/[^/]+)"
                        r"(?:\?|/)(?:.*?url=)?([^&]*)", re.I)


# ------------------------------------------------------------------ preco

def _por_prefixo(tabela, modelo):
    modelo = (modelo or "").strip()
    if modelo in tabela:
        return tabela[modelo]
    for chave in sorted(tabela, key=len, reverse=True):
        if modelo.startswith(chave):
            return tabela[chave]
    return None


def tier_qualidade(largura, altura):
    maior = max(int(largura or 0), int(altura or 0))
    if not maior:
        return None
    if maior <= 1024:
        return "1K"
    if maior <= 2048:
        return "2K"
    return "4K"


def custo_imagem(modelo, qualidade):
    faixa = _por_prefixo(CUSTO_IMAGEM, modelo)
    return None if faixa is None else faixa.get(qualidade)


def custo_video(modelo, resolucao, segundos):
    faixa = _por_prefixo(CUSTO_VIDEO_S, modelo)
    if faixa is None:
        return None
    por_s = faixa.get(resolucao)
    return None if por_s is None else round(por_s * float(segundos or 0), 3)


def combo_de_video_valido(resolucao, segundos):
    """O Veo amarra resolucao e duracao: 1080p so existe com 8 segundos."""
    return not (resolucao == "1080p" and int(segundos or 0) != 8)


# ------------------------------------------------------------------ razao

def razao_api(largura, altura):
    """A razao da API mais proxima, ou None quando nao ha dimensao."""
    if not (largura and altura):
        return None
    alvo = float(largura) / float(altura)
    melhor, dist = None, None
    for r in RAZOES_API:
        a, b = r.split(":")
        d = abs(float(a) / float(b) - alvo)
        if dist is None or d < dist:
            melhor, dist = r, d
    return melhor


def snap_razao(texto):
    """('3.429:1') -> ('21:9', '3.429:1'). Razao ja suportada volta sem exibicao."""
    if not texto:
        return None, None
    texto = str(texto).strip()
    if texto in RAZOES_API:
        return texto, None
    m = RAZAO_TEXTO.match(texto)
    if not m:
        return None, texto
    a, b = float(m.group(1)), float(m.group(2))
    if not b:
        return None, texto
    return razao_api(a, b), texto


# ------------------------------------------------------------------ caminho

GOOGLE_FONT = re.compile(r"family=([^&\"']+)")


def fonte_google(href):
    """Nome da familia e pesos, separados. O href traz `Inter:wght@400;700` e o
    briefing entregava essa string crua como se fosse o nome da fonte."""
    saida = []
    for bruto in GOOGLE_FONT.findall(href or ""):
        familia, _, eixos = bruto.replace("+", " ").partition(":")
        familia = familia.strip()
        if not familia:
            continue
        pesos = re.findall(r"\d{3}", eixos.partition("wght@")[2])
        saida.append("%s (%s)" % (familia, ", ".join(sorted(set(pesos), key=int)))
                     if pesos else familia)
    return saida


def _posix(p):
    return p.replace("\\", "/")


def raiz_de_servico(raiz):
    """A pasta que a build serve como '/'. Por evidencia de disco, nunca por chute."""
    for pasta in RAIZES_ESTATICAS:
        if pasta and os.path.isdir(os.path.join(raiz, pasta)):
            return pasta
    return ""


def caminho(p, raiz):
    """Absolutiza sem deixar sair da raiz. Fecha id com '../' e saida absoluta."""
    raiz_abs = os.path.abspath(raiz)
    alvo = os.path.abspath(p if os.path.isabs(p) else os.path.join(raiz_abs, p))
    try:
        dentro = os.path.commonpath([raiz_abs, alvo]) == raiz_abs
    except ValueError:            # unidades diferentes no Windows
        dentro = False
    if not dentro:
        raise ValueError("destino fora da raiz do projeto: %s (raiz: %s)" % (alvo, raiz_abs))
    return alvo


def raiz_do_plano(plano, raiz_arg=None, raiz_processo=None):
    for c in (raiz_arg, (plano or {}).get("raiz"), raiz_processo, os.getcwd()):
        if c:
            return os.path.abspath(c)
    return os.path.abspath(os.getcwd())


def _geravel(destino):
    ext = posixpath.splitext(destino)[1].lower()
    if ext in EXT_IMAGEM + EXT_VIDEO:
        return destino, None
    return None, "extensao-nao-geravel:%s" % (ext or "sem-extensao")


def resolver_destino(src, arquivo, raiz, raiz_servico=None):
    """O arquivo que a pagina pede, relativo a raiz. (destino|None, origem)."""
    if not src:
        return None, "src-ausente"
    src = str(src).strip()
    if src.startswith(("http://", "https://", "//", "data:", "blob:")):
        return None, "externo"
    if "{" in src or src.startswith("$") or "<?" in src or "{{" in src:
        return None, "src-dinamico"

    # /_next/image?url=%2Fimg%2Fhero.png&w=1200 -> /img/hero.png
    m = OTIMIZADOR.match(src)
    if m and m.group(1):
        try:
            import urllib.parse
            src = urllib.parse.unquote(m.group(1))
        except Exception:
            pass
        if src.startswith(("http://", "https://")):
            return None, "externo"

    # alias de bundler resolve contra a raiz do projeto (ou src/), nao contra o arquivo
    for alias in ALIAS_BUNDLER:
        if src.startswith(alias):
            resto = src[len(alias):]
            for pasta in ("src", "", "app", "assets"):
                cand = os.path.join(raiz, pasta, resto.replace("/", os.sep)) if pasta \
                    else os.path.join(raiz, resto.replace("/", os.sep))
                if os.path.exists(cand):
                    return (_geravel(_posix(os.path.relpath(cand, raiz)))[0],
                            "alias:%s" % alias)
            d, motivo = _geravel(_posix(posixpath.join("src", resto)))
            return d, motivo or "alias:%s (nao encontrado em disco)" % alias

    limpo = src.split("?")[0].split("#")[0]
    if raiz_servico is None:
        raiz_servico = raiz_de_servico(raiz)

    if limpo.startswith("/"):
        rel = limpo.lstrip("/")
        # (a) o arquivo existe sob alguma raiz de servico -- evidencia direta
        for pasta in RAIZES_ESTATICAS:
            cand = os.path.join(raiz, pasta, rel.replace("/", os.sep)) if pasta else \
                os.path.join(raiz, rel.replace("/", os.sep))
            if os.path.exists(cand):
                return _geravel(_posix(os.path.relpath(cand, raiz)))[0], "arquivo-existente"
        # (b) a PASTA pedida existe -- resolve o projeto que serve da raiz mas tem assets/
        for pasta in RAIZES_ESTATICAS:
            base = os.path.join(raiz, pasta) if pasta else raiz
            if os.path.isdir(os.path.join(base, os.path.dirname(rel.replace("/", os.sep)))):
                d, motivo = _geravel(_posix(posixpath.join(pasta, rel) if pasta else rel))
                return d, motivo or ("pasta-existente:%s" % (pasta or "raiz"))
        # (c) convencao pela raiz de servico do projeto
        d, motivo = _geravel(_posix(posixpath.join(raiz_servico, rel) if raiz_servico else rel))
        return d, motivo or ("convencao:%s" % (raiz_servico or "raiz"))

    alvo = os.path.join(os.path.dirname(arquivo), limpo.replace("/", os.sep))
    d, motivo = _geravel(_posix(os.path.relpath(alvo, raiz)))
    return d, motivo or "relativo-ao-arquivo"


def variantes(destino, tipo="imagem"):
    """Todos os arquivos que contam como 'este item ja existe em disco'."""
    if not destino:
        return []
    base, ext = posixpath.splitext(destino)
    saida = [destino, base + "-original" + ext]
    if tipo == "video":
        saida += [base + "-original.mp4", base + "-poster.jpg"]
    else:
        saida += [base + "-original" + e for e in (".png", ".jpg", ".webp")]
    vistos, unicos = set(), []
    for v in saida:
        if v not in vistos:
            vistos.add(v)
            unicos.append(v)
    return unicos


def achar_em_disco(destino, raiz, tipo="imagem"):
    for v in variantes(destino, tipo):
        try:
            p = caminho(v, raiz)
        except ValueError:
            continue
        if os.path.exists(p):
            return v
    return None


# ------------------------------------------------------------------ v1 -> v2

def normalizar_plano(plano, raiz=None):
    """Um midias.json v1 continua rodando, e gravando onde gravava antes."""
    plano = dict(plano or {})
    avisos = []
    if plano.get("versao") == VERSAO_PLANO:
        return plano, avisos

    saida = plano.get("saida") or "public/assets"
    plano["versao"] = VERSAO_PLANO
    plano.setdefault("raiz", raiz)
    plano.setdefault("raiz_servico", "")
    plano["saida"] = saida
    avisos.append("plano no formato v1: normalizado para v2 em memoria (o arquivo em disco "
                  "nao foi alterado). Os destinos foram derivados de '<saida>/<id>'.")

    itens = []
    for it in plano.get("itens", []) or []:
        it = dict(it)
        tipo = it.get("tipo") or "imagem"
        it["tipo"] = tipo
        if not it.get("destino"):
            ext = ".mp4" if tipo == "video" else ".jpg"
            it["destino"] = posixpath.join(saida, "%s%s" % (it.get("id", "sem-id"), ext))
            it["destino_origem"] = "v1:saida+id"

        larg, alt = it.get("largura"), it.get("altura")
        if bool(larg) != bool(alt):          # meia dimensao nunca existiu no site
            avisos.append("%s: largura sem altura (ou vice-versa) foi descartada"
                          % it.get("id"))
            larg = alt = None
        it["largura"], it["altura"] = larg, alt

        api, exibicao = snap_razao(it.get("aspect_ratio"))
        if api is None and (larg and alt):
            api = razao_api(larg, alt)
        it["aspect_ratio"] = api
        if exibicao:
            it["razao_exibicao"] = exibicao
            avisos.append("%s: aspect_ratio '%s' nao existe na API; virou razao_exibicao "
                          "e a geracao usa %s" % (it.get("id"), exibicao, api))

        if tipo == "video":
            it["resolucao"] = it.get("resolucao") or "720p"
            it["duracao_s"] = it.get("duracao_s") or 4
        else:
            it["qualidade"] = it.get("qualidade") or tier_qualidade(larg, alt) or "1K"

        it.setdefault("dimensao_origem", "v1:plano")
        it.setdefault("dimensao_confianca", "declarada" if (larg and alt) else "suposta")

        revisar = it.get("revisar")
        if isinstance(revisar, str):
            revisar = [revisar]
        it["revisar"] = list(revisar or [])
        if it["dimensao_confianca"] == "suposta" and not it["revisar"]:
            it["revisar"].append("dimensao nao declarada no site - confirme antes de gerar")

        if "origem" not in it and it.get("nota"):
            partes = str(it["nota"]).split("  ", 1)
            it["origem"] = {"arquivo": partes[0], "copy": partes[1] if len(partes) > 1 else ""}
        it.setdefault("prompt", "")
        it.setdefault("aceite", "")
        it.setdefault("estado", {})
        itens.append(it)

    plano["itens"] = itens
    return plano, avisos


# ------------------------------------------------------------------ invariantes

def validar(plano):
    """As 12 invariantes do contrato. Devolve a lista de problemas (vazia = ok)."""
    p = []
    if plano.get("versao") != VERSAO_PLANO:
        p.append("1. plano sem versao %d (rode normalizar_plano antes)" % VERSAO_PLANO)

    ids, destinos = {}, {}
    for i, it in enumerate(plano.get("itens", []) or []):
        rot = it.get("id") or "item[%d]" % i
        if not it.get("id"):
            p.append("2. %s: item sem id" % rot)
        if it.get("id") in ids:
            p.append("3. id repetido: %s" % it.get("id"))
        ids[it.get("id")] = True

        tipo = it.get("tipo")
        if tipo not in ("imagem", "video"):
            p.append("7. %s: tipo invalido (%r)" % (rot, tipo))

        d = it.get("destino")
        if d:
            if d in destinos:
                p.append("4. %s: destino repetido (%s) - seria pagar duas vezes pelo "
                         "mesmo arquivo" % (rot, d))
            destinos[d] = True
            if os.path.isabs(d) or "\\" in d or ".." in d.split("/"):
                p.append("5. %s: destino tem de ser relativo POSIX sem '..' (%s)" % (rot, d))
            ext = posixpath.splitext(d)[1].lower()
            esperado = EXT_VIDEO if tipo == "video" else EXT_IMAGEM
            if ext and ext not in esperado:
                p.append("6. %s: extensao %s nao combina com tipo %s" % (rot, ext, tipo))

        r = it.get("aspect_ratio")
        if r is not None and r not in RAZOES_API:
            p.append("8. %s: aspect_ratio %r nao existe na API (use razao_exibicao)" % (rot, r))

        larg, alt = it.get("largura"), it.get("altura")
        if bool(larg) != bool(alt):
            p.append("9. %s: largura e altura tem de vir em par" % rot)

        if tipo == "imagem" and it.get("qualidade") not in QUALIDADES:
            p.append("10. %s: qualidade %r fora de %s" % (rot, it.get("qualidade"), QUALIDADES))

        if tipo == "video":
            if it.get("resolucao") not in RESOLUCOES:
                p.append("11. %s: resolucao %r invalida" % (rot, it.get("resolucao")))
            if it.get("duracao_s") not in DURACOES:
                p.append("11. %s: duracao_s %r invalida" % (rot, it.get("duracao_s")))
            if not combo_de_video_valido(it.get("resolucao"), it.get("duracao_s")):
                p.append("11. %s: 1080p so existe com 8 segundos" % rot)

        conf = it.get("dimensao_confianca")
        if conf not in CONFIANCAS:
            p.append("12. %s: dimensao_confianca %r fora de %s" % (rot, conf, CONFIANCAS))
        elif conf == "suposta" and not it.get("revisar"):
            p.append("12. %s: dimensao suposta tem de trazer 'revisar' preenchido" % rot)
    return p
