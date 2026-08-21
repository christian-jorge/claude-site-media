# -*- coding: utf-8 -*-
"""ONDA 5 — o que entra e o que sai da conta paga.

`arquivo_existe: False` e o gatilho de `--so-faltando`, e e ele que decide o que
vai ser cobrado. Cada teste aqui prende um caso em que ele disparava errado:

  comentario / template string   markup desativado virava item PAGO
  arrow function em JSX          a tag truncava e a imagem sumia em silencio
  bloco PHP                      `?>` fechava a tag e levava todos os atributos
  binding de framework           `:src="foto"` virava caminho estatico faltando
  <picture>/<source>/srcset      cada variante virava um item pago a parte
  <video poster>                 o video apontava para o JPEG do poster
  alias / next-image             caminho impossivel, ou o otimizador no lugar do arquivo
  componente proprio             recall ZERO: o extrator dizia que nao havia midia
"""
import io
import json
import os
import shutil
import tempfile
import unittest

import ajuda


class Base(unittest.TestCase):

    def pasta(self, arquivos):
        raiz = tempfile.mkdtemp(prefix="fx-cob-")
        self.addCleanup(shutil.rmtree, raiz, True)
        for rel, conteudo in arquivos.items():
            alvo = os.path.join(raiz, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(alvo), exist_ok=True)
            modo = "wb" if isinstance(conteudo, bytes) else "w"
            if modo == "wb":
                with open(alvo, "wb") as f:
                    f.write(conteudo)
            else:
                with io.open(alvo, "w", encoding="utf-8", newline="\n") as f:
                    f.write(conteudo)
        return raiz

    def plano(self, arquivos, *extra):
        raiz = self.pasta(arquivos)
        destino = os.path.join(raiz, "midias.json")
        proc = ajuda.rodar_script("ler_site.py", raiz, "--plano", destino, *extra)
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        with io.open(destino, encoding="utf-8") as f:
            itens = json.load(f)["itens"]
        return {i["id"]: i for i in itens}, ajuda.texto(proc)


class Fantasmas(Base):

    def test_markup_comentado_nao_vira_item_pago(self):
        itens, _ = self.plano({"app/p.tsx": u"""export default function P() {
  return (<section><h2>Servicos</h2><p>Tres frentes.</p>
    <img src="/img/vivo.jpg" width={800} height={600} alt="vivo" />
    {/* <img src="/img/comentado.jpg" width={800} height={600} alt="morto" /> */}
    {/* um comentario comum */}
  </section>)
}"""})
        self.assertIn("vivo", itens)
        self.assertNotIn("comentado", itens,
                         "comentar o bloco e a forma mais comum de desativa-lo")

    def test_template_string_nao_vira_item_pago(self):
        itens, _ = self.plano({"app/p.jsx": u"""const molde = `
  <img src="/img/molde.jpg" width="800" height="600" alt="molde">
`
export default function P() {
  return (<section><h2>T</h2><p>P</p>
    <img src="/img/real.jpg" width={800} height={600} alt="real" />
  </section>)
}"""})
        self.assertEqual(sorted(itens), ["real"])

    def test_arrow_function_nao_trunca_a_tag(self):
        itens, _ = self.plano({"app/p.tsx": u"""export default function P() {
  return (<section><h2>Equipe</h2><p>Quem faz.</p>
    <img src="/img/time.jpg" width={960} height={540} alt="time"
         onError={(e) => { e.currentTarget.src = "/img/fallback.jpg" }} />
  </section>)
}"""})
        self.assertIn("time", itens, "a imagem sumia em silencio")
        self.assertEqual((itens["time"]["largura"], itens["time"]["altura"]), (960, 540))

    def test_bloco_php_nao_come_os_atributos(self):
        itens, _ = self.plano({"tema/home.php": u"""<section>
  <h2>Promocoes</h2><p>Da semana.</p>
  <img src="<?= $img->url ?>" width="1200" height="800" alt="promocao">
  <img src="/img/estatica.jpg" width="600" height="400" alt="estatica">
</section>"""})
        self.assertIn("estatica", itens)
        self.assertEqual((itens["estatica"]["largura"], itens["estatica"]["altura"]),
                         (600, 400))
        dinamico = [i for i in itens.values() if i["destino"] is None]
        self.assertTrue(dinamico, "o src em PHP tem de sair como dinamico, nao como caminho")
        self.assertEqual(dinamico[0]["destino_origem"], "src-dinamico")


