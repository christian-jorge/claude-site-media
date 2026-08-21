# -*- coding: utf-8 -*-
"""P-tst-6 — o servidor MCP como processo, falando JSON-RPC de verdade.

Sao exatamente os metodos que nao chamam a API, entao nao ha o que dublar: o
processo sobe com MIDIA_RAIZ num tempdir e sem GEMINI_API_KEY no ambiente.

O teste que mais importa aqui e o mais chato: **stdout tem de ser JSON puro**.
`atualizar_inventario` importa `gerar_midia`, que tem `print` em quase toda
funcao — um print que vaze para o canal do protocolo derruba a sessao inteira.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import ajuda

SERVIDOR = os.path.join(ajuda.FERR, "mcp_google_midia.py")


class Servidor(unittest.TestCase):

    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="fx-srv-")
        self.addCleanup(shutil.rmtree, self.raiz, True)

    def conversar(self, *mensagens):
        entrada = "".join(json.dumps(m, ensure_ascii=False) + "\n" if not isinstance(m, str)
                          else m + "\n" for m in mensagens)
        env = ajuda.ambiente_limpo({"MIDIA_RAIZ": self.raiz,
                                    "MIDIA_LEDGER": os.path.join(self.raiz, "gastos.jsonl")})
        proc = subprocess.run([sys.executable, SERVIDOR], input=entrada.encode("utf-8"),
                              capture_output=True, env=env)
        saida = []
        for linha in proc.stdout.decode("utf-8", "replace").splitlines():
            if not linha.strip():
                continue
            try:
                saida.append(json.loads(linha))
            except ValueError:
                self.fail("stdout do MCP contem linha que nao e JSON-RPC:\n  %s\n"
                          "algum print() vazou para o canal do protocolo." % linha[:200])
        return proc, saida

    def test_handshake_e_catalogo(self):
        proc, saida = self.conversar(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual([m["id"] for m in saida], [1, 2, 3],
                         "a notificacao nao pode gerar resposta")
        self.assertEqual(saida[0]["result"]["protocolVersion"], "2025-06-18")
        ferramentas = saida[2]["result"]["tools"]
        self.assertEqual(len(ferramentas), 7)
        cobram = {f["name"] for f in ferramentas if f["annotations"]["destructiveHint"]}
        self.assertEqual(cobram, {"gerar_imagem", "gerar_video"},
                         "so as duas que gastam dinheiro sao destrutivas")
        for f in ferramentas:
            self.assertEqual("COBRA" in f["description"], f["name"] in cobram,
                             "%s: a descricao tem de dizer se cobra" % f["name"])

    def test_erros_nao_derrubam_a_sessao(self):
        proc, saida = self.conversar(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "metodo/inexistente"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "nao_existe", "arguments": {}}},
            "123", '"lixo"', "[{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"ping\"}]",
            {"jsonrpc": "2.0", "id": 4, "method": "ping"})
        self.assertEqual(proc.returncode, 0, "o servidor morreu no meio da sessao")
        por_id = {}
        for m in saida:
            if isinstance(m, list):
                for x in m:
                    por_id[x.get("id")] = x
            else:
                por_id[m.get("id")] = m
        self.assertEqual(por_id[2]["error"]["code"], -32601)
        self.assertEqual(por_id[3]["error"]["code"], -32602)
        self.assertIn(9, por_id, "batch JSON-RPC tem de ser respondido")
        self.assertEqual(por_id[4]["result"], {}, "o ping depois do lixo ainda responde")

    def test_atualizar_inventario_ponta_a_ponta(self):
        assets = os.path.join(self.raiz, "public", "assets")
        os.makedirs(assets)
        with open(os.path.join(assets, "hero.jpg"), "wb") as f:
            f.write(b"JPEG-FALSO")
        plano = {"provedor": "google-midia", "saida": "public/assets",
                 "inventario": "inventario_midias.html",
                 "itens": [
                     {"id": "hero", "tipo": "imagem", "largura": 1600, "altura": 900,
                      "prompt": u'um <hero> com "aspas" & e-comercial',
                      "aceite": u"sem texto na imagem"},
                     {"id": "hero-video", "tipo": "video", "prompt": u"um plano so",
                      "aceite": u"sem corte"}]}
        with io.open(os.path.join(self.raiz, "midias.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(plano, ensure_ascii=False))

        proc, saida = self.conversar(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "atualizar_inventario", "arguments": {}}})
        self.assertEqual(proc.returncode, 0)
        texto = saida[1]["result"]["content"][0]["text"]
        self.assertFalse(saida[1]["result"].get("isError"), texto)
        self.assertIn("hero-video", texto, "o item sem arquivo tem de ser nomeado")

        alvo = os.path.join(self.raiz, "inventario_midias.html")
        self.assertTrue(os.path.exists(alvo))
        with io.open(alvo, encoding="utf-8") as f:
            html = f.read()
        corpo = html[html.index("<table>"):html.index("</table>") + 8]
        ajuda.comparar(self, "mcp/inventario.html", ajuda.normalizar(corpo, self.raiz))
        self.assertNotIn("<hero>", html, "o prompt tem de entrar escapado")
        self.assertIn("&lt;hero&gt;", html, "e o '>' tambem, nao so o '<'")


if __name__ == "__main__":
    unittest.main()
