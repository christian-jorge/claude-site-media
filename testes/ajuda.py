# -*- coding: utf-8 -*-
"""Apoio comum dos testes. Stdlib pura: quem instala pelo .sh nao tem pytest.

Duas garantias que valem mais que qualquer assercao daqui:

  * nenhuma fixture versionada e escrita — `copiar_fixture` copia para um tempdir
    e o teste mexe na copia;
  * nenhum teste alcanca API paga — `rodar_script` e `instalar_duble` removem as
    chaves do ambiente, e o duble estoura se a URL nao estiver no roteiro.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
FERR = os.path.join(RAIZ, "skills", "design-to-mcp", "ferramentas")
FIXTURES = os.path.join(AQUI, "fixtures")
INSTANTANEOS = os.path.join(AQUI, "instantaneos")

CHAVES = ("GEMINI_API_KEY", "OPENAI_API_KEY", "REPLICATE_API_TOKEN")
ATUALIZAR = os.environ.get("ATUALIZAR_INSTANTANEOS", "") in ("1", "true", "sim")

if FERR not in sys.path:
    sys.path.insert(0, FERR)


# ------------------------------------------------------------------ fixtures

def copiar_fixture(caso, nome):
    """Copia a fixture para um tempdir e devolve o caminho. Limpo no fim do teste."""
    origem = os.path.join(FIXTURES, nome)
    if not os.path.isdir(origem):
        raise AssertionError("fixture inexistente: %s" % origem)
    destino = tempfile.mkdtemp(prefix="fx-%s-" % nome)
    alvo = os.path.join(destino, nome)
    shutil.copytree(origem, alvo)
    caso.addCleanup(shutil.rmtree, destino, True)
    return alvo


def ambiente_limpo(extra=None):
    env = dict(os.environ)
    for k in CHAVES:
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def rodar_script(nome, *args, **kw):
    """Roda a ferramenta como o agente roda: subprocesso, sem chave no ambiente."""
    cmd = [sys.executable, os.path.join(FERR, nome)] + [str(a) for a in args]
    return subprocess.run(cmd, cwd=kw.get("cwd"), capture_output=True,
                          env=ambiente_limpo(kw.get("env")))


def texto(proc, canal="stdout"):
    return getattr(proc, canal).decode("utf-8", "replace").replace("\r\n", "\n")


# ------------------------------------------------------------------ instantaneos

_TMP = re.compile(r"fx-[a-z0-9-]+-[a-z0-9_]{6,}", re.I)


def normalizar(txt, raiz=None):
    """Tira do texto tudo que muda entre maquinas: caminho absoluto, barra, tempdir."""
    if raiz:
        for variante in (raiz, raiz.replace("\\", "/"), raiz.replace("\\", "\\\\")):
            txt = txt.replace(variante, "<RAIZ>")
    txt = txt.replace("\\\\", "/").replace("\\", "/")
    txt = _TMP.sub("<TMP>", txt)
    txt = txt.replace(RAIZ.replace("\\", "/"), "<REPO>")
    return txt.replace("\r\n", "\n")


def comparar(caso, nome, atual):
    """Compara com o instantaneo versionado; grava e falha quando ele nao existe."""
    alvo = os.path.join(INSTANTANEOS, nome)
    os.makedirs(os.path.dirname(alvo), exist_ok=True)
    atual = atual if atual.endswith("\n") else atual + "\n"
    if ATUALIZAR or not os.path.exists(alvo):
        with io.open(alvo, "w", encoding="utf-8", newline="\n") as f:
            f.write(atual)
        if not ATUALIZAR:
            caso.fail("instantaneo criado agora: %s\nRevise o conteudo e rode de novo." % nome)
        return
    with io.open(alvo, encoding="utf-8") as f:
        esperado = f.read()
    caso.maxDiff = None
    caso.assertEqual(esperado.splitlines(), atual.splitlines(),
                     "\n%s mudou. Se a mudanca for desejada, revise o diff acima linha a "
                     "linha e regrave com:\n    python testes/rodar.py --atualizar\n" % nome)


def canonico(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ duble de rede

class RespostaFalsa(object):
    def __init__(self, corpo, status=200):
        self.corpo = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode("utf-8")
        self.status = status

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AbridorFalso(object):
    """Substitui o opener do modulo. Chamada fora do roteiro e erro, nunca requisicao."""

    def __init__(self, roteiro):
        self.roteiro = roteiro
        self.chamadas = []

    def open(self, req, timeout=None):
        url = getattr(req, "full_url", str(req))
        corpo = req.data if getattr(req, "data", None) else None
        self.chamadas.append((url, json.loads(corpo.decode("utf-8")) if corpo else None))
        for padrao, resposta in self.roteiro:
            if padrao in url:
                r = resposta(len([c for c in self.chamadas if padrao in c[0]])) \
                    if callable(resposta) else resposta
                if isinstance(r, Exception):
                    raise r
                return RespostaFalsa(r)
        raise AssertionError(
            "URL fora do roteiro do duble: %s\n"
            "nenhum teste pode alcancar a API de verdade." % url)


def instalar_duble(caso, modulo, roteiro, raiz=None):
    """Troca o opener, zera o sleep do retry e aponta a raiz para o tempdir."""
    duble = AbridorFalso(roteiro)
    anterior = getattr(modulo, "ABRIDOR", None)
    modulo.ABRIDOR = duble
    caso.addCleanup(setattr, modulo, "ABRIDOR", anterior)

    if hasattr(modulo, "time"):
        esperas = []
        dorme = modulo.time.sleep
        modulo.time.sleep = lambda s: esperas.append(s)
        caso.addCleanup(setattr, modulo.time, "sleep", dorme)
        duble.esperas = esperas

    if raiz is not None and hasattr(modulo, "RAIZ"):
        antes = modulo.RAIZ
        modulo.RAIZ = raiz
        caso.addCleanup(setattr, modulo, "RAIZ", antes)

    antes_chave = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "chave-de-teste-sem-valor"
    caso.addCleanup(lambda: os.environ.__setitem__("GEMINI_API_KEY", antes_chave)
                    if antes_chave is not None else os.environ.pop("GEMINI_API_KEY", None))
    return duble
