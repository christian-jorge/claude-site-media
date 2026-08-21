# -*- coding: utf-8 -*-
"""P-tst-5 — as ferramentas do MCP contra um dublê de rede.

O corte e no opener (`modulo.ABRIDOR`), nao em `http()`: o retry, a lista de
codigos que repete e o timeout moram DENTRO de http(), e interceptar mais acima
deixaria justamente isso sem teste.

Nenhum teste alcanca a API: URL fora do roteiro estoura AssertionError.
"""
import base64
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import urllib.error

import ajuda

import mcp_google_midia as M

GERAR = ":generateContent"
VIDEO = ":predictLongRunning"


def png(cor=(20, 90, 60), tam=(64, 48)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", tam, cor).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def resposta_imagem(dados=None):
    return json.dumps({"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "image/png", "data": dados or png()}}]}}]}).encode()


def erro_http(code, corpo=b'{"error":{"message":"simulado"}}'):
    return urllib.error.HTTPError("http://x", code, "simulado", {}, io.BytesIO(corpo))


try:
    from PIL import Image  # noqa: F401
    TEM_PILLOW = True
except ImportError:
    TEM_PILLOW = False


class Base(unittest.TestCase):
    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="fx-mcp-")
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.ledger = os.path.join(self.raiz, "gastos.jsonl")
        os.environ["MIDIA_LEDGER"] = self.ledger
        self.addCleanup(os.environ.pop, "MIDIA_LEDGER", None)
        self.teto = M.TETO_USD
        M.TETO_USD = None                      # o teto tem teste proprio
        self.addCleanup(setattr, M, "TETO_USD", self.teto)

    def duble(self, roteiro):
        return ajuda.instalar_duble(self, M, roteiro, raiz=self.raiz)

    def item(self, **kw):
        base = dict(id="hero", prompt="uma cena", largura=1600, altura=900)
        base.update(kw)
        return base


class Imagem(Base):

    def test_o_corpo_enviado_carrega_o_que_decide_preco(self):
        d = self.duble([(GERAR, resposta_imagem())])
        M.t_gerar_imagem(self.item(redimensionar=False))
        _, corpo = d.chamadas[0]
        cfg = corpo["generationConfig"]["imageConfig"]
        self.assertEqual(cfg["aspectRatio"], "16:9")
        self.assertEqual(cfg["imageSize"], "2K", "1600x900 tem de cair na faixa 2K")

    @unittest.skipUnless(TEM_PILLOW, "sem Pillow")
    def test_reamostra_para_o_tamanho_de_exibicao(self):
        self.duble([(GERAR, resposta_imagem())])
        M.t_gerar_imagem(self.item(largura=320, altura=200))
        final = os.path.join(self.raiz, "public", "assets", "hero.jpg")
        self.assertTrue(os.path.exists(final))
        self.assertEqual(Image.open(final).size, (320, 200))
        self.assertFalse(os.path.exists(os.path.join(self.raiz, "public", "assets",
                                                     "hero-original.png")),
                         "o -original desta chamada devia ter sido descartado")

    def test_resposta_sem_imagem_vira_falha_legivel(self):
        """Bloqueio de conteudo e a unica falha que acontece DEPOIS do POST.

        A mensagem antiga era um dump de JSON: passava neste teste porque o dump
        contem a string, e nao dizia nem que o dinheiro ja tinha saido nem que
        repetir seria recusado de novo -- as duas coisas que decidem o proximo passo.
        """
        self.duble([(GERAR, json.dumps({"candidates": [
            {"finishReason": "IMAGE_SAFETY", "content": {"parts": []}}]}).encode())])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item())
        msg = str(e.exception)
        self.assertIn("IMAGE_SAFETY", msg)
        self.assertIn("recusa de CONTEUDO", msg,
                      "sem isto o palpite natural e repetir a mesma chamada")
        self.assertIn("PAGA", msg, "a chamada passou do POST: tratar como paga")
        # e a mensagem tem de ser verdade: a linha existe mesmo no ledger
        linhas = [l for l in open(self.ledger, encoding="utf-8").read().splitlines() if l]
        self.assertEqual(len(linhas), 1)

    def test_falha_tecnica_sem_imagem_nao_acusa_bloqueio(self):
        """Nem toda resposta sem imagem e censura: dizer que e manda reescrever a toa."""
        self.duble([(GERAR, json.dumps({"candidates": [
            {"finishReason": "MAX_TOKENS",
             "content": {"parts": [{"text": "nao consegui gerar"}]}}]}).encode())])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item())
        msg = str(e.exception)
        self.assertIn("MAX_TOKENS", msg)
        self.assertNotIn("recusa de CONTEUDO", msg)
        self.assertIn("nao consegui gerar", msg,
                      "o texto que o modelo devolveu no lugar da imagem e o diagnostico")

    def test_bloqueio_no_prompt_tambem_e_lido(self):
        """A recusa pode vir em promptFeedback, antes de haver candidato."""
        self.duble([(GERAR, json.dumps(
            {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT",
                                "blockReasonMessage": "pedido recusado"}}).encode())])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item())
        msg = str(e.exception)
        self.assertIn("PROHIBITED_CONTENT", msg)
        self.assertIn("recusa de CONTEUDO", msg)
        self.assertIn("pedido recusado", msg)

    def test_5xx_nao_repete_o_post_que_cobra(self):
        """A regressao mais cara do repo: um 503 virava tres cobrancas."""
        d = self.duble([(GERAR, erro_http(503))])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item())
        self.assertEqual(len(d.chamadas), 1, "o POST cobrado nao pode ser repetido")
        self.assertIn("nao repeti a submissao", str(e.exception))

    def test_get_continua_com_retry(self):
        d = self.duble([("/models", erro_http(503))])
        with self.assertRaises(M.Falha):
            M.http("https://generativelanguage.googleapis.com/v1beta/models", None, "GET")
        self.assertEqual(len(d.chamadas), 3)
        self.assertEqual(d.esperas, [3, 6], "espera exponencial 3s, 6s")

    def test_400_nao_repete(self):
        d = self.duble([(GERAR, erro_http(400))])
        with self.assertRaises(M.Falha):
            M.t_gerar_imagem(self.item())
        self.assertEqual(len(d.chamadas), 1, "repetir um 400 so gasta cota")

    def test_nao_destroi_arquivo_que_nao_criou(self):
        pasta = os.path.join(self.raiz, "public", "assets")
        os.makedirs(pasta)
        alvo = os.path.join(pasta, "hero.jpg")
        with open(alvo, "wb") as f:
            f.write(b"FOTO DO FOTOGRAFO")
        self.duble([(GERAR, resposta_imagem())])
        texto = M.t_gerar_imagem(self.item(largura=320, altura=200))
        self.assertEqual(open(alvo, "rb").read(), b"FOTO DO FOTOGRAFO")
        self.assertIn("ja existia", texto)

    def test_sem_pillow_recusa_antes_de_cobrar(self):
        antes = M.SEM_PILLOW
        M.SEM_PILLOW = "No module named 'PIL' (simulado)"
        self.addCleanup(setattr, M, "SEM_PILLOW", antes)
        d = self.duble([(GERAR, resposta_imagem())])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item())
        self.assertEqual(len(d.chamadas), 0, "nenhum POST podia ter saido")
        self.assertIn("NADA foi cobrado", str(e.exception))


