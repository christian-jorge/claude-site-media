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
import io
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Raiz para caminhos relativos: o projeto onde o Claude Code foi aberto, NAO a pasta do
# script. Instalada em ~/.claude/skills/, a skill escreveria os assets dentro dela mesma.
# MIDIA_RAIZ existe para o caso de o cliente subir o servidor com outro cwd.
RAIZ = os.path.abspath(os.environ.get("MIDIA_RAIZ") or os.getcwd())
API = "https://generativelanguage.googleapis.com/v1beta"
PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")

MODELO_IMAGEM = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
MODELO_VIDEO = os.environ.get("GEMINI_VIDEO_MODEL", "veo-3.1-fast-generate-preview")

# ai.google.dev/gemini-api/docs/pricing (consultado em 20/08/2026), USD.
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
RAZOES = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


# ------------------------------------------------------------------ util

def log(msg):
    print(msg, file=sys.stderr, flush=True)


class Falha(Exception):
    pass


def api_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        raise Falha("GEMINI_API_KEY nao definida no ambiente do servidor MCP.")
    return k


def http(url, payload=None, metodo=None, tentativas=3, bruto=False):
    dados = json.dumps(payload).encode("utf-8") if payload is not None else None
    cab = {"x-goog-api-key": api_key()}
    if dados:
        cab["Content-Type"] = "application/json"
    ultimo = None
    for t in range(tentativas):
        req = urllib.request.Request(url, data=dados, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                corpo = r.read()
                return corpo if bruto else json.loads(corpo.decode("utf-8"))
        except urllib.error.HTTPError as e:
            ultimo = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:600])
            if e.code in (408, 429, 500, 502, 503, 504) and t < tentativas - 1:
                time.sleep(2 ** t * 3)
                continue
            raise Falha(ultimo)
        except urllib.error.URLError as e:
            ultimo = "rede: %s" % e.reason
            if t < tentativas - 1:
                time.sleep(2 ** t * 3)
                continue
            raise Falha(ultimo)
    raise Falha(ultimo or "falha desconhecida")


def caminho(p):
    return p if os.path.isabs(p) else os.path.join(RAIZ, p)


def familia(modelo):
    return modelo.replace("-preview", "")


def razao(largura, altura):
    alvo = float(largura) / float(altura or 1)

    def dist(r):
        a, b = r.split(":")
        return abs(float(a) / float(b) - alvo)

    return min(RAZOES, key=dist)


def tamanho_imagem(largura, altura):
    maior = max(int(largura or 0), int(altura or 0))
    if maior <= 1024:
        return "1K"
    if maior <= 2048:
        return "2K"
    return "4K"


def custo_imagem(modelo, tam):
    return CUSTO_IMAGEM.get(familia(modelo), {}).get(tam)


def custo_video(modelo, resolucao, segundos):
    por_s = CUSTO_VIDEO_S.get(familia(modelo), {}).get(resolucao)
    return None if por_s is None else round(por_s * float(segundos), 3)


def ler_imagem(p):
    p = caminho(p)
    if not os.path.exists(p):
        raise Falha("referencia nao encontrada: %s" % p)
    mime = mimetypes.guess_type(p)[0] or "image/png"
    with open(p, "rb") as f:
        return mime, base64.b64encode(f.read()).decode("ascii")


def achar_uri(no):
    """Varre a resposta da operacao do Veo procurando a URI do mp4."""
    if isinstance(no, dict):
        for k, v in no.items():
            if k in ("uri", "url") and isinstance(v, str) and v.startswith("http"):
                return v
            achou = achar_uri(v)
            if achou:
                return achou
    elif isinstance(no, list):
        for item in no:
            achou = achar_uri(item)
            if achou:
                return achou
    return None


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


def asset_em_disco(saida, item):
    """Arquivo ja gravado para o item, ou None."""
    base = os.path.join(saida, item.get("id", ""))
    exts = (".mp4", ".webm") if item.get("tipo") == "video" else (".jpg", ".png", ".webp")
    return next((base + e for e in exts if os.path.exists(base + e)), None)


