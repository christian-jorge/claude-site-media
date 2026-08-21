# -*- coding: utf-8 -*-
"""P-per-8 — a chave chega mesmo ao registro do MCP?

Os instaladores nao tinham teste nenhum, e o defeito que isso escondeu nao e do
tipo que revisao pega: em `GEMINI_API_KEY="$CHAVE" claude ... --env
"GEMINI_API_KEY=$GEMINI_API_KEY"`, o `$GEMINI_API_KEY` de dentro do argumento
expande no shell PAI, antes de a atribuicao valer. O instalador imprimia
"registrado" e o servidor subia SEM chave -- ou com o valor velho do ambiente.

O `claude` aqui e um script que so despeja o proprio argv. Nada e instalado fora
do tempdir e nenhuma chave real aparece.
"""
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAVE = "CHAVE-DE-TESTE-SEM-VALOR-123"


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fx-inst-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.projeto = os.path.join(self.tmp, "projeto")
        os.makedirs(self.projeto)
        # o --projeto pergunta quando a pasta nao parece raiz de projeto
        with io.open(os.path.join(self.projeto, "package.json"), "w") as f:
            f.write(u"{}")
        self.argv = os.path.join(self.tmp, "argv.txt")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)

    def shim(self, nome, corpo):
        alvo = os.path.join(self.bin, nome)
        with io.open(alvo, "w", encoding="utf-8", newline="\n") as f:
            f.write(corpo)
        os.chmod(alvo, os.stat(alvo).st_mode | stat.S_IEXEC | stat.S_IXGRP)
        return alvo

    def ambiente(self):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["ARGV_LOG"] = self.argv
        env.pop("GEMINI_API_KEY", None)
        return env

    def registrado(self):
        with io.open(self.argv, encoding="utf-8") as f:
            return f.read()


class Sh(Base):

    def setUp(self):
        Base.setUp(self)
        self.shim("claude", '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; '
                            'done > "$ARGV_LOG"\n')

    def rodar(self, entrada=CHAVE):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("sem bash nesta maquina")
        return subprocess.run([bash, os.path.join(RAIZ, "install.sh"),
                               "--projeto", "--chave-stdin"],
                              cwd=self.projeto, env=self.ambiente(),
                              input=(entrada + "\n").encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_a_chave_digitada_chega_ao_registro(self):
        proc = self.rodar()
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))
        self.assertIn("GEMINI_API_KEY=" + CHAVE, self.registrado(),
                      "registrava a variavel VAZIA: o servidor subia sem chave e o "
                      "instalador dizia 'registrado'")

    def test_valor_antigo_do_ambiente_nao_vence_o_digitado(self):
        """O modo de falhar mais cruel: registrar silenciosamente a chave errada."""
        env = self.ambiente()
        env["GEMINI_API_KEY"] = "CHAVE-VELHA-DO-AMBIENTE"
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("sem bash nesta maquina")
        proc = subprocess.run([bash, os.path.join(RAIZ, "install.sh"),
                               "--projeto", "--chave-stdin"],
                              cwd=self.projeto, env=env,
                              input=(CHAVE + "\n").encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))
        self.assertIn("GEMINI_API_KEY=" + CHAVE, self.registrado())
        self.assertNotIn("CHAVE-VELHA", self.registrado())

    def test_escopo_do_mcp_acompanha_o_da_instalacao(self):
        self.rodar()
        registrado = self.registrado()
        self.assertIn("local", registrado,
                      "skill instalada so no projeto registrada em -s user deixa um "
                      "servidor quebrado em todos os outros projetos")

    def test_sem_mcp_nao_registra_nada(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("sem bash nesta maquina")
        proc = subprocess.run([bash, os.path.join(RAIZ, "install.sh"),
                               "--projeto", "--sem-mcp"],
                              cwd=self.projeto, env=self.ambiente(),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists(self.argv), "nada devia ter sido registrado")


@unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"),
                     "install.ps1 so roda com pwsh")
class Ps1(Base):

    def test_a_chave_chega_ao_registro(self):
        """Sem -PedirChave nao ha como injetar a chave: o Read-Host exige console.

        O que da para provar aqui e que o comando montado leva a chave no --env, e
        nao uma variavel de ambiente que o `claude mcp add` nunca leria.
        """
        with io.open(os.path.join(RAIZ, "install.ps1"), encoding="utf-8") as f:
            fonte = f.read()
        self.assertIn('--env "GEMINI_API_KEY=$chave"', fonte)
        self.assertNotIn("$env:GEMINI_API_KEY = $chave", fonte,
                         "definir a variavel no processo pai era teatro: o registro "
                         "guarda o que vai em --env, nao o ambiente de quem chamou")


if __name__ == "__main__":
    unittest.main()
