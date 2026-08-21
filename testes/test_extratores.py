# -*- coding: utf-8 -*-
"""P-tst-4 — congela a saida dos extratores.

Tres artefatos por fixture, deliberadamente separados: uma mudanca de CONTAGEM
falha num teste e uma mudanca de CAMPO falha noutro, em vez de tudo junto.

  briefing.json  o dicionario inteiro (menos a raiz absoluta)
  midias.json    o plano gerado — e o contrato com o gerador
  rodape.txt     so as linhas que o agente le na PARADA 1
"""
import io
import json
import os
import unittest

import ajuda

SITES = ["site-html-css", "site-pastas-mistas", "site-next-jsx",
         "site-vue-svelte", "site-quebrado", "site-colisao-de-id"]


class Extrator(unittest.TestCase):

    def _rodar(self, nome):
        alvo = ajuda.copiar_fixture(self, nome)
        proc = ajuda.rodar_script("ler_site.py", alvo,
                                  "--json", os.path.join(alvo, "briefing.json"),
                                  "--plano", os.path.join(alvo, "midias.json"))
        self.assertEqual(proc.returncode, 0,
                         "ler_site.py falhou em %s:\n%s" % (nome, ajuda.texto(proc, "stderr")))
        return alvo, proc

    def test_briefing(self):
        for nome in SITES:
            with self.subTest(fixture=nome):
                alvo, _ = self._rodar(nome)
                with io.open(os.path.join(alvo, "briefing.json"), encoding="utf-8") as f:
                    d = json.load(f)
                d.pop("raiz", None)
                ajuda.comparar(self, "%s/briefing.json" % nome,
                               ajuda.normalizar(ajuda.canonico(d), alvo))

    def test_plano(self):
        for nome in SITES:
            with self.subTest(fixture=nome):
                alvo, _ = self._rodar(nome)
                with io.open(os.path.join(alvo, "midias.json"), encoding="utf-8") as f:
                    ajuda.comparar(self, "%s/midias.json" % nome,
                                   ajuda.normalizar(f.read(), alvo))

    def test_rodape(self):
        """A contagem e o numero que a PARADA 2 transforma em dolar."""
        for nome in SITES:
            with self.subTest(fixture=nome):
                alvo, proc = self._rodar(nome)
                linhas = [l for l in ajuda.texto(proc).splitlines()
                          if l.startswith(("SLOTS DE MIDIA", "LISTADOS:", "TOTAL:",
                                           "Confirme a dimensao"))]
                ajuda.comparar(self, "%s/rodape.txt" % nome,
                               ajuda.normalizar("\n".join(linhas), alvo))

    def test_so_faltando_nao_lista_o_que_existe(self):
        alvo = ajuda.copiar_fixture(self, "site-html-css")
        proc = ajuda.rodar_script("ler_site.py", alvo, "--so-faltando")
        saida = ajuda.texto(proc)
        self.assertIn("FORA DA LISTA", saida)
        self.assertIn("torno", saida.split("FORA DA LISTA")[1],
                      "o asset que existe em disco tem de aparecer como excluido, nomeado")

    def test_marcacao_quebrada_nao_some_em_silencio(self):
        alvo = ajuda.copiar_fixture(self, "site-quebrado")
        proc = ajuda.rodar_script("ler_site.py", alvo)
        self.assertEqual(proc.returncode, 0, "marcacao quebrada nao pode derrubar o extrator")
        self.assertIn("palco", ajuda.texto(proc), "o slot antes do ponto quebrado tem de sair")
        # o aviso antigo dependia de uma excecao que html.parser nunca levanta:
        # era codigo morto, e o usuario nunca soube que a copy podia estar misturada
        erro = ajuda.texto(proc, "stderr")
        self.assertIn("sem fechar", erro, "o aviso tem de disparar de verdade")
        self.assertIn("copy de cada bloco pode estar misturada", erro)

    def test_marcacao_boa_nao_gera_aviso(self):
        alvo = ajuda.copiar_fixture(self, "site-html-css")
        proc = ajuda.rodar_script("ler_site.py", alvo)
        self.assertNotIn("sem fechar", ajuda.texto(proc, "stderr"),
                         "aviso que dispara sempre e ruido, nao sinal")

    def test_ordem_de_leitura_e_deterministica(self):
        """P-tst-3: sem sorted() nas subpastas o instantaneo oscila entre maquinas."""
        alvo = ajuda.copiar_fixture(self, "site-pastas-mistas")
        saidas = set()
        for _ in range(3):
            proc = ajuda.rodar_script("ler_site.py", alvo, "--json",
                                      os.path.join(alvo, "b.json"))
            with io.open(os.path.join(alvo, "b.json"), encoding="utf-8") as f:
                saidas.add(json.dumps(json.load(f)["arquivos_lidos"]))
        self.assertEqual(len(saidas), 1, "arquivos_lidos mudou entre execucoes: %s" % saidas)


class Canvas(unittest.TestCase):
    """Unica cobertura de ler_design.py — que nao tinha nenhuma."""

    def test_briefing_do_canvas(self):
        alvo = ajuda.copiar_fixture(self, "canvas-basico")
        proc = ajuda.rodar_script("ler_design.py", alvo,
                                  "--json", os.path.join(alvo, "b.json"))
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        with io.open(os.path.join(alvo, "b.json"), encoding="utf-8") as f:
            d = json.load(f)
        for r in d:
            r.pop("caminho", None)
        ajuda.comparar(self, "canvas-basico/briefing.json",
                       ajuda.normalizar(ajuda.canonico(d), alvo))

    def test_console_estreito_nao_derruba_a_etapa_1(self):
        """P-canvas-1: copy com travessao matava o script num console cp850."""
        alvo = ajuda.copiar_fixture(self, "canvas-basico")
        with io.open(os.path.join(alvo, "acentos.dc.html"), "w", encoding="utf-8") as f:
            f.write(u'<section class="artboard" data-artboard="X" style="width:800px">'
                    u'<h1>Sim \u2014 e agora \u2605</h1>'
                    u'<div class="media-placeholder" style="width:400px;height:300px"></div>'
                    u'</section>')
        destino = os.path.join(alvo, "b.json")
        proc = ajuda.rodar_script("ler_design.py", alvo, "--json", destino,
                                  env={"PYTHONIOENCODING": "cp850"})
        self.assertEqual(proc.returncode, 0,
                         "console estreito derrubou a Etapa 1:\n%s" % ajuda.texto(proc, "stderr"))
        self.assertTrue(os.path.exists(destino),
                        "o --json tem de ser gravado ANTES do print, senao o briefing se perde")


if __name__ == "__main__":
    unittest.main()