def t_estimar_custo(a):
    itens = a.get("itens")
    saida = caminho("public/assets")
    if not itens:
        plano = json.load(open(caminho(a.get("plano", "midias.json")), encoding="utf-8"))
        itens = plano.get("itens", [])
        saida = caminho(plano.get("saida", "public/assets"))
    linhas, total, incerto = [], 0.0, False
    ja_existem, gasto_repetido = [], 0.0
    for it in itens:
        if it.get("tipo") == "video":
            modelo = it.get("modelo", MODELO_VIDEO)
            res = it.get("resolucao", "1080p")
            seg = it.get("duracao_s", 4)
            c = custo_video(modelo, res, seg)
            desc = "%s %ss %s" % (modelo, seg, res)
        else:
            modelo = it.get("modelo", MODELO_IMAGEM)
            tam = it.get("qualidade") or tamanho_imagem(it.get("largura", 1024),
                                                        it.get("altura", 1024))
            c = custo_imagem(modelo, tam)
            desc = "%s %s" % (modelo, tam)
        existe = asset_em_disco(saida, it)
        if existe:
            ja_existem.append(it.get("id", "?"))
            gasto_repetido += c or 0.0
        marca = "  <- ja existe em disco" if existe else ""
        if c is None:
            incerto = True
            linhas.append("  %-16s %-46s custo desconhecido%s" % (it.get("id", "?"), desc, marca))
        else:
            total += c
            linhas.append("  %-16s %-46s US$ %.3f%s" % (it.get("id", "?"), desc, c, marca))
    rodape = "\nTOTAL ESTIMADO: US$ %.2f em %d itens" % (total, len(itens))
    if ja_existem:
        rodape += ("\nDESTE TOTAL, US$ %.2f em %d item(ns) que JA EXISTEM em disco (%s):"
                   " so cobre de novo se a intencao for regerar."
                   % (gasto_repetido, len(ja_existem), ", ".join(ja_existem)))
        rodape += "\nGerar so o que falta custa US$ %.2f." % (total - gasto_repetido)
    if incerto:
        rodape += "\n(itens sem preco na tabela nao entram no total)"
    return "\n".join(linhas) + rodape


def t_gerar_imagem(a):
    ident = a["id"]
    modelo = a.get("modelo", MODELO_IMAGEM)
    largura, altura = int(a.get("largura", 1024)), int(a.get("altura", 1024))
    tam = a.get("qualidade") or tamanho_imagem(largura, altura)

    partes = []
    for ref in a.get("referencias", []) or []:
        mime, b64 = ler_imagem(ref)
        partes.append({"inline_data": {"mime_type": mime, "data": b64}})
    partes.append({"text": a["prompt"]})

    payload = {
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": a.get("aspect_ratio") or razao(largura, altura),
                            "imageSize": tam},
        },
    }
    resp = http("%s/models/%s:generateContent" % (API, modelo), payload)

    bruto = mime = None
    for cand in resp.get("candidates", []):
        for parte in cand.get("content", {}).get("parts", []):
            inline = parte.get("inlineData") or parte.get("inline_data")
            if inline and inline.get("data"):
                bruto = base64.b64decode(inline["data"])
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                break
    if not bruto:
        raise Falha("resposta sem imagem: %s" % json.dumps(resp)[:600])

    pasta = caminho(a.get("saida", "public/assets"))
    os.makedirs(pasta, exist_ok=True)
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".png")
    original = os.path.join(pasta, ident + "-original" + ext)
    with open(original, "wb") as f:
        f.write(bruto)

    linhas = ["imagem gerada: %s (%.1f MB)" % (original, len(bruto) / 1048576.0)]
    if a.get("redimensionar", True):
        from PIL import Image
        img = Image.open(io.BytesIO(bruto)).convert("RGB")
        img = img.resize((largura, altura), Image.LANCZOS)
        final = os.path.join(pasta, ident + ".jpg")
        img.save(final, "JPEG", quality=int(a.get("jpeg_qualidade", 80)),
                 optimize=True, progressive=True)
        linhas.append("final: %s  %dx%d  %.0f KB" % (final, largura, altura,
                                                     os.path.getsize(final) / 1024.0))
        if not a.get("manter_original", False):
            os.remove(original)
            linhas.append("(original descartado)")
    c = custo_imagem(modelo, tam)
    linhas.append("modelo %s | %s | custo ~US$ %s" % (modelo, tam,
                                                      "%.3f" % c if c else "desconhecido"))
    return "\n".join(linhas)


