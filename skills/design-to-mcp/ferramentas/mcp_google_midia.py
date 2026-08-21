#!/usr/bin/env python3
"""Servidor MCP (stdio) que gera midia com a API do Google Gemini.

Ferramentas expostas:
    listar_modelos   modelos de imagem e video disponiveis na chave
    estimar_custo    custo em USD de um plano (midias.json) antes de gerar
    gerar_imagem     Nano Banana Pro / Nano Banana 2 -> arquivo em public/assets
    gerar_video      Veo 3.1 (submete o job e devolve o id da operacao)
    status_video     consulta a operacao e baixa o mp4 quando terminar
    preparar_video   reencode com keyframe por frame + poster (ffmpeg)
    atualizar_inventario  regrava o inventario HTML a partir dos assets em disco

Chave: variavel de ambiente GEMINI_API_KEY (definida no registro do MCP).
Dependencias: stdlib + Pillow (redimensionamento) + ffmpeg no PATH (video).
"""

import base64
import hashlib
import io
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contrato  # noqa: E402  - vocabulario comum das tres ferramentas

# P-mcp-6: o import tem de acontecer ANTES de qualquer POST cobrado. Estava dentro de
# t_gerar_imagem, depois da cobranca: numa maquina sem Pillow a imagem era paga e o
# cliente recebia so 'ModuleNotFoundError'.
try:
    from PIL import Image
    SEM_PILLOW = None
except ImportError as _e:  # pragma: no cover - depende da maquina
    Image, SEM_PILLOW = None, str(_e)

# Raiz para caminhos relativos: o projeto onde o Claude Code foi aberto, NAO a pasta do
# script. Instalada em ~/.claude/skills/, a skill escreveria os assets dentro dela mesma.
# MIDIA_RAIZ existe para o caso de o cliente subir o servidor com outro cwd.
RAIZ = os.path.abspath(os.environ.get("MIDIA_RAIZ") or os.getcwd())
API = "https://generativelanguage.googleapis.com/v1beta"
PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")

MODELO_IMAGEM = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
MODELO_VIDEO = os.environ.get("GEMINI_VIDEO_MODEL", "veo-3.1-fast-generate-preview")

# Fonte unica da tabela de preco: contrato.py. Havia tres copias no repositorio, e
# um modelo com id datado nao casava com nenhuma -- o item sumia do total da PARADA 2.
CUSTO_IMAGEM = contrato.CUSTO_IMAGEM
CUSTO_VIDEO_S = contrato.CUSTO_VIDEO_S
RAZOES = contrato.RAZOES_API


def _teto(nome, padrao):
    """Teto de gasto do registro do MCP. 'off' desliga; 0 bloqueia tudo."""
    bruto = (os.environ.get(nome) or "").strip().lower()
    if not bruto:
        return padrao
    if bruto in ("off", "none", "sem", "-1"):
        return None
    try:
        return max(0.0, float(bruto.replace(",", ".")))
    except ValueError:
        return padrao


# A trava nao se levanta de dentro da sessao: mudar exige mexer no registro do MCP e
# reiniciar o Claude Code. E isso que a torna uma trava, e nao um lembrete.
TETO_USD = _teto("MIDIA_TETO_USD", 5.0)              # acumulado em 24h
TETO_CHAMADA_USD = _teto("MIDIA_TETO_CHAMADA_USD", 1.0)
VALIDADE_ORCAMENTO_S = 3600
# padrao desligado: o token vira exigencia so quando o usuario liga o campo no
# formulario do /plugin. Sem ele a chamada passa, mas a resposta sai marcada.
EXIGE_ORCAMENTO = (os.environ.get("MIDIA_EXIGE_ORCAMENTO", "") or "").strip().lower() \
    in ("1", "true", "sim", "on")
ORCAMENTOS = {}


# ------------------------------------------------------------------ util

def log(msg):
    print(msg, file=sys.stderr, flush=True)


class Falha(Exception):
    pass


# ------------------------------------------------------------------ ledger de gasto

def ledger():
    return os.environ.get("MIDIA_LEDGER") or os.path.join(
        RAIZ, ".claude", "state", "midias-gastos.jsonl")