class Video(Base):

    def test_default_720p_4s(self):
        d = self.duble([(VIDEO, json.dumps({"name": "models/veo/operations/a1"}).encode())])
        texto = M.t_gerar_video(self.item(id="hero-video", forcar=True))
        par = d.chamadas[0][1]["parameters"]
        self.assertEqual((par["resolution"], par["durationSeconds"]), ("720p", 4))
        self.assertIn("NAO resubmeta", texto)
        self.assertIn("id do item: hero-video", texto)

    def test_1080p_com_4s_e_recusado_localmente(self):
        d = self.duble([(VIDEO, json.dumps({"name": "x"}).encode())])
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_video(self.item(resolucao="1080p", duracao_s=4, forcar=True))
        self.assertEqual(len(d.chamadas), 0, "o combo invalido nao pode chegar a API")
        self.assertIn("1080p em 8 segundos", str(e.exception))

    def test_ainda_processando_nao_e_erro(self):
        self.duble([("/operations/", json.dumps({"done": False}).encode())])
        texto = M.t_status_video({"job": "models/veo/operations/a1", "espera_s": 0})
        self.assertIn("ainda processando", texto)
        self.assertIn("nao ressubmeta", texto.lower(),
                      "tratar 'ainda processando' como falha e ressubmeter cobra o video duas vezes")

    def test_baixa_o_mp4_quando_pronto(self):
        pronto = json.dumps({"done": True, "response": {"generateVideoResponse": {
            "generatedSamples": [{"video": {
                "uri": "https://generativelanguage.googleapis.com/v1beta/files/a1:download"}}]}}})
        self.duble([("/operations/", pronto.encode()),
                    ("files/a1:download", b"MP4-FALSO")])
        texto = M.t_status_video({"job": "models/veo/operations/a1", "id": "hero-video",
                                  "espera_s": 0})
        alvo = os.path.join(self.raiz, "public", "assets", "hero-video-original.mp4")
        self.assertTrue(os.path.exists(alvo), texto)

    def test_uri_de_terceiro_nao_recebe_a_chave(self):
        pronto = json.dumps({"done": True, "response": {"generateVideoResponse": {
            "generatedSamples": [{"video": {"uri": "https://cdn.terceiro.example/v.mp4"}}]}}})
        self.duble([("/operations/", pronto.encode())])
        with self.assertRaises(M.Falha) as e:
            M.t_status_video({"job": "models/veo/operations/a1", "id": "v", "espera_s": 0})
        self.assertIn("fora do dominio do Google", str(e.exception))


