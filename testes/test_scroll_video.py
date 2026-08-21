# -*- coding: utf-8 -*-
"""ONDA 7 — scroll-video.js num harness Node, sem navegador.

Os quatro defeitos que este arquivo tinha eram todos de MEDIDA, e medida se
testa sem DOM de verdade: um dublê de getBoundingClientRect/innerHeight basta.

  data-smooth fora de (0,1]  loop de requestAnimationFrame que nunca converge
                             -- e a propria doc sugeria o valor 0
  altura 0                   o hero abria no ULTIMO frame do clipe
  hero no topo               ~56% do percurso ja gasto antes da primeira tela
  reduced-motion             desligava tambem muted/playsInline/pause
"""
import json
import os
import shutil
import subprocess
import unittest

import ajuda

SCRIPT = os.path.join(ajuda.FERR, "scroll-video.js")

HARNESS = r"""
const fs = require("fs");
const caso = JSON.parse(process.argv[2]);
const avisos = [];
let rafs = [];
const video = {
  id: "hero", src: "/x.mp4", dataset: caso.dataset || {},
  duration: caso.duracao || 10, readyState: 1, seeking: false,
  currentTime: 0, muted: false, playsInline: false, pausado: false,
  pause() { this.pausado = true; },
  addEventListener() {},
  getBoundingClientRect() { return { top: caso.top, height: caso.altura }; },
};
class IO { constructor(cb) { this.cb = cb; } observe() { this.cb([{ isIntersecting: true }]); } }
class RO { constructor() {} observe() {} }
global.window = {
  innerHeight: caso.vh, console: { warn: (m) => avisos.push(m) },
  matchMedia: () => ({ matches: !!caso.reduzido, addEventListener() {} }),
  addEventListener() {},
};
global.document = {
  readyState: "complete", documentElement: { clientHeight: caso.vh },
  querySelectorAll: () => [video], addEventListener() {},
};
global.IntersectionObserver = IO;
global.ResizeObserver = RO;
global.console = { warn: (m) => avisos.push(m) };
global.requestAnimationFrame = (fn) => rafs.push(fn);

eval(fs.readFileSync(process.argv[3], "utf8"));

let voltas = 0;
while (rafs.length && voltas < 400) { const f = rafs.shift(); f(); voltas++; }
process.stdout.write(JSON.stringify({
  currentTime: video.currentTime, muted: video.muted,
  playsInline: video.playsInline, pausado: video.pausado,
  voltas, pendentes: rafs.length, avisos,
}));
"""


@unittest.skipUnless(shutil.which("node"), "sem node")
class ScrollVideo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.harness = os.path.join(ajuda.AQUI, "_harness_scroll.js")
        with open(cls.harness, "w", encoding="utf-8") as f:
            f.write(HARNESS)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.harness):
            os.remove(cls.harness)

    def rodar(self, **caso):
        caso.setdefault("vh", 900)
        caso.setdefault("top", 0)
        caso.setdefault("altura", 600)
        proc = subprocess.run(["node", self.harness, json.dumps(caso), SCRIPT],
                              capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def test_smooth_zero_nao_trava_o_loop(self):
        r = self.rodar(dataset={"smooth": "0"})
        self.assertLess(r["voltas"], 400, "o rAF nunca convergiu")
        self.assertTrue(any("data-smooth" in a for a in r["avisos"]),
                        "o valor invalido tem de ser avisado, nao engolido")

    def test_altura_zero_fica_no_primeiro_frame(self):
        r = self.rodar(altura=0)
        self.assertEqual(r["currentTime"], 0,
                         "sem caixa util, o hero abria no ULTIMO frame do clipe")

    def test_hero_no_topo_com_auto_comeca_do_zero(self):
        """Sem 'auto', um video no topo ja nasce com ~56% do percurso gasto."""
        sem = self.rodar(top=0, altura=600, vh=900)
        com = self.rodar(top=0, altura=600, vh=900, dataset={"scrollStart": "auto"})
        self.assertGreater(sem["currentTime"], 5.0, "e este o comportamento antigo")
        self.assertLess(com["currentTime"], 0.01,
                        "com auto, o clipe comeca quando o topo encosta na viewport")

    def test_faixa_invertida_avisa_e_cai_no_padrao(self):
        r = self.rodar(dataset={"scrollStart": "0.9", "scrollEnd": "0.2"})
        self.assertTrue(any("scroll-start" in a for a in r["avisos"]))
        self.assertLess(r["voltas"], 400)

    def test_reduced_motion_ainda_prepara_o_video(self):
        r = self.rodar(reduzido=True)
        self.assertTrue(r["muted"], "iOS/Chrome bloqueiam video com audio sem gesto")
        self.assertTrue(r["playsInline"], "sem playsinline o iOS abre em fullscreen")
        self.assertTrue(r["pausado"])
        self.assertEqual(r["currentTime"], 0, "nada pode escrever currentTime no modo reduzido")

    def test_convergencia_normal(self):
        r = self.rodar(top=300, altura=600, vh=900)
        self.assertGreater(r["currentTime"], 0)
        self.assertEqual(r["pendentes"], 0, "o loop tem de parar sozinho")


if __name__ == "__main__":
    unittest.main()