def registrar_gasto(**campos):
    """Uma linha por chamada cobrada, gravada ANTES do POST.

    E o instante a partir do qual o dinheiro pode ter saido. O arquivo sobrevive a
    /compact, a reinicio do servidor e a troca de sessao -- que e o que o contador
    de processo nao faz.
    """
    campos.setdefault("epoch", time.time())
    campos.setdefault("quando", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    try:
        alvo = ledger()
        os.makedirs(os.path.dirname(alvo), exist_ok=True)
        with open(alvo, "a", encoding="utf-8") as f:
            f.write(json.dumps(campos, ensure_ascii=False) + "\n")
    except Exception as e:  # o ledger nunca pode impedir a chamada de acontecer
        log("aviso: nao consegui gravar no ledger (%s)" % e)


def estornar(ident, custo, motivo):
    """Linha negativa quando a API recusou sem cobrar (400/401/403/404)."""
    registrar_gasto(ferramenta="estorno", id=ident, custo_usd=-abs(custo or 0.0),
                    motivo=motivo)


def gasto_recente(horas=24):
    alvo = ledger()
    if not os.path.exists(alvo):
        return 0.0
    corte = time.time() - horas * 3600
    total = 0.0
    try:
        with open(alvo, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    d = json.loads(linha)
                except ValueError:
                    continue
                if float(d.get("epoch", 0)) >= corte:
                    total += float(d.get("custo_usd") or 0.0)
    except Exception as e:
        log("aviso: nao consegui ler o ledger (%s)" % e)
    return round(total, 4)


def checar_teto(custo, ident):
    """Roda ANTES do POST. Recusar aqui e de graca; recusar depois nao existe."""
    if custo is None:
        return
    if TETO_CHAMADA_USD is not None and custo > TETO_CHAMADA_USD:
        raise Falha(
            "'%s' custa US$ %.3f e o teto por chamada e US$ %.2f "
            "(MIDIA_TETO_CHAMADA_USD no registro do MCP). Nada foi cobrado."
            % (ident, custo, TETO_CHAMADA_USD))
    if TETO_USD is not None:
        ja = gasto_recente()
        if ja + custo > TETO_USD:
            raise Falha(
                "teto de gasto atingido: US$ %.2f ja saiu nas ultimas 24h e '%s' custa mais "
                "US$ %.3f, acima do teto de US$ %.2f (MIDIA_TETO_USD). Nada foi cobrado. "
                "Para elevar o teto o usuario precisa mudar o registro do MCP e reiniciar o "
                "Claude Code -- nao da para levantar esta trava de dentro da sessao."
                % (ja, ident, custo, TETO_USD))


# ------------------------------------------------------------------ token de orcamento

def assinatura_item(ident, tipo, modelo, escala, saida):
    cru = "|".join(str(x) for x in (ident, tipo, modelo, escala, saida or ""))
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:16]


def emitir_orcamento(aprovados, total):
    """Token da PARADA 2. A autoridade e a memoria deste processo: nada a forjar."""
    if not aprovados:
        return None
    token = "orc-" + secrets.token_urlsafe(9)
    while len(ORCAMENTOS) >= 8:
        ORCAMENTOS.pop(next(iter(ORCAMENTOS)))
    ORCAMENTOS[token] = {"emitido": time.time(), "total": total,
                         "itens": aprovados, "usados": set()}
    return token


def consumir_orcamento(a, ident, assinatura, custo):
    """Devolve o aviso a anexar na resposta, ou None quando houve aval.

    Com a exigencia desligada -- que e o padrao -- a chamada sem token passava em
    silencio: nada na resposta dizia que o dinheiro saiu fora da PARADA 2.
    """
    token = a.get("orcamento")
    if not token:
        if EXIGE_ORCAMENTO:
            raise Falha("esta chamada cobra e nenhum orcamento foi apresentado. Rode "
                        "estimar_custo, mostre a lista ao usuario (PARADA 2) e passe o "
                        "token devolvido em orcamento:. Nada foi cobrado.")
        return ("AVISO: gerado SEM orcamento aprovado (US$ %s cobrados). A PARADA 2 "
                "existe para o usuario ver a lista e o total ANTES da cobranca -- rode "
                "estimar_custo e passe o token em orcamento:."
                % ("%.3f" % custo if custo else "?"))
    orc = ORCAMENTOS.get(token)
    if not orc:
        raise Falha("orcamento '%s' desconhecido neste servidor (ele morre quando o "
                    "servidor reinicia). Rode estimar_custo de novo. Nada foi cobrado."
                    % token)
    if time.time() - orc["emitido"] > VALIDADE_ORCAMENTO_S:
        raise Falha("orcamento '%s' expirou (vale %d min). Rode estimar_custo de novo e "
                    "confirme com o usuario. Nada foi cobrado."
                    % (token, VALIDADE_ORCAMENTO_S // 60))
    item = orc["itens"].get(ident)
    if not item:
        raise Falha("'%s' nao estava na lista aprovada do orcamento '%s' (aprovados: %s). "
                    "Nada foi cobrado." % (ident, token, ", ".join(sorted(orc["itens"]))))
    if item["assinatura"] != assinatura:
        raise Falha("os parametros de '%s' mudaram depois da aprovacao (aprovado: %s por "
                    "US$ %.3f). Rode estimar_custo com os parametros novos. Nada foi cobrado."
                    % (ident, item["escala"], item["custo"]))
    if ident in orc["usados"]:
        raise Falha("'%s' ja foi gerado com o orcamento '%s'. Para regerar, rode "
                    "estimar_custo de novo. Nada foi cobrado." % (ident, token))
    orc["usados"].add(ident)


def livre(p, sobrescrever):
    """Caminho gravavel sem destruir o que ja esta la (P-mcpgen-3)."""
    if sobrescrever or not os.path.exists(p):
        return p, None
    base, ext = os.path.splitext(p)
    for n in range(1, 50):
        cand = "%s-novo%s%s" % (base, "" if n == 1 else "-%d" % n, ext)
        if not os.path.exists(cand):
            return cand, ("%s ja existia: gravei em %s (a chamada ja foi cobrada). "
                          "Passe sobrescrever:true para trocar o arquivo antigo."
                          % (os.path.basename(p), os.path.basename(cand)))
    raise Falha("nao consegui um nome livre para %s" % p)


def api_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        raise Falha("GEMINI_API_KEY nao definida no ambiente do servidor MCP.")
    return k


def host_google(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return h == "googleapis.com" or h.endswith(".googleapis.com")


class RedirectSemCredencial(urllib.request.HTTPRedirectHandler):
    """A chave nao acompanha um redirect para fora do Google."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        novo = urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)
        if novo is not None and not host_google(newurl):
            novo.remove_header("X-goog-api-key")
        return novo


ABRIDOR = urllib.request.build_opener(RedirectSemCredencial())


def http(url, payload=None, metodo=None, tentativas=3, bruto=False, cobra=False):
    dados = json.dumps(payload).encode("utf-8") if payload is not None else None
    # a chave so vai para o Google: a URI que a operacao do Veo devolve pode ser de
    # outro host, e mandar credencial para la e vazamento
    cab = {"x-goog-api-key": api_key()} if host_google(url) else {}
    if dados:
        cab["Content-Type"] = "application/json"
    # num POST que cobra, repetir e o mesmo que pagar de novo: um 5xx (ou um timeout de
    # leitura) pode esconder um pedido que o servidor ja aceitou. So 429 -- que e recusa
    # antes do trabalho -- continua sendo retentado.
    repetiveis = (429,) if cobra else (408, 429, 500, 502, 503, 504)
    aviso = ("" if not cobra else
             " (nao repeti a submissao: depois do POST, um erro pode esconder um pedido"
             " ja aceito e cobrado -- confira o estado antes de tentar de novo)")
    ultimo = None
    for t in range(tentativas):
        req = urllib.request.Request(url, data=dados, headers=cab, method=metodo)
        try:
            with ABRIDOR.open(req, timeout=600) as r:
                corpo = r.read()
                return corpo if bruto else json.loads(corpo.decode("utf-8"))
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:600]
            ultimo = "HTTP %s: %s%s" % (e.code, corpo, aviso)
            if e.code in repetiveis and t < tentativas - 1:
                time.sleep(2 ** t * 3)
                continue
            raise Falha(ultimo)
        except urllib.error.URLError as e:
            ultimo = "rede: %s%s" % (e.reason, aviso)
            if not cobra and t < tentativas - 1:
                time.sleep(2 ** t * 3)
                continue
            raise Falha(ultimo)
    raise Falha(ultimo or "falha desconhecida")


def caminho(p, raiz=None):
    """Absolutiza contra a raiz do plano (nao contra o cwd) e recusa sair dela."""
    try:
        return contrato.caminho(p, raiz or RAIZ)
    except ValueError as e:
        raise Falha(str(e))


def carregar_plano(a, obrigatorio=False):
    """(plano_v2, raiz, caminho_do_arquivo). Sem `plano`, cai no comportamento antigo."""
    rel = a.get("plano")
    if not rel:
        if obrigatorio:
            raise Falha("informe plano: o caminho do midias.json")
        return None, RAIZ, None
    alvo = caminho(rel)
    if not os.path.exists(alvo):
        raise Falha("plano nao encontrado: %s (raiz em uso: %s). Confira o caminho, ou "
                    "passe raiz: se o projeto nao e o cwd do servidor." % (alvo, RAIZ))
    try:
        with open(alvo, encoding="utf-8") as f:
            bruto = json.load(f)
    except ValueError as e:
        raise Falha("plano %s nao e JSON valido: %s" % (alvo, e))
    raiz = contrato.raiz_do_plano(bruto, a.get("raiz"), RAIZ)
    plano, avisos = contrato.normalizar_plano(bruto, raiz)
    plano["_avisos"] = avisos
    return plano, raiz, alvo


def item_do_plano(plano, ident):
    for it in (plano or {}).get("itens", []) or []:
        if it.get("id") == ident:
            return it
    return None


def gravar_plano(plano, alvo):
    """O plano e o checklist da rodada: estado que nao sobrevive nao serve."""
    if not alvo:
        return
    limpo = dict(plano)
    limpo.pop("_avisos", None)
    try:
        with open(alvo, "w", encoding="utf-8") as f:
            json.dump(limpo, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as e:
        log("aviso: nao consegui regravar o plano (%s)" % e)


def razao(largura, altura):
    return contrato.razao_api(largura, altura) or "1:1"


def tamanho_imagem(largura, altura):
    return contrato.tier_qualidade(largura, altura) or "1K"


def custo_imagem(modelo, tam):
    return contrato.custo_imagem(modelo, tam)


def custo_video(modelo, resolucao, segundos):
    return contrato.custo_video(modelo, resolucao, segundos)


def ler_imagem(p):
    p = caminho(p)
    if not os.path.exists(p):
        raise Falha("referencia nao encontrada: %s" % p)
    mime = mimetypes.guess_type(p)[0] or "image/png"
    with open(p, "rb") as f:
        return mime, base64.b64encode(f.read()).decode("ascii")


EXT_VIDEO_URI = (".mp4", ".webm", ".mov", ".m4v")


def _parece_video(v):
    baixo = v.lower().split("?")[0]
    return (baixo.endswith(EXT_VIDEO_URI) or ":download" in v
            or "alt=media" in v.lower() or "/videos/" in baixo)


def _varrer_uri(no):
    if isinstance(no, dict):
        for k, v in no.items():
            if (k in ("uri", "url") and isinstance(v, str) and v.startswith("http")
                    and host_google(v) and _parece_video(v)):
                return v
            achou = _varrer_uri(v)
            if achou:
                return achou
    elif isinstance(no, list):
        for item in no:
            achou = _varrer_uri(item)
            if achou:
                return achou
    return None


def achar_uri(no):
    """URI do mp4 na resposta da operacao do Veo.

    Le primeiro o caminho conhecido; a varredura generica so entra como plano B, e
    exigindo host do Google -- devolver a primeira uri http que aparecesse podia
    entregar um link de documentacao para baixar com a chave anexada.
    """
    try:
        amostras = (no.get("generateVideoResponse", {}) or {}).get("generatedSamples")
        for s in amostras or []:
            u = ((s or {}).get("video") or {}).get("uri")
            if isinstance(u, str) and u.startswith("http"):
                return u
    except AttributeError:
        pass
    return _varrer_uri(no)


# ------------------------------------------------------------------ ferramentas

def t_listar_modelos(_):
    d = http("%s/models?pageSize=300" % API, None, "GET")
    imgs, vids = [], []
    for m in d.get("models", []):
        nome = m.get("name", "").replace("models/", "")
        rotulo = "%-40s %s" % (nome, m.get("displayName", ""))
        if "veo" in nome:
            vids.append(rotulo)
        elif "image" in nome:
            imgs.append(rotulo)
    return ("IMAGEM\n  " + "\n  ".join(imgs) + "\n\nVIDEO\n  " + "\n  ".join(vids) +
            "\n\nRAIZ (destino dos caminhos relativos): %s" % RAIZ)


def asset_em_disco(item, raiz, saida=None):
    """Arquivo ja gravado para o item, incluindo as variantes -original e -poster.

    Enxergar so `<saida>/<id>.jpg` fazia o mp4 baixado e a imagem sem reamostragem
    contarem como faltando -- e a rodada seguinte pagava de novo pelo mesmo pixel.
    """
    tipo = item.get("tipo") or "imagem"
    destino = item.get("destino")
    if not destino:
        ext = ".mp4" if tipo == "video" else ".jpg"
        destino = "%s/%s%s" % ((saida or "public/assets").replace("\\", "/"),
                               item.get("id", ""), ext)
    return contrato.achar_em_disco(destino, raiz, tipo)


def t_estimar_custo(a):
    itens = a.get("itens")
    regerar = set(a.get("regerar") or [])
    if itens:
        # itens inline: a raiz e a do servidor, e o `saida` do plano nao se aplica
        plano, raiz, _ = None, RAIZ, None
        saida = a.get("saida") or "public/assets"
    else:
        plano, raiz, _ = carregar_plano(dict(a, plano=a.get("plano") or "midias.json"),
                                        obrigatorio=True)
        itens = plano.get("itens", [])
        saida = plano.get("saida", "public/assets")
    linhas, total, incerto = [], 0.0, False
    ja_existem, gasto_repetido, aprovados, sem_preco = [], 0.0, {}, []
    for it in itens:
        if it.get("tipo") == "video":
            modelo = it.get("modelo", MODELO_VIDEO)
            res = it.get("resolucao") or "720p"
            seg = it.get("duracao_s") or 4
            c = custo_video(modelo, res, seg)
            escala = "%ss %s" % (seg, res)
            desc = "%s %ss %s" % (modelo, seg, res)
            if res == "1080p" and seg != 8:
                # cotar um par que a API recusa e pior que nao cotar: o numero da
                # PARADA 2 fica pela metade do que se consegue comprar
                c = None
                desc += "  ALERTA combo invalido: 1080p so em 8s (US$ %s); com %ss use 720p" % (
                    custo_video(modelo, "1080p", 8), seg)
        else:
            modelo = it.get("modelo", MODELO_IMAGEM)
            tam = it.get("qualidade") or tamanho_imagem(it.get("largura", 1024),
                                                        it.get("altura", 1024))
            c = custo_imagem(modelo, tam)
            escala = tam
            desc = "%s %s" % (modelo, tam)
        ident = it.get("id", "?")
        existe = asset_em_disco(it, raiz, saida)
        pedido_de_regerar = ident in regerar
        if existe and not pedido_de_regerar:
            ja_existem.append(ident)
            gasto_repetido += c or 0.0
        marca = ("  <- REGERAR pedido (o arquivo atual vai ser trocado)" if pedido_de_regerar
                 else "  <- ja existe em disco (%s)" % existe if existe else "")
        # o que esta sendo COMPRADO, nao so quanto custa: sem destino e sem a frase do
        # prompt, a PARADA 2 pede um sim para uma lista de precos sem objeto
        onde = it.get("destino") or "%s/%s.<ext>" % (saida, ident)
        detalhe = "        -> %s" % onde
        if it.get("dimensao_confianca") == "suposta":
            detalhe += "   [!] dimensao SUPOSTA: %s" % "; ".join(it.get("revisar") or [])
        if it.get("prompt"):
            detalhe += "\n        \"%s\"" % str(it["prompt"])[:110]
        elif not pedido_de_regerar and not existe:
            detalhe += "\n        [!] prompt em branco: escreva antes de aprovar"
        if c is None:
            incerto = True
            sem_preco.append(ident)
            linhas.append("  %-16s %-46s custo DESCONHECIDO%s" % (ident, desc, marca))
        else:
            total += c
            if not existe or pedido_de_regerar:
                aprovados[ident] = {
                    "assinatura": assinatura_item(ident, it.get("tipo", "imagem"), modelo,
                                                  escala, it.get("destino")),
                    "custo": c, "escala": "%s %s" % (modelo, escala)}
            linhas.append("  %-16s %-46s US$ %.3f%s" % (ident, desc, c, marca))
        linhas.append(detalhe)
    rodape = "\nTOTAL ESTIMADO: US$ %.2f em %d itens" % (total, len(itens))
    if ja_existem:
        rodape += ("\nDESTE TOTAL, US$ %.2f em %d item(ns) que JA EXISTEM em disco (%s):"
                   " so cobre de novo se a intencao for regerar."
                   % (gasto_repetido, len(ja_existem), ", ".join(ja_existem)))
        rodape += "\nGerar so o que falta custa US$ %.2f." % (total - gasto_repetido)
    if incerto:
        # o TOTAL nunca pode passar por completo estando incompleto: era assim que a
        # PARADA 2 exibia US$ 0,00 para um lote de dezenas de dolares
        rodape = ("\nATENCAO: %d item(ns) sem preco conhecido na tabela (%s). O total abaixo "
                  "e um PISO, nao o valor final -- confirme o preco desses modelos em "
                  "ai.google.dev/gemini-api/docs/pricing antes de aprovar."
                  % (len(sem_preco), ", ".join(sem_preco))) + rodape.replace(
            "TOTAL ESTIMADO", "TOTAL ESTIMADO (PISO)")
    if TETO_USD is not None:
        rodape += ("\nGasto nas ultimas 24h: US$ %.2f de um teto de US$ %.2f."
                   % (gasto_recente(), TETO_USD))
    token = emitir_orcamento(aprovados, total - gasto_repetido)
    if token:
        rodape += ("\n\nPARADA 2: mostre esta lista e o total ao usuario e espere aprovacao\n"
                   "explicita. Depois do aval, passe orcamento:\"%s\" em cada\n"
                   "gerar_imagem/gerar_video (vale %d min, um uso por item)."
                   % (token, VALIDADE_ORCAMENTO_S // 60))
    return "\n".join(linhas) + rodape


def primeira_imagem(resp):
    """Primeiro candidato com imagem. O laco antigo tinha break so no laco interno,
    entao com mais de um candidato quem vencia era o ultimo."""
    cands = resp.get("candidates", []) or []
    for cand in cands:
        for parte in cand.get("content", {}).get("parts", []):
            inline = parte.get("inlineData") or parte.get("inline_data")
            if inline and inline.get("data"):
                mime = (inline.get("mimeType") or inline.get("mime_type")
                        or "image/png")
                return base64.b64decode(inline["data"]), mime, len(cands)
    # o dump cru nao dizia as duas coisas que decidem o proximo passo: se o dinheiro
    # ja saiu, e se repetir adianta. Depois de um bloqueio de seguranca, o palpite
    # natural do agente e tentar de novo -- e pagar duas vezes pela mesma recusa.
    raise Falha(contrato.explicar_sem_imagem(resp, cobrada=True))


def _sem_cobranca(erro):
    """400/401/403/404 sao recusa antes do trabalho: nao cobram."""
    return any(("HTTP %d" % k) in str(erro) for k in (400, 401, 403, 404))


def _resolver(a, tipo):
    """Junta argumento da chamada + item do plano. O plano manda no endereco."""
    ident = a["id"]
    plano, raiz, alvo_plano = carregar_plano(a)
    item = item_do_plano(plano, ident)
    if plano is not None and item is None:
        raise Falha("'%s' nao esta no plano %s. Os ids do plano sao: %s"
                    % (ident, a.get("plano"),
                       ", ".join(i.get("id", "?") for i in plano.get("itens", []))))
    item = item or {}
    for aviso in (plano or {}).get("_avisos", []):
        log("plano: %s" % aviso)
    return ident, item, plano, raiz, alvo_plano


def t_gerar_imagem(a):
    ident, item, plano, raiz, alvo_plano = _resolver(a, "imagem")
    modelo = a.get("modelo") or item.get("modelo") or MODELO_IMAGEM
    largura = a.get("largura") or item.get("largura")
    altura = a.get("altura") or item.get("altura")
    if bool(largura) != bool(altura):
        raise Falha("largura e altura tem de vir em par (%r x %r): meia dimensao nunca "
                    "existiu no site. Nada foi cobrado." % (largura, altura))
    tam = (a.get("qualidade") or item.get("qualidade")
           or contrato.tier_qualidade(largura, altura))
    prop = (a.get("aspect_ratio") or item.get("aspect_ratio")
            or contrato.razao_api(largura, altura))
    # P3 do contrato: o desconhecido barra a geracao, nao vira 1024 nem 1:1
    if not prop:
        raise Falha("item sem aspect_ratio e sem largura/altura: recuso gerar as cegas. "
                    "Confirme a dimensao do slot com o usuario. Nada foi cobrado.")
    if prop not in contrato.RAZOES_API:
        raise Falha("aspect_ratio %r nao esta na lista que a API aceita (%s). Use a razao "
                    "suportada mais proxima e corte na aplicacao. Nada foi cobrado."
                    % (prop, ", ".join(contrato.RAZOES_API)))
    if not tam:
        tam = "1K"
    destino = a.get("destino") or item.get("destino")

    partes = []
    for ref in a.get("referencias", []) or []:
        mime, b64 = ler_imagem(ref)
        partes.append({"inline_data": {"mime_type": mime, "data": b64}})
    partes.append({"text": a["prompt"]})

    payload = {
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": prop, "imageSize": tam},
        },
    }
    # ---- tudo que pode recusar tem de acontecer ANTES do POST: depois dele o dinheiro
    # ja saiu, e nenhuma checagem local devolve o que foi cobrado.
    redimensionar = a.get("redimensionar", True)
    if redimensionar and SEM_PILLOW:
        raise Falha(
            "Pillow nao instalada (%s), e sem ela nao da para reamostrar. Rode\n"
            "  %s -m pip install pillow\n"
            "(este e o interpretador com que o servidor MCP esta registrado -- se a maquina\n"
            "tem mais de um Python, instalar no outro nao resolve), ou chame com\n"
            "redimensionar:false. NADA foi cobrado." % (SEM_PILLOW, sys.executable))

    c = custo_imagem(modelo, tam)
    checar_teto(c, ident)
    aviso_orc = consumir_orcamento(
        a, ident, assinatura_item(ident, "imagem", modelo, tam, destino), c)
    registrar_gasto(ferramenta="gerar_imagem", id=ident, modelo=modelo, qualidade=tam,
                    custo_usd=c or 0.0, orcamento=a.get("orcamento"), destino=destino)
    try:
        resp = http("%s/models/%s:generateContent" % (API, modelo), payload, cobra=True)
    except Falha as e:
        if _sem_cobranca(e):
            estornar(ident, c, str(e)[:200])
        raise

    bruto, mime, n_cands = primeira_imagem(resp)

    # O ARQUIVO E O QUE A PAGINA PEDE. Antes daqui o destino era reconstruido como
    # <saida>/<id>.jpg, entao pasta e extensao do slot se perdiam e o asset pago caia
    # onde a pagina nao procura.
    if not destino:
        destino = "%s/%s.jpg" % (str(a.get("saida") or "public/assets").rstrip("/"), ident)
    final_abs = caminho(destino, raiz)
    pasta = os.path.dirname(final_abs)
    os.makedirs(pasta, exist_ok=True)
    ext_bruto = {"image/png": ".png", "image/jpeg": ".jpg",
                 "image/webp": ".webp"}.get(mime, ".png")
    base_sem_ext = os.path.splitext(final_abs)[0]
    sobrescrever = bool(a.get("sobrescrever"))
    original, aviso_o = livre(base_sem_ext + "-original" + ext_bruto, sobrescrever)
    with open(original, "wb") as f:
        f.write(bruto)

    linhas = ["imagem gerada e COBRADA (US$ %s): %s (%.1f MB)"
              % ("%.3f" % c if c else "?", original, len(bruto) / 1048576.0)]
    if aviso_orc:
        linhas.append(aviso_orc)
    if n_cands > 1:
        linhas.append("resposta trouxe %d candidatos; usei o primeiro." % n_cands)
    if aviso_o:
        linhas.append(aviso_o)

    if redimensionar and largura and altura:
        final, aviso_f = livre(final_abs, sobrescrever)
        formato = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}.get(
            os.path.splitext(final)[1].lower(), "JPEG")
        try:
            from PIL import ImageOps
            img = Image.open(io.BytesIO(bruto))
            if formato in ("JPEG",):
                img = img.convert("RGB")
            # RECORTA, nao estica: a API entrega na razao suportada mais proxima, e
            # forcar largura x altura deformava pessoa e objeto numa imagem ja paga
            img = ImageOps.fit(img, (int(largura), int(altura)), Image.LANCZOS,
                               centering=(0.5, 0.5))
            if formato == "JPEG":
                img.save(final, formato, quality=int(a.get("jpeg_qualidade", 80)),
                         optimize=True, progressive=True)
            else:
                img.save(final, formato)
        except Exception as e:
            raise Falha(
                "A IMAGEM FOI GERADA E COBRADA (US$ %s) e esta salva em %s. O que falhou "
                "foi o pos-processamento local: %s: %s. NAO regere -- reaproveite esse "
                "arquivo (ele conta como ja em disco no estimar_custo)."
                % ("%.3f" % c if c else "?", original, type(e).__name__, e))
        linhas.append("final: %s  %dx%d  %.0f KB" % (final, largura, altura,
                                                     os.path.getsize(final) / 1024.0))
        if aviso_f:
            linhas.append(aviso_f)
        # so descarta o -original que ESTA chamada criou num caminho antes livre
        if not a.get("manter_original", False) and not aviso_o:
            os.remove(original)
            linhas.append("(original descartado)")
        entregue = final
    else:
        entregue = original
        linhas.append("sem reamostragem: o arquivo entregue e o bruto acima; a pagina "
                      "pede %s." % destino)
    if item and alvo_plano:
        estado = dict(item.get("estado") or {})
        estado["situacao"] = "gerado"
        estado["custo_usd"] = round(float(estado.get("custo_usd") or 0) + (c or 0.0), 3)
        estado["tentativas"] = int(estado.get("tentativas") or 0) + 1
        estado["arquivo"] = contrato._posix(os.path.relpath(entregue, raiz))
        item["estado"] = estado
        gravar_plano(plano, alvo_plano)
    linhas.append("modelo %s | %s | custo ~US$ %s" % (modelo, tam,
                                                      "%.3f" % c if c else "desconhecido"))
    return "\n".join(linhas)


def t_gerar_video(a):
    _ident, item, plano, raiz, alvo_plano = _resolver(a, "video")
    modelo = a.get("modelo") or item.get("modelo") or MODELO_VIDEO
    largura = int(a.get("largura") or item.get("largura") or 1920)
    altura = int(a.get("altura") or item.get("altura") or 1080)
    # P-mcpgen-6: um job ja submetido nao pode ser submetido de novo por engano --
    # cada resubmissao e um clipe pago que ninguem vai baixar
    job_anterior = (item.get("estado") or {}).get("job")
    if job_anterior and not a.get("resubmeter"):
        raise Falha("'%s' ja tem um job submetido e PAGO: %s\n"
                    "Consulte com status_video (job=%s, id=%s). Se realmente quiser "
                    "outro clipe, passe resubmeter:true -- isso cobra de novo."
                    % (_ident, job_anterior, job_anterior, _ident))
    prop = a.get("aspect_ratio") or ("9:16" if altura > largura else "16:9")
    # 1080p+4s era o default e e justamente o par que o Veo recusa com 400; alem disso
    # o estimar_custo o cotava por metade do preco do combo que se consegue comprar
    res = a.get("resolucao") or item.get("resolucao") or "720p"
    seg = int(a.get("duracao_s") or item.get("duracao_s") or 4)
    ident = _ident
    if res == "1080p" and seg != 8:
        raise Falha(
            "o Veo so faz 1080p em 8 segundos (US$ %s); com %ss a resolucao tem de ser "
            "720p (US$ %s). Nada foi submetido nem cobrado."
            % (custo_video(modelo, "1080p", 8), seg, custo_video(modelo, "720p", seg)))
    if not shutil.which("ffmpeg") and not a.get("forcar"):
        raise Falha(
            "ffmpeg nao esta no PATH e sem ele o reencode obrigatorio (docs/video.md) nao "
            "roda: o clipe seria pago e ficaria inutilizavel para scrub por rolagem. "
            "Instale o ffmpeg, ou passe forcar:true se for preparar o mp4 por outro "
            "caminho. Nada foi cobrado.")

    inst = {"prompt": a["prompt"]}
    if a.get("imagem_inicial"):
        mime, b64 = ler_imagem(a["imagem_inicial"])
        inst["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
    params = {"aspectRatio": prop, "resolution": res, "durationSeconds": seg}
    if a.get("negative_prompt"):
        params["negativePrompt"] = a["negative_prompt"]

    c = custo_video(modelo, res, seg)
    checar_teto(c, ident)
    aviso_orc = consumir_orcamento(a, ident, assinatura_item(ident, "video", modelo,
                                                             "%ss %s" % (seg, res),
                                                             item.get("destino")), c)
    registrar_gasto(ferramenta="gerar_video", id=ident, modelo=modelo, resolucao=res,
                    duracao_s=seg, custo_usd=c or 0.0, orcamento=a.get("orcamento"))
    try:
        resp = http("%s/models/%s:predictLongRunning" % (API, modelo),
                    {"instances": [inst], "parameters": params}, cobra=True)
    except Falha as e:
        if _sem_cobranca(e):
            estornar(ident, c, str(e)[:200])
        if "duration" in str(e):
            raise Falha("%s\nO Veo 3.1 amarra resolucao e duracao: 1080p so sai em 8s; "
                        "para 4s ou 6s use resolucao 720p." % e)
        raise
    nome = resp.get("name")
    if not nome:
        raise Falha("submissao sem operacao: %s" % json.dumps(resp)[:400])
    registrar_gasto(ferramenta="gerar_video.job", id=ident, job=nome, custo_usd=0.0)
    if item and alvo_plano:
        estado = dict(item.get("estado") or {})
        estado.update({"job": nome, "situacao": "submetido",
                       "custo_usd": round(float(estado.get("custo_usd") or 0) + (c or 0), 3),
                       "tentativas": int(estado.get("tentativas") or 0) + 1})
        item["estado"] = estado
        gravar_plano(plano, alvo_plano)
    return ("job submetido: %s\nmodelo %s | %s | %ss | %s | custo ~US$ %s\n"
            "id do item: %s (passe o MESMO id em status_video, senao o mp4 cai com "
            "outro nome)\n"
            "Consulte com status_video (job=%s, id=%s). NAO resubmeta: cobra de novo.%s"
            % (nome, modelo, prop, seg, res, "%.2f" % c if c else "desconhecido",
               ident, nome, ident, "\n" + aviso_orc if aviso_orc else ""))


def t_status_video(a):
    job = a["job"]
    limite = min(int(a.get("espera_s", 30)), 55)
    fim = time.time() + limite
    d = {}
    while True:
        d = http("%s/%s" % (API, job.lstrip("/")), None, "GET")
        if d.get("done") or time.time() >= fim:
            break
        time.sleep(5)

    if not d.get("done"):
        return "ainda processando (%s). Chame status_video de novo - nao ressubmeta." % job
    if d.get("error"):
        raise Falha("job falhou: %s" % json.dumps(d["error"])[:400])

    uri = achar_uri(d.get("response") or {})
    if not uri:
        raise Falha("job concluido sem URI de video: %s" % json.dumps(d)[:600])
    if not a.get("id"):
        return "pronto. URI: %s (informe 'id' para baixar)" % uri

    if not host_google(uri):
        raise Falha("a operacao devolveu uma URI fora do dominio do Google (%s): recuso "
                    "baixar com a sua chave de API anexada." % uri)
    _i, item, plano, raiz, alvo_plano = _resolver(a, "video")
    alvo_rel = a.get("destino") or item.get("destino") \
        or "%s/%s.mp4" % (str(a.get("saida") or "public/assets").rstrip("/"), a["id"])
    base = os.path.splitext(caminho(alvo_rel, raiz))[0]
    os.makedirs(os.path.dirname(base), exist_ok=True)
    destino, aviso = livre(base + "-original.mp4", bool(a.get("sobrescrever")))
    dados = http(uri, None, "GET", bruto=True)
    with open(destino, "wb") as f:
        f.write(dados)
    return ("video baixado: %s (%.1f MB)%s\nAgora rode preparar_video para o reencode com "
            "keyframe por frame + poster (docs/video.md)."
            % (destino, len(dados) / 1048576.0, "\n" + aviso if aviso else ""))


def t_preparar_video(a):
    entrada = caminho(a["entrada"])
    if not os.path.exists(entrada):
        raise Falha("arquivo nao encontrado: %s" % entrada)
    if not shutil.which("ffmpeg"):
        raise Falha(
            "ffmpeg nao esta no PATH deste servidor. O mp4 pago ja esta em %s -- NAO "
            "regere o video. Instale o ffmpeg (winget install Gyan.FFmpeg / "
            "apt install ffmpeg / brew install ffmpeg) e rode preparar_video de novo."
            % entrada)
    saida = caminho(a.get("saida") or entrada.replace("-original.mp4", ".mp4"))
    largura = int(a.get("largura", 1440))
    fps = int(a.get("fps", 30))
    crf = int(a.get("crf", 24))
    cmd = ["ffmpeg", "-y", "-i", entrada, "-an",
           "-vf", "scale=%d:-2,fps=%d" % (largura, fps),
           "-c:v", "libx264", "-crf", str(crf), "-g", "1", "-keyint_min", "1",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", saida]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise Falha("ffmpeg falhou: %s" % p.stderr[-600:])
    linhas = ["video pronto: %s (%.1f MB, keyframe por frame)"
              % (saida, os.path.getsize(saida) / 1048576.0)]

    if a.get("poster", True):
        frame = int(a.get("frame_poster", 0))
        destino = caminho(a.get("poster_saida") or saida.replace(".mp4", "-poster.jpg"))
        # Um poster gerado a parte (Nano Banana Pro, usado como imagem_inicial do Veo) tem
        # mais resolucao e direcao de arte que o frame extraido -- e ja custou US$ 0,134.
        # A heuristica antiga olhava se "poster" veio nos argumentos, e o cliente MCP que
        # preenche defaults mandava sempre: o poster dirigido morria calado.
        if os.path.exists(destino) and not a.get("sobrescrever_poster"):
            linhas.append("poster: %s ja existe, mantido (nao sobrescrevi). Passe "
                          "sobrescrever_poster:true para extrair do clipe assim mesmo, ou "
                          "poster_saida para outro arquivo." % destino)
        else:
            pc = subprocess.run(["ffmpeg", "-y", "-i", saida, "-vf",
                                 "select=eq(n\\,%d)" % frame, "-vframes", "1",
                                 "-q:v", "4", destino], capture_output=True, text=True)
            if pc.returncode != 0:
                raise Falha("ffmpeg (poster) falhou: %s" % pc.stderr[-400:])
            linhas.append("poster: %s (frame %d, %.0f KB)"
                          % (destino, frame, os.path.getsize(destino) / 1024.0))
    if os.path.getsize(saida) > 6 * 1048576:
        linhas.append("AVISO: passou de 6 MB - reduza largura ou fps antes de subir o CRF.")
    return "\n".join(linhas)


def t_atualizar_inventario(a):
    """Regrava o inventario HTML a partir dos assets ja em disco. Nao gera nada."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gerar_midia

    plano, raiz, _ = carregar_plano(dict(a, plano=a.get("plano") or "midias.json"),
                                    obrigatorio=True)
    destino = caminho(a.get("destino") or plano.get("inventario",
                                                    "inventario_midias.html"), raiz)

    registros, faltando = [], []
    for item in plano.get("itens", []) or []:
        rel = asset_em_disco(item, raiz, plano.get("saida"))
        if rel:
            registros.append(dict(item, arquivo=caminho(rel, raiz)))
        else:
            faltando.append(item.get("id", "?"))

    plano["_faltando"] = [i for i in (plano.get("itens") or [])
                          if i.get("id") in set(faltando)]
    gerar_midia.escrever_inventario(plano, registros, destino)
    linhas = ["inventario gravado: %s (%d de %d item(ns) com arquivo em disco)"
              % (destino, len(registros), len(plano.get("itens") or []))]
    if faltando:
        # sao exatamente os itens que a PARADA 3 vai acusar: nomear aqui poupa a ida
        linhas.append("SEM ARQUIVO em disco: %s" % ", ".join(faltando))
    for aviso in plano.get("_avisos", []):
        linhas.append("plano: %s" % aviso)
    return "\n".join(linhas)


FERRAMENTAS = [
    {"name": "listar_modelos", "handler": t_listar_modelos,
     "description": ("NAO cobra. Lista os modelos de imagem e video disponiveis para esta "
                     "chave Gemini, e imprime no rodape a raiz em uso para caminhos relativos."),
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "estimar_custo", "handler": t_estimar_custo,
     "description": ("NAO cobra. Custo em USD de um plano de midia ANTES de gerar: e a "
                     "ferramenta da PARADA 2. Marca os itens que ja existem em disco e "
                     "mostra separado quanto custa gerar so o que falta."),
     "inputSchema": {"type": "object", "properties": {
         "plano": {"type": "string", "description": "caminho do midias.json (padrao: midias.json)"},
         "itens": {"type": "array", "items": {"type": "object"},
                   "description": "itens inline, no lugar do arquivo"},
         "raiz": {"type": "string",
                  "description": "raiz do projeto, quando nao for o cwd do servidor"},
         "regerar": {"type": "array", "items": {"type": "string"},
                     "description": ("ids que serao REGERADOS: entram no total mesmo ja "
                                     "existindo em disco. E o numero da rodada de correcao")}}}},

    {"name": "gerar_imagem", "handler": t_gerar_imagem,
     "description": ("COBRA na conta Google do usuario e o gasto e irreversivel: US$ 0,134 por "
                     "imagem 1K/2K no Nano Banana Pro, US$ 0,24 em 4K. So chame depois de rodar "
                     "estimar_custo, mostrar a lista ao usuario e receber aprovacao explicita "
                     "(PARADA 2). Gera uma imagem e grava no `destino` do item do plano, "
                     "reamostrada para largura x altura (sem `plano`, cai no fallback "
                     "public/assets/<id>.jpg). Um item por chamada."),
     "inputSchema": {"type": "object", "required": ["id", "prompt"], "properties": {
         "id": {"type": "string", "description": "id do item no plano"},
         "prompt": {"type": "string"},
         "plano": {"type": "string",
                   "description": ("caminho do midias.json. Passe SEMPRE que houver plano: "
                                   "e dele que sai o destino do arquivo, e sem ele a "
                                   "ferramenta cai no default public/assets")},
         "raiz": {"type": "string",
                  "description": "raiz do projeto, quando nao for o cwd do servidor"},
         "destino": {"type": "string",
                     "description": ("caminho relativo do arquivo que a PAGINA pede, com "
                                     "pasta e extensao (ex: img/hero.webp). Vence o `saida`")},
         "largura": {"type": "integer"}, "altura": {"type": "integer"},
         "modelo": {"type": "string", "description": "padrao gemini-3-pro-image-preview"},
         "qualidade": {"type": "string", "enum": ["1K", "2K", "4K"]},
         "aspect_ratio": {"type": "string",
                          "description": "forca a razao (padrao: derivada das dimensoes)"},
         "referencias": {"type": "array", "items": {"type": "string"},
                         "description": "caminhos de imagens de referencia (model sheet, expressoes)"},
         "redimensionar": {"type": "boolean",
                           "description": "padrao true: JPEG progressivo q80 no tamanho de exibicao"},
         "jpeg_qualidade": {"type": "integer"},
         "manter_original": {"type": "boolean"},
         "sobrescrever": {"type": "boolean",
                          "description": ("padrao false: arquivo existente NAO e trocado, "
                                          "o novo vira <nome>-novo.<ext>")},
         "orcamento": {"type": "string",
                       "description": "token devolvido por estimar_custo na PARADA 2"},
         "saida": {"type": "string", "description": "pasta destino (padrao public/assets)"}}}},

    {"name": "gerar_video", "handler": t_gerar_video,
     "description": ("COBRA na conta Google do usuario no momento da SUBMISSAO, mesmo que o "
                     "resultado nunca seja baixado: US$ 0,40 o clipe padrao de 4s/720p no "
                     "veo-3.1-fast, US$ 0,96 em 8s/1080p. So chame depois da PARADA 2 aprovada, "
                     "e nunca resubmeta - resubmeter cobra de novo. Devolve o id da operacao e "
                     "NAO espera terminar: consulte com status_video."),
     "inputSchema": {"type": "object", "required": ["id", "prompt"], "properties": {
         "id": {"type": "string"}, "prompt": {"type": "string"},
         "plano": {"type": "string",
                   "description": ("caminho do midias.json. Passe SEMPRE que houver plano: "
                                   "e dele que sai o destino do arquivo, e sem ele a "
                                   "ferramenta cai no default public/assets")},
         "raiz": {"type": "string",
                  "description": "raiz do projeto, quando nao for o cwd do servidor"},
         "resubmeter": {"type": "boolean",
                        "description": ("padrao false: um item que ja tem job submetido e "
                                        "PAGO nao e submetido de novo por engano")},
         "largura": {"type": "integer"}, "altura": {"type": "integer"},
         "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"]},
         "resolucao": {"type": "string", "enum": ["720p", "1080p"],
                       "description": "padrao 720p; 1080p SO existe com duracao_s 8"},
         "duracao_s": {"type": "integer", "enum": [4, 6, 8], "description": "padrao 4"},
         "orcamento": {"type": "string",
                       "description": "token devolvido por estimar_custo na PARADA 2"},
         "forcar": {"type": "boolean",
                    "description": "submete mesmo sem ffmpeg no PATH (o reencode e obrigatorio)"},
         "modelo": {"type": "string", "description": "padrao veo-3.1-fast-generate-preview"},
         "negative_prompt": {"type": "string"},
         "imagem_inicial": {"type": "string",
                            "description": "caminho de imagem para image-to-video"}}}},

    {"name": "status_video", "handler": t_status_video,
     "description": ("NAO cobra. Consulta a operacao do Veo (long-poll de ate ~55s) e, quando "
                     "pronta, baixa o mp4 para <destino do item sem extensao>-original.mp4 "
                     "(sem `plano`, cai no fallback public/assets/<id>-original.mp4). Pode devolver "
                     "'ainda processando' varias vezes: chame de novo, nao resubmeta o video."),
     "inputSchema": {"type": "object", "required": ["job"], "properties": {
         "job": {"type": "string", "description": "nome da operacao devolvido por gerar_video"},
         "plano": {"type": "string",
                   "description": ("caminho do midias.json. Passe SEMPRE que houver plano: "
                                   "e dele que sai o destino do arquivo, e sem ele a "
                                   "ferramenta cai no default public/assets")},
         "raiz": {"type": "string",
                  "description": "raiz do projeto, quando nao for o cwd do servidor"},
         "id": {"type": "string", "description": "informe para baixar o arquivo"},
         "sobrescrever": {"type": "boolean",
                          "description": "padrao false: nao troca um mp4 que ja exista"},
         "espera_s": {"type": "integer", "description": "quanto esperar nesta chamada (max 55)"},
         "saida": {"type": "string"}}}},

    {"name": "preparar_video", "handler": t_preparar_video,
     "description": ("NAO cobra. Reencode obrigatorio de docs/video.md: keyframe por frame, sem "
                     "audio, faststart, mais extracao do poster. Exige ffmpeg no PATH."),
     "inputSchema": {"type": "object", "required": ["entrada"], "properties": {
         "entrada": {"type": "string"}, "saida": {"type": "string"},
         "largura": {"type": "integer"}, "fps": {"type": "integer"}, "crf": {"type": "integer"},
         "poster": {"type": "boolean", "description": "padrao true: extrai o poster do clipe"},
         "sobrescrever_poster": {"type": "boolean",
                                 "description": ("padrao false. Um poster dirigido (gerado "
                                                 "a parte e usado como imagem_inicial) ja "
                                                 "custou US$ 0,134: nao e trocado sem isto")},
         "frame_poster": {"type": "integer"},
         "poster_saida": {"type": "string"}}}},

    {"name": "atualizar_inventario", "handler": t_atualizar_inventario,
     "description": ("NAO cobra e nao gera nada. Regrava o inventario HTML (preview, caminho, "
                     "dimensao, prompt e criterio de aceite) a partir dos assets ja em disco. "
                     "Rode ao final da Etapa 3."),
     "inputSchema": {"type": "object", "properties": {
         "plano": {"type": "string", "description": "caminho do midias.json (padrao: midias.json)"},
         "destino": {"type": "string",
                     "description": "arquivo de saida (padrao: campo 'inventario' do plano)"},
         "raiz": {"type": "string",
                  "description": "raiz do projeto, quando nao for o cwd do servidor"}}}},
]

# annotations do schema de Tool (MCP 2025-06-18): o cliente usa destructiveHint para
# decidir se pede confirmacao. As duas unicas ferramentas que gastam dinheiro sao as
# unicas em que ele importa -- e eram justamente as que nada declaravam.
ANOTACOES = {
    "listar_modelos": {"title": "Listar modelos (nao cobra)", "readOnlyHint": True,
                       "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    "estimar_custo": {"title": "Estimar custo - PARADA 2 (nao cobra)", "readOnlyHint": True,
                      "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "gerar_imagem": {"title": "Gerar imagem (COBRA ~US$ 0,134)", "readOnlyHint": False,
                     "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    "gerar_video": {"title": "Gerar video (COBRA US$ 0,40+)", "readOnlyHint": False,
                    "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    "status_video": {"title": "Status do video (nao cobra)", "readOnlyHint": False,
                     "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    "preparar_video": {"title": "Preparar video (nao cobra)", "readOnlyHint": False,
                       "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "atualizar_inventario": {"title": "Atualizar inventario (nao cobra)", "readOnlyHint": False,
                             "destructiveHint": False, "idempotentHint": True,
                             "openWorldHint": False},
}
for _f in FERRAMENTAS:
    _f["annotations"] = ANOTACOES[_f["name"]]

POR_NOME = {f["name"]: f for f in FERRAMENTAS}


# ------------------------------------------------------------------ loop JSON-RPC

def responder(msg):
    sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def tratar_mensagem(req):
    """Porta de entrada do transporte: aceita objeto, batch e recusa o resto.

    Batch faz parte de 2024-11-05 e 2025-03-26, que este servidor anuncia em
    PROTOCOLOS. Antes disto, qualquer linha de JSON valido que nao fosse dict
    matava o processo com AttributeError e o cliente perdia as sete ferramentas
    no meio da sessao -- com um job do Veo ja pago sem ninguem para consultar.
    """
    if isinstance(req, dict):
        return tratar(req)

    if isinstance(req, list):
        if not req:
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "batch JSON-RPC vazio"}}
        saidas = []
        for item in req:
            if not isinstance(item, dict):
                saidas.append({"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32600,
                                         "message": "elemento de batch nao e um objeto: %s"
                                                    % type(item).__name__}})
                continue
            r = tratar(item)
            if r is not None:
                saidas.append(r)
        return saidas or None

    return {"jsonrpc": "2.0", "id": None,
            "error": {"code": -32600,
                      "message": "mensagem JSON-RPC invalida: esperava um objeto, veio %s"
                                 % type(req).__name__}}


