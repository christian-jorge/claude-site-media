#!/usr/bin/env python3
"""Gera as imagens do plano de midia e grava em public/assets/.

Uso:
    python ferramentas/gerar_midia.py midias.json --dry-run
    python ferramentas/gerar_midia.py midias.json
    python ferramentas/gerar_midia.py midias.json --only hero,feature-1 --forcar
    python ferramentas/gerar_midia.py --listar-modelos            (provedor gemini)

Provedores suportados (escolhidos no campo "provedor" do plano ou via --provedor):
    gemini     GEMINI_API_KEY      modelo: GEMINI_IMAGE_MODEL
    openai     OPENAI_API_KEY      modelo: OPENAI_IMAGE_MODEL
    replicate  REPLICATE_API_TOKEN modelo: REPLICATE_IMAGE_MODEL (owner/nome)

Somente stdlib: nao precisa de pip install.
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- utilidades

TAMANHOS_OPENAI = [(1024, 1024), (1536, 1024), (1024, 1536)]


def erro(msg):
    sys.exit("ERRO: " + msg)


def chave(nome_var):
    valor = os.environ.get(nome_var, "").strip()
    if not valor:
        erro("variavel de ambiente %s nao definida." % nome_var)
    return valor


def http_json(url, payload=None, headers=None, metodo=None, tentativas=3):
    """POST/GET JSON com retry exponencial em 429/5xx."""
    dados = json.dumps(payload).encode("utf-8") if payload is not None else None
    cabecalhos = {"Content-Type": "application/json"}
    cabecalhos.update(headers or {})

    ultimo = None
    for tentativa in range(tentativas):
        req = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:800]
            ultimo = "HTTP %s: %s" % (e.code, corpo)
            if e.code in (408, 429, 500, 502, 503, 504) and tentativa < tentativas - 1:
                espera = 2 ** tentativa * 3
                print("      ... %s, nova tentativa em %ss" % (e.code, espera))
                time.sleep(espera)
                continue
            erro(ultimo)
        except urllib.error.URLError as e:
            ultimo = "falha de rede: %s" % e.reason
            if tentativa < tentativas - 1:
                time.sleep(2 ** tentativa * 3)
                continue
            erro(ultimo)
    erro(ultimo or "falha desconhecida")


def baixar(url):
    with urllib.request.urlopen(url, timeout=300) as resp:
        return resp.read()


def ler_referencia(caminho):
    if not os.path.exists(caminho):
        erro("imagem de referencia nao encontrada: %s" % caminho)
    tipo = mimetypes.guess_type(caminho)[0] or "image/png"
    with open(caminho, "rb") as f:
        return tipo, base64.b64encode(f.read()).decode("ascii")


def tamanho_openai(largura, altura):
    """Escolhe o tamanho suportado mais proximo do aspect ratio pedido."""
    alvo = largura / float(altura or 1)
    melhor = min(TAMANHOS_OPENAI, key=lambda t: abs(t[0] / float(t[1]) - alvo))
    return "%dx%d" % melhor


# ---------------------------------------------------------------- provedores

def gerar_gemini(item, referencias):
    modelo = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
           % (modelo, chave("GEMINI_API_KEY")))

    partes = []
    for ref in referencias:
        tipo, b64 = ler_referencia(ref)
        partes.append({"inline_data": {"mime_type": tipo, "data": b64}})
    partes.append({"text": item["prompt"]})

    payload = {
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    resposta = http_json(url, payload)

    for candidato in resposta.get("candidates", []):
        for parte in candidato.get("content", {}).get("parts", []):
            inline = parte.get("inlineData") or parte.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime
    erro("o Gemini nao retornou imagem. Resposta: %s" % json.dumps(resposta)[:600])


def gerar_openai(item, referencias):
    if referencias:
        print("      aviso: referencias de imagem sao ignoradas neste endpoint do OpenAI")
    modelo = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    payload = {
        "model": modelo,
        "prompt": item["prompt"],
        "size": tamanho_openai(item.get("largura", 1024), item.get("altura", 1024)),
        "n": 1,
    }
    resposta = http_json(
        "https://api.openai.com/v1/images/generations",
        payload,
        {"Authorization": "Bearer " + chave("OPENAI_API_KEY")},
    )
    dados = (resposta.get("data") or [{}])[0]
    if dados.get("b64_json"):
        return base64.b64decode(dados["b64_json"]), "image/png"
    if dados.get("url"):
        return baixar(dados["url"]), "image/png"
    erro("o OpenAI nao retornou imagem. Resposta: %s" % json.dumps(resposta)[:600])


def gerar_replicate(item, referencias):
    modelo = os.environ.get("REPLICATE_IMAGE_MODEL", "black-forest-labs/flux-1.1-pro")
    entrada = {
        "prompt": item["prompt"],
        "aspect_ratio": item.get("aspect_ratio", "custom"),
        "width": item.get("largura"),
        "height": item.get("altura"),
    }
    entrada = {k: v for k, v in entrada.items() if v is not None}
    if referencias:
        tipo, b64 = ler_referencia(referencias[0])
        entrada["image_prompt"] = "data:%s;base64,%s" % (tipo, b64)

    resposta = http_json(
        "https://api.replicate.com/v1/models/%s/predictions" % modelo,
        {"input": entrada},
        {"Authorization": "Bearer " + chave("REPLICATE_API_TOKEN"), "Prefer": "wait"},
    )

    # Prefer: wait cobre a maioria dos casos; se ainda estiver rodando, faz polling.
    while resposta.get("status") in ("starting", "processing"):
        time.sleep(3)
        resposta = http_json(resposta["urls"]["get"], None,
                             {"Authorization": "Bearer " + chave("REPLICATE_API_TOKEN")})

    if resposta.get("status") != "succeeded":
        erro("Replicate falhou (%s): %s" % (resposta.get("status"), resposta.get("error")))

    saida = resposta.get("output")
    url = saida[0] if isinstance(saida, list) else saida
    if not url:
        erro("Replicate nao retornou URL de saida.")
    return baixar(url), "image/png"


PROVEDORES = {"gemini": gerar_gemini, "openai": gerar_openai, "replicate": gerar_replicate}


def listar_modelos_gemini():
    resposta = http_json(
        "https://generativelanguage.googleapis.com/v1beta/models?key=%s&pageSize=200"
        % chave("GEMINI_API_KEY"), None, None, "GET")
    print("Modelos disponiveis que geram imagem:\n")
    for m in resposta.get("models", []):
        nome = m.get("name", "").replace("models/", "")
        if "image" in nome or "IMAGE" in str(m.get("supportedGenerationMethods", "")):
            print("  %-42s %s" % (nome, m.get("displayName", "")))
    print("\nDefina o escolhido com:  setx GEMINI_IMAGE_MODEL \"<nome>\"")


# ---------------------------------------------------------------- orquestracao

def extensao(mime):
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".png")


VIDEO_EXT = (".mp4", ".webm", ".mov")


def preview(rel, ident, base_dir):
    """Celula de preview do inventario: <video> para mp4, <img> para o resto."""
    if not rel.lower().endswith(VIDEO_EXT):
        return "<img src=\"%s\" alt=\"%s\" loading=\"lazy\">" % (rel, ident)
    poster = ""
    for cand in (rel.rsplit(".", 1)[0] + "-poster.jpg", rel.rsplit("-", 1)[0] + "-poster.jpg"):
        if os.path.exists(os.path.join(base_dir, cand)):
            poster = " poster=\"%s\"" % cand
            break
    return ("<video src=\"%s\"%s muted playsinline loop autoplay preload=\"metadata\">"
            "</video>" % (rel, poster))


def escrever_inventario(plano, registros, destino):
    linhas = [
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Inventario de midias</title><style>",
        "body{font:15px/1.55 system-ui,sans-serif;margin:0;padding:32px;background:#0f1115;color:#e8eaf0}",
        "h1{font-size:22px;margin:0 0 4px}p.sub{color:#98a2b3;margin:0 0 28px}",
        "table{border-collapse:collapse;width:100%;max-width:1200px}",
        "th,td{border-bottom:1px solid #232733;padding:12px;text-align:left;vertical-align:top}",
        "th{color:#98a2b3;font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.04em}",
        "img,video{max-width:220px;height:auto;border-radius:8px;display:block;background:#1a1d26}",
        "code{background:#1a1d26;padding:2px 6px;border-radius:4px;font-size:13px}",
        ".prompt{color:#c3c8d4;font-size:13px;max-width:520px}",
        ".aceite{display:block;margin-top:10px;color:#8fd6a8;font-size:12px}",
        ".aceite b{color:#5fb37f;font-weight:600;text-transform:uppercase;letter-spacing:.04em}",
        "</style></head><body>",
        "<h1>Inventario de midias</h1>",
        "<p class=\"sub\">Provedor: <code>%s</code> &middot; %d asset(s)</p>"
        % (plano["provedor"], len(registros)),
        "<table><tr><th>Preview</th><th>ID / arquivo</th><th>Dimensao alvo</th><th>Prompt</th></tr>",
    ]
    base_dir = os.path.dirname(destino) or "."
    for r in registros:
        rel = os.path.relpath(r["arquivo"], base_dir).replace("\\", "/")
        prompt = r["prompt"].replace("&", "&amp;").replace("<", "&lt;")
        if r.get("aceite"):
            prompt += ("<span class=\"aceite\"><b>aceite</b> &middot; %s</span>"
                       % r["aceite"].replace("&", "&amp;").replace("<", "&lt;"))
        linhas.append(
            "<tr><td>%s</td>"
            "<td><strong>%s</strong><br><code>%s</code></td>"
            "<td>%s&times;%s</td><td class=\"prompt\">%s</td></tr>"
            % (preview(rel, r["id"], base_dir), r["id"], rel,
               r.get("largura", "?"), r.get("altura", "?"), prompt)
        )
    linhas.append("</table></body></html>")

    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    # Sem print: o servidor MCP chama esta funcao e qualquer coisa no stdout
    # quebra o JSON-RPC. Quem chama decide se e como reporta.
    return destino


def achar_asset(saida, item):
    """Arquivo ja gravado para o item, ou None. Video procura .mp4 antes do original."""
    base = os.path.join(saida, item["id"])
    exts = (".mp4", ".webm") if item.get("tipo") == "video" else (".jpg", ".png", ".webp")
    return next((base + e for e in exts if os.path.exists(base + e)), None)


def main():
    ap = argparse.ArgumentParser(description="Gera as midias do plano.")
    ap.add_argument("plano", nargs="?", help="caminho do midias.json")
    ap.add_argument("--provedor", choices=sorted(PROVEDORES), help="sobrescreve o provedor do plano")
    ap.add_argument("--only", help="lista de ids separados por virgula")
    ap.add_argument("--dry-run", action="store_true", help="so lista o que seria gerado")
    ap.add_argument("--so-inventario", action="store_true",
                    help="regrava o inventario a partir dos assets ja em disco, sem gerar nada")
    ap.add_argument("--forcar", action="store_true", help="regera assets que ja existem")
    ap.add_argument("--listar-modelos", action="store_true", help="lista modelos de imagem do Gemini")
    args = ap.parse_args()

    if args.listar_modelos:
        return listar_modelos_gemini()
    if not args.plano:
        ap.error("informe o caminho do plano (midias.json) ou use --listar-modelos")
    if not os.path.exists(args.plano):
        erro("plano '%s' nao encontrado." % args.plano)

    with open(args.plano, "r", encoding="utf-8") as f:
        plano = json.load(f)

    plano["provedor"] = args.provedor or plano.get("provedor", "gemini")

    # "google-midia" e servido pelo MCP, nao por este script. O plano ainda e valido
    # para revisao (--dry-run) e para regravar o inventario (--so-inventario);
    # so a geracao precisa de um provedor de API.
    if plano["provedor"] not in PROVEDORES and not (args.dry_run or args.so_inventario):
        if plano["provedor"] == "google-midia":
            erro("o provedor 'google-midia' e servido pelo MCP, nao por este script.\n"
                 "       Gere pelas ferramentas mcp__google-midia__* dentro do Claude Code,\n"
                 "       ou use este script como fallback: --provedor gemini|openai|replicate")
        erro("provedor '%s' desconhecido. Use: %s"
             % (plano["provedor"], ", ".join(sorted(PROVEDORES))))

    saida = plano.get("saida", "public/assets")
    os.makedirs(saida, exist_ok=True)

    itens = plano.get("itens", [])
    if args.only:
        alvo = {i.strip() for i in args.only.split(",")}
        itens = [i for i in itens if i["id"] in alvo]
    if not itens:
        erro("nenhum item a gerar.")

    if args.so_inventario:
        registros, faltando = [], []
        for item in itens:
            arquivo = achar_asset(saida, item)
            (registros.append(dict(item, arquivo=arquivo)) if arquivo
             else faltando.append(item["id"]))
        if faltando:
            print("aviso: %d item(ns) sem arquivo em disco, fora do inventario: %s"
                  % (len(faltando), ", ".join(faltando)))
        alvo = escrever_inventario(plano, registros,
                                   plano.get("inventario", "inventario_midias.html"))
        print("Inventario gravado em %s" % alvo)
        print("[so-inventario] %d asset(s) listados. Nada foi gerado nem cobrado."
              % len(registros))
        return

    print("Provedor: %s" % plano["provedor"])
    print("Saida:    %s" % saida)
    print("Itens:    %d\n" % len(itens))
    so_imagem = plano["provedor"] in PROVEDORES
    videos = [it["id"] for it in itens if it.get("tipo") == "video"]
    cobrados = []
    for i, item in enumerate(itens, 1):
        e_video = item.get("tipo") == "video"
        existe = achar_asset(saida, item)
        if e_video and so_imagem:
            marca = "  [video - pulado por este provedor]"
        elif existe and not args.forcar:
            marca = "  [ja existe - pulado]"
        else:
            marca = "  [video]" if e_video else ""
            cobrados.append(item["id"])
        print("  %2d. %-22s %sx%s%s"
              % (i, item["id"], item.get("largura", "?"), item.get("altura", "?"), marca))
        print("      %s" % item["prompt"][:150])
    if videos and so_imagem:
        print("\n  aviso: o provedor '%s' so gera imagem. %d item(ns) de video serao pulados: %s"
              % (plano["provedor"], len(videos), ", ".join(videos)))
        print("         gere video pelas ferramentas mcp__google-midia__* (Veo 3.1).")

    if args.dry_run:
        # So conta o que seria realmente chamado: item que ja tem arquivo em disco e
        # pulado (sem --forcar) e nao cobra. Este numero vai para a PARADA 2.
        print("\n[dry-run] %d geracao(oes) seriam cobradas%s. Nada foi chamado."
              % (len(cobrados), (": " + ", ".join(cobrados)) if cobrados else ""))
        if len(cobrados) < len(itens):
            print("          %d item(ns) ja em disco ou fora deste provedor. "
                  "Use --forcar para regerar." % (len(itens) - len(cobrados)))
        return

    gerar = PROVEDORES[plano["provedor"]]
    refs_globais = plano.get("referencias", [])
    registros = []

    for i, item in enumerate(itens, 1):
        if item.get("tipo") == "video":
            print("\n[%d/%d] %s -> video: este script so gera imagem, pulando."
                  % (i, len(itens), item["id"]))
            continue
        destino_base = os.path.join(saida, item["id"])
        existentes = [destino_base + e for e in (".png", ".jpg", ".webp")
                      if os.path.exists(destino_base + e)]
        if existentes and not args.forcar:
            print("\n[%d/%d] %s -> ja existe (%s), pulando. Use --forcar para regerar."
                  % (i, len(itens), item["id"], os.path.basename(existentes[0])))
            registros.append(dict(item, arquivo=existentes[0]))
            continue

        refs = list(refs_globais) + list(item.get("referencias", []))
        print("\n[%d/%d] gerando %s ..." % (i, len(itens), item["id"]))
        blob, mime = gerar(item, refs)
        arquivo = destino_base + extensao(mime)
        with open(arquivo, "wb") as f:
            f.write(blob)
        print("      OK -> %s (%.1f KB)" % (arquivo, len(blob) / 1024.0))
        registros.append(dict(item, arquivo=arquivo))

    alvo = escrever_inventario(plano, registros,
                               plano.get("inventario", "inventario_midias.html"))
    print("\nInventario gravado em %s" % alvo)


if __name__ == "__main__":
    main()