class Containers(Base):

    def test_picture_e_srcset_viram_um_item_so(self):
        itens, _ = self.plano({"index.html": u"""<!doctype html><meta charset="utf-8">
<section><h2>Capa</h2><p>Da edicao.</p>
<picture>
  <source srcset="/img/capa.avif" type="image/avif">
  <source srcset="/img/capa.webp" type="image/webp">
  <img src="/img/capa.jpg" width="1200" height="675" alt="capa">
</picture>
</section>"""})
        self.assertEqual(sorted(itens), ["capa"],
                         "cada <source> virava um item pago para um formato que a "
                         "ferramenta nem produz")
        self.assertEqual(itens["capa"]["destino"], "img/capa.jpg")
        self.assertEqual([v["url"] for v in itens["capa"].get("variantes", [])] or None, None,
                         "as variantes nao viram item pago")

    def test_video_e_poster_sao_dois_itens_com_caminhos_proprios(self):
        itens, _ = self.plano({"index.html": u"""<!doctype html><meta charset="utf-8">
<section><h2>Tour</h2><p>Pela fabrica.</p>
<video poster="/img/tour-poster.jpg" width="1280" height="720" muted playsinline>
  <source src="/img/tour.webm" type="video/webm">
  <source src="/img/tour.mp4" type="video/mp4">
</video>
</section>"""})
        tipos = {i["id"]: i["tipo"] for i in itens.values()}
        self.assertEqual(tipos.get("tour"), "video",
                         "o slot do video apontava para o JPEG do poster")
        self.assertEqual(itens["tour"]["destino"], "img/tour.mp4",
                         "entre os <source>, o mp4 e o que o Veo entrega")
        self.assertEqual(tipos.get("tour-poster"), "imagem")


class Cobertura(Base):

    def test_alias_de_bundler(self):
        itens, _ = self.plano({
            "src/components/Card.vue": u"""<template><figure><h3>C</h3><p>D</p>
  <img src="@/assets/card.png" width="480" height="320" alt="card" />
</figure></template>""",
            "src/assets/card.png": b"PNG"})
        self.assertEqual(itens["card"]["destino"], "src/assets/card.png",
                         "@/ resolvia para components/@/assets/card.png")
        self.assertTrue(itens["card"]["destino_origem"].startswith("alias:"))

    def test_otimizador_de_imagem_do_next(self):
        itens, _ = self.plano({"app/p.tsx": u"""export default function P() {
  return (<section><h2>T</h2><p>P</p>
    <img src="/_next/image?url=%2Fimg%2Fhero.png&w=1200&q=75" width={1200} height={600} alt="hero" />
  </section>)
}"""})
        self.assertEqual(itens["hero"]["destino"], "img/hero.png",
                         "o arquivo real esta no parametro url=")

    def test_componente_proprio_deixa_de_ser_invisivel(self):
        itens, _ = self.plano({"app/p.tsx": u"""import Hero from "./Hero"
export default function P() {
  return (<main><Hero image="/img/capa-hero.jpg" titulo="Bem-vindo" />
    <h2>Depois</h2><p>Texto que vem depois do componente.</p>
  </main>)
}"""})
        self.assertIn("capa-hero", itens,
                      "o arquetipo com recall zero: o extrator dizia que nao havia midia")

    def test_engine_de_template_nao_aborta(self):
        """Shopify e Eleventy faziam sys.exit com 'nenhum arquivo de marcacao'."""
        itens, saida = self.plano({"secoes/hero.liquid": u"""<section>
  <h2>{{ secao.titulo }}</h2><p>Descricao.</p>
  <img src="/img/loja.jpg" width="1200" height="600" alt="loja">
</section>"""})
        self.assertIn("loja", itens)


POST = u"""---
title: Nosso time
capa: /img/capa.jpg
autor: Ana
---

# Nosso time

Somos quatro pessoas.

![Retrato da fundadora](/img/fundadora.jpg)

<img src="/img/premio.jpg" width="800" height="600" alt="premio">
"""