def t_gerar_video(a):
    modelo = a.get("modelo", MODELO_VIDEO)
    largura, altura = int(a.get("largura", 1920)), int(a.get("altura", 1080))
    prop = a.get("aspect_ratio") or ("9:16" if altura > largura else "16:9")
    res = a.get("resolucao", "1080p")
    seg = int(a.get("duracao_s", 4))

    inst = {"prompt": a["prompt"]}
    if a.get("imagem_inicial"):
        mime, b64 = ler_imagem(a["imagem_inicial"])
        inst["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
    params = {"aspectRatio": prop, "resolution": res, "durationSeconds": seg}
    if a.get("negative_prompt"):
        params["negativePrompt"] = a["negative_prompt"]

    try:
        resp = http("%s/models/%s:predictLongRunning" % (API, modelo),
                    {"instances": [inst], "parameters": params})
    except Falha as e:
        if "duration" in str(e):
            raise Falha("%s\nO Veo 3.1 amarra resolucao e duracao: 1080p so sai em 8s; "
                        "para 4s ou 6s use resolucao 720p." % e)
        raise
    nome = resp.get("name")
    if not nome:
        raise Falha("submissao sem operacao: %s" % json.dumps(resp)[:400])
    c = custo_video(modelo, res, seg)
    return ("job submetido: %s\nmodelo %s | %s | %ss | %s | custo ~US$ %s\n"
            "Consulte com status_video (job=%s). NAO resubmeta: cobra de novo."
            % (nome, modelo, prop, seg, res, "%.2f" % c if c else "desconhecido", nome))


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

    pasta = caminho(a.get("saida", "public/assets"))
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, a["id"] + "-original.mp4")
    dados = http(uri, None, "GET", bruto=True)
    with open(destino, "wb") as f:
        f.write(dados)
    return ("video baixado: %s (%.1f MB)\nAgora rode preparar_video para o reencode com "
            "keyframe por frame + poster (docs/video.md)." % (destino, len(dados) / 1048576.0))


def t_preparar_video(a):
    entrada = caminho(a["entrada"])
    if not os.path.exists(entrada):
        raise Falha("arquivo nao encontrado: %s" % entrada)
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
        # mais resolucao e direcao de arte que o frame extraido. Nao sobrescreve sozinho.
        if os.path.exists(destino) and "poster" not in a and not a.get("poster_saida"):
            linhas.append("poster: %s ja existe, mantido (nao sobrescrevi). Passe poster:true "
                          "para extrair do clipe assim mesmo, ou poster_saida para outro arquivo."
                          % destino)
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

    caminho_plano = caminho(a.get("plano") or "midias.json")
    if not os.path.exists(caminho_plano):
        raise Falha("plano nao encontrado: %s" % caminho_plano)
    with open(caminho_plano, "r", encoding="utf-8") as f:
        plano = json.load(f)

    saida = caminho(plano.get("saida", "public/assets"))
    destino = caminho(a.get("destino") or plano.get("inventario", "inventario_midias.html"))

    registros, faltando = [], []
    for item in plano.get("itens", []):
        arquivo = gerar_midia.achar_asset(saida, item)
        if arquivo:
            registros.append(dict(item, arquivo=arquivo))
        else:
            faltando.append(item["id"])

    gerar_midia.escrever_inventario(plano, registros, destino)
    linhas = ["inventario gravado: %s (%d asset(s))" % (destino, len(registros))]
    if faltando:
        linhas.append("sem arquivo em disco, fora da lista: %s" % ", ".join(faltando))
    return "\n".join(linhas)


