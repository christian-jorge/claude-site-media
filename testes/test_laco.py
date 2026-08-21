# -*- coding: utf-8 -*-
"""P-tst-7 — o laco da PARADA 3, ponta a ponta.

Extrair -> gerar (com a rede dublada) -> RE-EXTRAIR e exigir zero
`ARQUIVO NAO EXISTE`. E o unico teste que prova a promessa do produto inteira:
o arquivo pago cai onde a pagina procura.

Antes do contrato v2 este roteiro gravava `public/assets/card-economia.jpg` --
pasta errada e extensao errada -- e a re-extracao acusava o slot vazio.
"""
import base64
import io
import json
import os
import shutil
import tempfile
import unittest

import ajuda

import mcp_google_midia as M

PAGINA = u"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Economia</title></head>
<body>
  <section>
    <h2>Quanto voce economiza</h2>
    <p>Em media, R$ 180 por mes na conta de luz.</p>
    <img src="/img/card-economia.png" width="800" height="600" alt="grafico de economia">
  </section>
</body></html>"""

try:
    from PIL import Image
    TEM_PILLOW = True
except ImportError:
    TEM_PILLOW = False


def png_falso(cor=(30, 120, 80)):
    buf = io.BytesIO()
    Image.new("RGB", (1024, 768), cor).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


@unittest.skipUnless(TEM_PILLOW, "sem Pillow")
class Laco(unittest.TestCase):

    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="fx-laco-")
        self.addCleanup(shutil.rmtree, self.raiz, True)
        os.makedirs(os.path.join(self.raiz, "public", "img"))
        with io.open(os.path.join(self.raiz, "index.html"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(PAGINA)
        os.environ["MIDIA_LEDGER"] = os.path.join(self.raiz, "gastos.jsonl")
        self.addCleanup(os.environ.pop, "MIDIA_LEDGER", None)
        self.teto = M.TETO_USD
        M.TETO_USD = None
        self.addCleanup(setattr, M, "TETO_USD", self.teto)

    def _extrair(self, *extra):
        plano = os.path.join(self.raiz, "midias.json")
        proc = ajuda.rodar_script("ler_site.py", self.raiz, "--plano", plano, *extra)
        self.assertEqual(proc.returncode, 0, ajuda.texto(proc, "stderr"))
        return plano, ajuda.texto(proc)

    def test_o_arquivo_pago_cai_onde_a_pagina_procura(self):
        plano, saida = self._extrair()
        self.assertIn("ARQUIVO NAO EXISTE", saida, "o slot comeca vazio")

        with io.open(plano, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(len(d["itens"]), 1)
        item = d["itens"][0]
        self.assertEqual(item["destino"], "public/img/card-economia.png",
                         "o plano tem de carregar pasta E extensao que a pagina pede")
        item["prompt"] = u"grafico de barras verde sobre fundo claro, sem texto"
        item["aceite"] = u"nenhuma letra na imagem"
        with io.open(plano, "w", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=2))

        ajuda.instalar_duble(self, M, [(":generateContent", json.dumps({"candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png",
                                                   "data": png_falso()}}]}}]}).encode())],
            raiz=self.raiz)
        texto = M.t_gerar_imagem({"id": item["id"], "prompt": item["prompt"],
                                  "plano": "midias.json"})

        alvo = os.path.join(self.raiz, "public", "img", "card-economia.png")
        self.assertTrue(os.path.exists(alvo),
                        "o asset pago nao caiu no lugar:\n%s" % texto)
        with Image.open(alvo) as img:
            self.assertEqual(img.format, "PNG",
                             "a pagina pede .png: entregar JPEG renomeado quebra o arquivo")
            self.assertEqual(img.size, (800, 600))

        # ---- PARADA 3: o mesmo extractor que abriu a rodada e o que a fecha
        _, saida = self._extrair("--so-faltando")
        self.assertNotIn("ARQUIVO NAO EXISTE", saida,
                         "a PARADA 3 ainda acusa slot vazio depois de gerar:\n%s" % saida)
        self.assertIn("LISTADOS: 0 de 1", saida)

    def test_reextrair_preserva_o_prompt_escrito_a_mao(self):
        """Sem isto a PARADA 3 seria destrutiva: re-rodar apagaria o trabalho caro."""
        plano, _ = self._extrair()
        with io.open(plano, encoding="utf-8") as f:
            d = json.load(f)
        d["itens"][0]["prompt"] = u"PROMPT ESCRITO A MAO"
        d["itens"][0]["aceite"] = u"ACEITE ESCRITO A MAO"
        with io.open(plano, "w", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=2))

        plano, saida = self._extrair()
        self.assertIn("fundindo por destino", saida)
        with io.open(plano, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["itens"][0]["prompt"], u"PROMPT ESCRITO A MAO")
        self.assertEqual(d["itens"][0]["aceite"], u"ACEITE ESCRITO A MAO")

    def test_o_plano_passa_nas_invariantes(self):
        import contrato
        plano, _ = self._extrair()
        with io.open(plano, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(contrato.validar(d), [])


if __name__ == "__main__":
    unittest.main()
