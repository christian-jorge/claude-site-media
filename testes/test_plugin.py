# -*- coding: utf-8 -*-
"""O manifesto do plugin e o unico "instalador" que sobra -- e ele nao avisa quando quebra.

Um caminho errado em `.mcp.json` nao da erro de sintaxe: da um servidor que nao sobe,
com a mensagem generica do cliente MCP. Um nome de variavel trocado nao da erro nenhum:
da um teto que nao vale e uma chave que nao chega. Os testes aqui amarram o manifesto ao
codigo que realmente le cada coisa.
"""
import io
import json
import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDOR = os.path.join(RAIZ, "skills", "design-to-mcp", "ferramentas",
                        "mcp_google_midia.py")


def ler(*partes):
    with io.open(os.path.join(RAIZ, *partes), encoding="utf-8") as f:
        return json.load(f)


class Manifesto(unittest.TestCase):

    def setUp(self):
        self.plugin = ler(".claude-plugin", "plugin.json")
        self.mcp = ler(".mcp.json")
        self.servidor = self.mcp["mcpServers"]["google-midia"]

    def test_o_caminho_do_servidor_existe(self):
        arg = self.servidor["args"][0]
        rel = arg.replace("${CLAUDE_PLUGIN_ROOT}/", "").replace("/", os.sep)
        self.assertTrue(os.path.exists(os.path.join(RAIZ, rel)),
                        "o .mcp.json aponta para %s, que nao existe" % arg)

    def test_a_skill_esta_onde_o_plugin_procura(self):
        """Sem manifesto de skills, o scan padrao e `skills/<nome>/SKILL.md`."""
        self.assertTrue(os.path.exists(
            os.path.join(RAIZ, "skills", "design-to-mcp", "SKILL.md")))
        self.assertTrue(os.path.exists(
            os.path.join(RAIZ, "commands", "gerar-imagem.md")))

    def test_toda_variavel_do_env_e_lida_pelo_servidor(self):
        """Variavel que ninguem le e configuracao que o usuario preenche a toa."""
        with io.open(SERVIDOR, encoding="utf-8") as f:
            fonte = f.read()
        for nome in self.servidor["env"]:
            if nome == "MIDIA_RAIZ":
                continue          # lida na linha 47, fora de os.environ.get literal
            self.assertIn(nome, fonte,
                          "%s nao aparece em mcp_google_midia.py" % nome)

    def test_todo_user_config_citado_existe_no_plugin_json(self):
        citados = set()
        for valor in [self.servidor["command"]] + list(self.servidor["args"]) \
                + list(self.servidor["env"].values()):
            citados.update(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", valor))
        declarados = set(self.plugin.get("userConfig") or {})
        self.assertEqual(citados - declarados, set(),
                         "o .mcp.json cita config que o plugin.json nao declara")
        self.assertEqual(declarados - citados, set(),
                         "o plugin.json pede ao usuario algo que ninguem consome")

    def test_a_chave_e_marcada_como_sensivel(self):
        chave = self.plugin["userConfig"]["gemini_api_key"]
        self.assertTrue(chave.get("sensitive"),
                        "sem sensitive:true a chave vai para settings.json em texto puro")
        self.assertTrue(chave.get("required"))

    def test_nenhum_segredo_literal_no_manifesto(self):
        for arquivo in (".mcp.json", os.path.join(".claude-plugin", "plugin.json"),
                        os.path.join(".claude-plugin", "marketplace.json")):
            with io.open(os.path.join(RAIZ, arquivo), encoding="utf-8") as f:
                texto = f.read()
            self.assertIsNone(re.search(r"AIza[0-9A-Za-z_-]{20,}", texto),
                              "%s tem o que parece uma chave de verdade" % arquivo)

    def test_o_ledger_nao_e_por_projeto(self):
        """Teto de 24h com ledger por projeto vira teto vezes o numero de projetos."""
        self.assertIn("CLAUDE_PLUGIN_DATA", self.servidor["env"]["MIDIA_LEDGER"])

    def test_marketplace_aponta_para_o_plugin_deste_repo(self):
        mkt = ler(".claude-plugin", "marketplace.json")
        entradas = [p for p in mkt["plugins"] if p["name"] == self.plugin["name"]]
        self.assertEqual(len(entradas), 1,
                         "o nome no marketplace tem de bater com o do plugin.json")
        self.assertEqual(entradas[0]["source"], "./",
                         "o repositorio e o proprio plugin")
        self.assertEqual(entradas[0]["version"], self.plugin["version"],
                         "versao divergente faz o usuario instalar o que nao espera")


if __name__ == "__main__":
    unittest.main()