def tratar(req):
    metodo = req.get("method")
    ident = req.get("id")

    if metodo == "initialize":
        pedido = (req.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": ident, "result": {
            "protocolVersion": pedido if pedido in PROTOCOLOS else PROTOCOLOS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "google-midia", "version": "1.0.0"}}}

    if metodo and metodo.startswith("notifications/"):
        return None

    if metodo == "ping":
        return {"jsonrpc": "2.0", "id": ident, "result": {}}

    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": ident, "result": {"tools": [
            {k: f[k] for k in ("name", "description", "inputSchema", "annotations")
             if k in f} for f in FERRAMENTAS]}}

    if metodo == "tools/call":
        p = req.get("params") or {}
        f = POR_NOME.get(p.get("name"))
        if not f:
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": -32602,
                              "message": "ferramenta desconhecida: %s" % p.get("name")}}
        try:
            texto = f["handler"](p.get("arguments") or {})
            erro = False
        except Falha as e:
            texto, erro = "ERRO: %s" % e, True
        except Exception as e:  # o erro volta pro cliente em vez de derrubar o servidor
            texto, erro = "ERRO inesperado: %s: %s" % (type(e).__name__, e), True
        return {"jsonrpc": "2.0", "id": ident,
                "result": {"content": [{"type": "text", "text": texto}], "isError": erro}}

    if ident is None:
        return None
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": "metodo nao suportado: %s" % metodo}}


