# -*- coding: utf-8 -*-
"""ONDA 5 — a dimensao do slot, que e o numero que a PARADA 2 transforma em dolar.

Cada teste aqui prende um defeito medido que fazia o plano pedir a imagem errada:

  @media          o breakpoint de celular vencia a base, e o hero era planejado em 360px
  descendente     `.hero .media` e `.footer .media` viravam a mesma chave: 120x60 no hero
  Tailwind        84% dos slots sem dimensao num projeto utility-first
  CSS Modules     a regra existia, indexada, e `className={css.foto}` nao casava com ela
  valor relativo  `.w-full{width:100%}` vencia a regra que tinha px de verdade
"""
import io
import json
import os
import shutil
import tempfile
import unittest

import ajuda


class Base(unittest.TestCase):

    def montar(self, arquivos):
        raiz = tempfile.mkdtemp(prefix="fx-dim-")
        self.addCleanup(shutil.rmtree, raiz, True)
        for rel, conteudo in arquivos.items():
            alvo = os.path.join(raiz, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(alvo), exist_ok=True)
            with io.open(alvo, "w", encoding="utf-8", newline="\n") as f:
                f.write(conteudo)
        return raiz

    def plano(self, arquivos):
        raiz = self.montar(arquivos)
        destino = os.path.join(raiz, "midias.json")
        proc = ajuda.rodar_script("ler_site.py", raiz, "--plano", destino)
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        with io.open(destino, encoding="utf-8") as f:
            return {i["id"]: i for i in json.load(f)["itens"]}


class Cascata(Base):

    CSS = u""".hero .media{width:1440px;height:420px}
.rodape .media{width:120px;height:60px}
@media (max-width:768px){.hero .media{width:360px;height:200px}}
@media (min-width:1920px){.hero .media{width:2560px;height:900px}}
@media print{.hero .media{width:99px;height:99px}}
"""
    HTML = u"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="e.css">
<section class="hero"><h1>Topo</h1><p>Texto do topo.</p>
  <img class="media" src="/img/hero.jpg"></section>
<footer class="rodape"><h2>Fim</h2><p>Texto do fim.</p>
  <img class="media" src="/img/rodape.jpg"></footer>"""

    def test_media_query_nao_sobrescreve_o_desktop(self):
        itens = self.plano({"index.html": self.HTML, "e.css": self.CSS})
        self.assertEqual((itens["hero"]["largura"], itens["hero"]["altura"]), (1440, 420),
                         "o breakpoint de celular venceu a regra base")

    def test_seletor_descendente_nao_colide(self):
        itens = self.plano({"index.html": self.HTML, "e.css": self.CSS})
        self.assertEqual((itens["rodape"]["largura"], itens["rodape"]["altura"]), (120, 60))
        self.assertIn(".hero", itens["hero"]["dimensao_origem"],
                      "a regra escolhida tem de ser a do bloco onde o slot esta")

    def test_valor_relativo_nao_vence_px(self):
        itens = self.plano({
            "index.html": u'<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="e.css">'
                          u'<section><h2>T</h2><p>P</p>'
                          u'<img class="w-full media" src="/img/x.jpg"></section>',
            "e.css": u".w-full{width:100%}\n.media{width:800px;height:450px}\n"})
        self.assertEqual((itens["x"]["largura"], itens["x"]["altura"]), (800, 450))


class Utilitarias(Base):

    def test_escala_do_tailwind(self):
        itens = self.plano({"app/page.tsx": u"""export default function P() {
  return (<section><h2>Planos</h2><p>Escolha o seu.</p>
    <img className="h-64 w-96 rounded" src="/img/plano.jpg" alt="plano" />
  </section>)
}"""})
        self.assertEqual((itens["plano"]["largura"], itens["plano"]["altura"]), (384, 256),
                         "a escala do Tailwind e 0.25rem: w-96 = 384px, h-64 = 256px")

    def test_razao_nomeada_e_arbitraria(self):
        itens = self.plano({"app/page.tsx": u"""export default function P() {
  return (<section><h2>Video</h2><p>Assista.</p>
    <img className="w-full aspect-video" src="/img/capa.jpg" alt="capa" />
    <img className="aspect-[4/5] w-80" src="/img/retrato.jpg" alt="retrato" />
  </section>)
}"""})
        self.assertEqual(itens["capa"]["aspect_ratio"], "16:9")
        self.assertEqual(itens["retrato"]["aspect_ratio"], "4:5")

    def test_prefixo_de_estado_nao_conta(self):
        """hover:h-96 nao e o layout base; 2xl: esta acima do desktop de referencia."""
        itens = self.plano({"app/page.tsx": u"""export default function P() {
  return (<section><h2>T</h2><p>P</p>
    <img className="hover:h-96 2xl:h-[900px] h-48 w-48" src="/img/t.jpg" alt="t" />
  </section>)
}"""})
        self.assertEqual((itens["t"]["largura"], itens["t"]["altura"]), (192, 192))


class Modulos(Base):

    FONTE = u"""import css from "./Card.module.css"
export default function Card() {
  return (<article><h3>Card</h3><p>Descricao do card.</p>
    <img className={css.foto} src="/img/card.jpg" alt="card" />
  </article>)
}"""

    def test_css_module_casa_pela_expressao(self):
        itens = self.plano({"app/Card.tsx": self.FONTE,
                            "app/Card.module.css": u".foto{width:640px;height:480px}\n"})
        self.assertEqual((itens["card"]["largura"], itens["card"]["altura"]), (640, 480))

    def test_modulo_de_outro_arquivo_nao_contamina(self):
        itens = self.plano({
            "app/Card.tsx": self.FONTE,
            "app/Card.module.css": u".foto{width:640px;height:480px}\n",
            "app/Outro.module.css": u".foto{width:64px;height:48px}\n"})
        self.assertEqual((itens["card"]["largura"], itens["card"]["altura"]), (640, 480),
                         "dois *.module.css com .foto nao podem se contaminar")


class Estilizado(Base):

    def test_styled_components_deixa_de_ser_invisivel(self):
        """O unico arquetipo com recall zero: o extrator dizia que nao havia midia."""
        itens = self.plano({"app/Hero.jsx": u"""import styled from "styled-components"
const Capa = styled.img`
  width: 1200px;
  height: 500px;
`
export default function Hero() {
  return (<section><h1>Titulo</h1><p>Subtitulo do hero.</p>
    <img className="Capa" src="/img/capa.jpg" alt="capa" />
  </section>)
}"""})
        self.assertEqual((itens["capa"]["largura"], itens["capa"]["altura"]), (1200, 500))


if __name__ == "__main__":
    unittest.main()