FERRAMENTAS = [
    {"name": "listar_modelos", "handler": t_listar_modelos,
     "description": "Lista os modelos de imagem e video disponiveis para esta chave Gemini.",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "estimar_custo", "handler": t_estimar_custo,
     "description": "Custo em USD de um plano de midia antes de gerar. Use na PARADA 2.",
     "inputSchema": {"type": "object", "properties": {
         "plano": {"type": "string", "description": "caminho do midias.json (padrao: midias.json)"},
         "itens": {"type": "array", "items": {"type": "object"},
                   "description": "itens inline, no lugar do arquivo"}}}},

    {"name": "gerar_imagem", "handler": t_gerar_imagem,
     "description": ("Gera uma imagem (Nano Banana Pro por padrao), salva em public/assets/<id>.jpg "
                     "ja reamostrada para largura x altura. Um item por chamada."),
     "inputSchema": {"type": "object", "required": ["id", "prompt"], "properties": {
         "id": {"type": "string", "description": "vira o nome do arquivo"},
         "prompt": {"type": "string"},
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
         "saida": {"type": "string", "description": "pasta destino (padrao public/assets)"}}}},

    {"name": "gerar_video", "handler": t_gerar_video,
     "description": ("Submete um job de video no Veo 3.1 e devolve o id da operacao. "
                     "NAO espera terminar - consulte com status_video."),
     "inputSchema": {"type": "object", "required": ["id", "prompt"], "properties": {
         "id": {"type": "string"}, "prompt": {"type": "string"},
         "largura": {"type": "integer"}, "altura": {"type": "integer"},
         "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"]},
         "resolucao": {"type": "string", "enum": ["720p", "1080p"]},
         "duracao_s": {"type": "integer", "enum": [4, 6, 8]},
         "modelo": {"type": "string", "description": "padrao veo-3.1-fast-generate-preview"},
         "negative_prompt": {"type": "string"},
         "imagem_inicial": {"type": "string",
                            "description": "caminho de imagem para image-to-video"}}}},

    {"name": "status_video", "handler": t_status_video,
     "description": ("Consulta a operacao do Veo (long-poll de ate ~55s) e, quando pronta, baixa o "
                     "mp4 para public/assets/<id>-original.mp4."),
     "inputSchema": {"type": "object", "required": ["job"], "properties": {
         "job": {"type": "string", "description": "nome da operacao devolvido por gerar_video"},
         "id": {"type": "string", "description": "informe para baixar o arquivo"},
         "espera_s": {"type": "integer", "description": "quanto esperar nesta chamada (max 55)"},
         "saida": {"type": "string"}}}},

    {"name": "preparar_video", "handler": t_preparar_video,
     "description": ("Reencode obrigatorio de docs/video.md: keyframe por frame, sem audio, "
                     "faststart, mais extracao do poster."),
     "inputSchema": {"type": "object", "required": ["entrada"], "properties": {
         "entrada": {"type": "string"}, "saida": {"type": "string"},
         "largura": {"type": "integer"}, "fps": {"type": "integer"}, "crf": {"type": "integer"},
         "poster": {"type": "boolean",
                    "description": ("padrao true, mas nao sobrescreve um poster que ja exista - "
                                    "passe true explicito para forcar")},
         "frame_poster": {"type": "integer"},
         "poster_saida": {"type": "string"}}}},

    {"name": "atualizar_inventario", "handler": t_atualizar_inventario,
     "description": ("Regrava o inventario HTML (preview, caminho, dimensao, prompt e criterio de "
                     "aceite) a partir dos assets ja em disco. Nao gera nada, nao cobra. "
                     "Rode ao final da Etapa 3."),
     "inputSchema": {"type": "object", "properties": {
         "plano": {"type": "string", "description": "caminho do midias.json (padrao: midias.json)"},
         "destino": {"type": "string",
                     "description": "arquivo de saida (padrao: campo 'inventario' do plano)"}}}},
]
POR_NOME = {f["name"]: f for f in FERRAMENTAS}


# ------------------------------------------------------------------ loop JSON-RPC

def responder(msg):
    sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


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
            {k: f[k] for k in ("name", "description", "inputSchema")} for f in FERRAMENTAS]}}

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
    for linha in sys.stdin.buffer:
        linha = linha.strip()
        if not linha:
            continue
        try:
            req = json.loads(linha.decode("utf-8"))
        except ValueError:
            continue
        try:
            resp = tratar(req)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}
        if resp is not None:
            responder(resp)


if __name__ == "__main__":
    main()