def main():
    log("mcp google-midia pronto (imagem %s / video %s)" % (MODELO_IMAGEM, MODELO_VIDEO))
    log("teto: US$ %s por chamada, US$ %s em 24h | ledger: %s"
        % (TETO_CHAMADA_USD if TETO_CHAMADA_USD is not None else "off",
           TETO_USD if TETO_USD is not None else "off", ledger()))
    log("orcamento da PARADA 2: %s"
        % ("EXIGIDO (gerar sem o token falha antes de cobrar)" if EXIGE_ORCAMENTO else
           "nao exigido -- a geracao sem aval passa e sai marcada na resposta. Ligue em "
           "/plugin (Exigir aprovacao de custo) ou com MIDIA_EXIGE_ORCAMENTO=1"))
    if SEM_PILLOW:
        log("AVISO: Pillow ausente (%s): gerar_imagem vai RECUSAR antes de cobrar"
            % SEM_PILLOW)
    if not shutil.which("ffmpeg"):
        log("AVISO: ffmpeg ausente: gerar_video e preparar_video vao RECUSAR antes de cobrar")
    for linha in sys.stdin.buffer:
        linha = linha.strip()
        if not linha:
            continue
        try:
            req = json.loads(linha.decode("utf-8"))
        except ValueError:
            continue
        try:
            resp = tratar_mensagem(req)
        except Exception as e:
            resp = {"jsonrpc": "2.0",
                    "id": req.get("id") if isinstance(req, dict) else None,
                    "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}
        if resp is not None:
            responder(resp)


if __name__ == "__main__":
    main()