class Custo(Base):

    def test_teto_recusa_antes_do_post(self):
        M.TETO_USD = 0.20
        d = self.duble([(GERAR, resposta_imagem())])
        M.t_gerar_imagem(self.item(id="a1", largura=320, altura=200))
        with self.assertRaises(M.Falha) as e:
            M.t_gerar_imagem(self.item(id="a2", largura=320, altura=200))
        self.assertEqual(len(d.chamadas), 1, "a segunda chamada nao podia ter saido")
        self.assertIn("teto de gasto atingido", str(e.exception))
        linhas = [l for l in open(self.ledger, encoding="utf-8").read().splitlines() if l]
        self.assertEqual(len(linhas), 1, "o ledger conta uma cobranca, nao duas")

    def test_estimativa_e_instantaneo(self):
        self.duble([])  # so para apontar a raiz: qualquer ida a rede aqui e erro
        plano = {"provedor": "google-midia", "saida": "public/assets",
                 "itens": [
                     {"id": "hero", "tipo": "imagem", "largura": 1600, "altura": 900},
                     {"id": "card", "tipo": "imagem", "largura": 400, "altura": 400},
                     {"id": "hero-video", "tipo": "video", "resolucao": "720p", "duracao_s": 4},
                     {"id": "sem-preco", "tipo": "imagem", "modelo": "modelo-que-nao-existe"}]}
        with io.open(os.path.join(self.raiz, "midias.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(plano, ensure_ascii=False))
        os.makedirs(os.path.join(self.raiz, "public", "assets"))
        with open(os.path.join(self.raiz, "public", "assets", "card.jpg"), "wb") as f:
            f.write(b"JA EXISTE")
        texto = M.t_estimar_custo({"plano": "midias.json"})
        # o token muda a cada chamada; mascarar preserva o resto do rodape no instantaneo
        texto = re.sub(r"orc-[A-Za-z0-9_-]+", "orc-<TOKEN>", texto)
        ajuda.comparar(self, "mcp/estimar_custo.txt", ajuda.normalizar(texto, self.raiz))

    def test_gerar_sem_orcamento_avisa_na_resposta(self):
        """Com a exigencia desligada (o padrao) a cobranca sem aval era muda."""
        self.duble([(GERAR, resposta_imagem())])
        saida = M.t_gerar_imagem(self.item(redimensionar=False))
        self.assertIn("SEM orcamento aprovado", saida)
        self.assertIn("PARADA 2", saida)

    def test_com_orcamento_aprovado_nao_avisa(self):
        self.duble([])              # aponta M.RAIZ para o tempdir
        plano = {"versao": 2, "raiz": self.raiz,
                 "itens": [{"id": "hero", "tipo": "imagem", "destino": "img/hero.jpg",
                            "largura": 1600, "altura": 900}]}
        with io.open(os.path.join(self.raiz, "midias.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(plano, ensure_ascii=False))
        token = re.search(r"orc-[A-Za-z0-9_-]+",
                          M.t_estimar_custo({"plano": "midias.json"})).group(0)
        self.duble([(GERAR, resposta_imagem())])
        saida = M.t_gerar_imagem(self.item(redimensionar=False, plano="midias.json",
                                           orcamento=token))
        self.assertNotIn("SEM orcamento", saida,
                         "avisar quem seguiu a PARADA 2 e transformar o aviso em ruido")


class PrepararVideo(Base):
    """O ffmpeg nao precisa existir: o que se verifica e o comando montado."""

    def setUp(self):
        Base.setUp(self)
        antes = M.RAIZ
        M.RAIZ = self.raiz          # sem rede, nao ha instalar_duble para apontar a raiz
        self.addCleanup(setattr, M, "RAIZ", antes)

    def duble_ffmpeg(self, retorno=0, erro="", cria=True):
        chamadas = []

        class Resultado(object):
            returncode = retorno
            stderr = erro

        def falso_run(cmd, **kw):
            chamadas.append(cmd)
            if cria and retorno == 0:
                with open(cmd[-1], "wb") as f:
                    f.write(b"x" * 2048)
            return Resultado()

        original_run = M.subprocess.run
        original_which = M.shutil.which
        M.subprocess.run = falso_run
        M.shutil.which = lambda nome: "/usr/bin/ffmpeg" if nome == "ffmpeg" else None
        self.addCleanup(setattr, M.subprocess, "run", original_run)
        self.addCleanup(setattr, M.shutil, "which", original_which)
        return chamadas

    def entrada(self, nome="hero-original.mp4"):
        alvo = os.path.join(self.raiz, nome)
        with open(alvo, "wb") as f:
            f.write(b"mp4 pago")
        return alvo

    def test_sem_ffmpeg_manda_nao_regerar_o_video(self):
        entrada = self.entrada()
        original = M.shutil.which
        M.shutil.which = lambda nome: None
        self.addCleanup(setattr, M.shutil, "which", original)
        with self.assertRaises(M.Falha) as e:
            M.t_preparar_video({"entrada": entrada})
        self.assertIn("NAO", str(e.exception))
        self.assertIn("regere", str(e.exception),
                      "o mp4 ja foi pago: a saida tem de impedir a regeracao")

    def test_o_comando_pede_keyframe_por_frame(self):
        """Sem -g 1 o scrub por scroll trava entre keyframes: e o ponto do arquivo."""
        chamadas = self.duble_ffmpeg()
        M.t_preparar_video({"entrada": self.entrada(), "poster": False})
        cmd = chamadas[0]
        self.assertIn("-g", cmd)
        self.assertEqual(cmd[cmd.index("-g") + 1], "1")
        self.assertEqual(cmd[cmd.index("-keyint_min") + 1], "1")
        self.assertIn("+faststart", cmd)
        self.assertIn("-an", cmd, "audio num video de scroll e peso morto")

    def test_largura_fps_e_crf_chegam_ao_filtro(self):
        chamadas = self.duble_ffmpeg()
        M.t_preparar_video({"entrada": self.entrada(), "largura": 960, "fps": 24,
                            "crf": 28, "poster": False})
        cmd = chamadas[0]
        self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=960:-2,fps=24")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "28")

    def test_saida_padrao_tira_o_sufixo_original(self):
        chamadas = self.duble_ffmpeg()
        M.t_preparar_video({"entrada": self.entrada(), "poster": False})
        self.assertTrue(chamadas[0][-1].endswith("hero.mp4"), chamadas[0][-1])

    def test_poster_dirigido_nao_e_sobrescrito(self):
        chamadas = self.duble_ffmpeg()
        poster = os.path.join(self.raiz, "hero-poster.jpg")
        with open(poster, "wb") as f:
            f.write(b"POSTER DIRIGIDO, US$ 0,134")
        saida = M.t_preparar_video({"entrada": self.entrada()})
        self.assertEqual(len(chamadas), 1, "o segundo ffmpeg extrairia o frame por cima")
        self.assertIn("ja existe", saida)
        with open(poster, "rb") as f:
            self.assertEqual(f.read(), b"POSTER DIRIGIDO, US$ 0,134")

    def test_sobrescrever_poster_extrai_o_frame(self):
        chamadas = self.duble_ffmpeg()
        with open(os.path.join(self.raiz, "hero-poster.jpg"), "wb") as f:
            f.write(b"antigo")
        M.t_preparar_video({"entrada": self.entrada(), "sobrescrever_poster": True})
        self.assertEqual(len(chamadas), 2)
        self.assertIn("select=eq(n\\,0)", " ".join(chamadas[1]))

    def test_ffmpeg_que_falha_vira_falha_legivel(self):
        self.duble_ffmpeg(retorno=1, erro="Invalid data found", cria=False)
        with self.assertRaises(M.Falha) as e:
            M.t_preparar_video({"entrada": self.entrada(), "poster": False})
        self.assertIn("Invalid data found", str(e.exception))

    def test_ferramentas_publicadas(self):
        nomes = ["%s  cobra=%s" % (f["name"], f["annotations"]["destructiveHint"])
                 for f in M.FERRAMENTAS]
        ajuda.comparar(self, "mcp/ferramentas.txt", "\n".join(nomes))


if __name__ == "__main__":
    unittest.main()
