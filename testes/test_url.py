# -*- coding: utf-8 -*-
"""P-tst-5 (segunda metade) — a via `--url` sem abrir socket nenhum.

Dois dublês, e os dois importam: `baixar` (a página e o CSS externo) e
`existe_no_servidor`. O segundo existe porque, pela URL, quem sabe se o asset
existe é o SERVIDOR — consultar o disco desta máquina marcava 100% dos slots
como vazios, e a PARADA 2 confirmava a mentira somando a rodada inteira.
"""
import shutil
import tempfile
import unittest

import ler_site as L

PAGINA = u"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<link rel="stylesheet" href="/css/site.css">
<style>:root{--marca:#0b7}</style></head>
<body>
  <section>
    <h2>Marmitas da semana</h2>
    <p>Voce escolhe na segunda e recebe na quarta.</p>
    <img class="card-media" src="/img/marmita.jpg" alt="marmita montada">
    <img class="card-media" src="/img/sobremesa.jpg" alt="sobremesa">
  </section>
</body></html>"""

CSS = u".card-media{width:640px;height:360px}\n"

CASCA = u'<!doctype html><html><body><div id="root"></div>' \
        u'<script src="/assets/index.js"></script></body></html>'


class Url(unittest.TestCase):

    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="fx-url-")
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.baixados = []

    def _rede(self, paginas, existentes=()):
        def baixar(url):
            self.baixados.append(url)
            for chave, corpo in paginas.items():
                if url.endswith(chave):
                    return corpo
            raise AssertionError("URL fora do dublê: %s" % url)

        def existe(url):
            return any(url.endswith(e) for e in existentes)

        for nome, funcao in (("baixar", baixar), ("existe_no_servidor", existe)):
            antes = getattr(L, nome)
            setattr(L, nome, funcao)
            self.addCleanup(setattr, L, nome, antes)

    def test_dimensao_vem_do_css_externo(self):
        """Sem baixar o CSS, a via --url entregava todo slot sem dimensao."""
        self._rede({"/": PAGINA, "/css/site.css": CSS}, existentes=("/img/marmita.jpg",))
        rel = L.analisar_url(["http://127.0.0.1:3000/"], self.raiz)
        self.assertIn("http://127.0.0.1:3000/css/site.css", self.baixados)
        s = rel["slots"][0]
        self.assertEqual((s["largura"], s["altura"]), (640, 360))
        self.assertEqual(s["aspect_ratio"], "16:9")
        self.assertEqual(rel["tokens"].get("--marca"), "#0b7")

    def test_quem_responde_se_o_asset_existe_e_o_servidor(self):
        self._rede({"/": PAGINA, "/css/site.css": CSS}, existentes=("/img/marmita.jpg",))
        rel = L.analisar_url(["http://127.0.0.1:3000/"], self.raiz)
        por_id = {s["id"]: s for s in rel["slots"]}
        self.assertIs(por_id["marmita"]["arquivo_existe"], True, "200 no servidor")
        self.assertIs(por_id["sobremesa"]["arquivo_existe"], False, "404 no servidor")
        self.assertIn("servidor:200", por_id["marmita"]["destino_origem"])

    def test_casca_de_spa_avisa(self):
        self._rede({"/": CASCA})
        rel = L.analisar_url(["http://127.0.0.1:5173/"], self.raiz)
        self.assertEqual(rel["slots"], [])
        self.assertEqual(rel["cascas_vazias"], ["http://127.0.0.1:5173/"],
                         "sem este aviso, o agente conclui que o site nao tem imagem")

    def test_css_que_nao_baixa_nao_derruba_a_leitura(self):
        def baixar(url):
            if url.endswith(".css"):
                raise IOError("500")
            return PAGINA
        antes = L.baixar
        L.baixar = baixar
        self.addCleanup(setattr, L, "baixar", antes)
        antes_e = L.existe_no_servidor
        L.existe_no_servidor = lambda url: None
        self.addCleanup(setattr, L, "existe_no_servidor", antes_e)
        rel = L.analisar_url(["http://127.0.0.1:3000/"], self.raiz)
        self.assertEqual(len(rel["slots"]), 2, "a pagina continua sendo lida")


if __name__ == "__main__":
    unittest.main()