class Markdown(Base):
    """Num site em Markdown a maior parte dos assets vive fora de qualquer tag."""

    def test_arquivo_md_e_lido(self):
        itens, saida = self.plano({"conteudo/post.md": POST})
        self.assertIn("post.md", saida, ".md nem entrava na coleta: so .mdx entrava")

    def test_imagem_em_sintaxe_de_markdown_vira_slot(self):
        itens, _ = self.plano({"conteudo/post.md": POST})
        self.assertIn("fundadora", itens,
                      "![alt](src) e a forma nativa de imagem do formato")
        self.assertEqual(itens["fundadora"]["origem"]["alt"], "Retrato da fundadora")

    def test_campo_de_imagem_do_frontmatter_vira_slot(self):
        itens, _ = self.plano({"conteudo/post.md": POST})
        self.assertIn("capa", itens, "a capa do post e um asset que a pagina pede")
        self.assertNotIn("Ana", " ".join(itens), "campo que nao e midia nao vira slot")

    def test_frontmatter_nao_vaza_para_a_copy(self):
        itens, _ = self.plano({"conteudo/post.md": POST})
        for ident, item in itens.items():
            junto = " ".join(item.get("copy") or [])
            self.assertNotIn("title:", junto, "%s: metadado nao e texto de pagina" % ident)
            self.assertNotIn("---", junto)
            self.assertNotIn("![", junto, "%s: a sintaxe de imagem tambem e marcacao" % ident)

    def test_o_mesmo_asset_nao_e_cobrado_duas_vezes(self):
        """`![](x.jpg)` e `<img src=x.jpg>` no mesmo .mdx sao um arquivo so."""
        itens, _ = self.plano({"conteudo/p.mdx": u"""# T

Texto do post.

![a](/img/x.jpg)

<img src="/img/x.jpg" width="800" height="600" alt="a">
"""})
        self.assertEqual(len(itens), 1, itens)


class Secao(Base):

    def secoes(self, arquivos):
        raiz = self.pasta(arquivos)
        destino = os.path.join(raiz, "b.json")
        proc = ajuda.rodar_script("ler_site.py", raiz, "--json", destino)
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        with io.open(destino, encoding="utf-8") as f:
            return {s["id"]: s["secao"] for s in json.load(f)["slots"]}

    def test_rotulo_de_secao_e_hierarquico(self):
        """Tres cards da mesma grade recebiam todos o rotulo generico `card`."""
        secoes = self.secoes({"index.html": u"""<!doctype html><meta charset="utf-8">
<section id="recursos"><h2>Recursos</h2>
  <article class="card"><h3>Torno</h3><p>Peca unica.</p>
    <img src="/img/torno.jpg" width="600" height="400" alt="torno"></article>
  <article class="card"><h3>Queima</h3><p>Forno a lenha.</p>
    <img src="/img/queima.jpg" width="600" height="400" alt="queima"></article>
</section>"""})
        self.assertEqual(secoes["torno"], "recursos > card",
                         "sem a secao que agrupa, o rotulo nao distingue nada")

    def test_secao_sem_nome_cai_na_propria_tag(self):
        secoes = self.secoes({"index.html": u"""<!doctype html><meta charset="utf-8">
<footer><h2>Rodape</h2><p>Contato.</p>
  <img src="/img/selo.jpg" width="200" height="200" alt="selo"></footer>"""})
        self.assertEqual(secoes["selo"], "footer")


class Fontes(Base):

    def test_google_font_sai_com_familia_e_pesos_separados(self):
        raiz = self.pasta({"index.html": u"""<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Playfair+Display:ital,wght@0,600&display=swap">
<section><h2>T</h2><p>Texto.</p>
<img src="/img/a.jpg" width="800" height="600" alt="a"></section>"""})
        destino = os.path.join(raiz, "b.json")
        proc = ajuda.rodar_script("ler_site.py", raiz, "--json", destino)
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        with io.open(destino, encoding="utf-8") as f:
            fontes = json.load(f)["google_fonts"]
        self.assertEqual(fontes, ["Inter (400, 700)", "Playfair Display (600)"],
                         "o briefing entregava o fragmento de URL como nome da fonte")


if __name__ == "__main__":
    unittest.main()
