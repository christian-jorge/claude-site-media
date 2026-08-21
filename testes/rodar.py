#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roda a suite inteira. Sem pytest, sem chave de API, sem rede.

    python testes/rodar.py                 # tudo
    python testes/rodar.py test_extratores # so um modulo
    python testes/rodar.py --atualizar     # regrava os instantaneos
"""
import os
import shutil
import sys
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)  # sem isto o discover levanta "not importable"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def main(argv):
    if "--atualizar" in argv:
        os.environ["ATUALIZAR_INSTANTANEOS"] = "1"
        argv = [a for a in argv if a != "--atualizar"]
        print("!! modo --atualizar: os instantaneos serao REGRAVADOS. Revise o diff depois.")

    try:
        from PIL import Image  # noqa: F401
        pillow = "sim"
    except ImportError:
        pillow = "NAO (testes de reamostragem serao pulados)"
    # o ffmpeg NAO e requisito da suite: preparar_video e testado pelo comando que
    # monta, com subprocess dublado. A linha existe porque a ferramenta o exige em uso.
    ffmpeg = "sim" if shutil.which("ffmpeg") else "NAO (a suite nao precisa; a skill sim)"
    print("python %s | pillow: %s | ffmpeg: %s"
          % (sys.version.split()[0], pillow, ffmpeg))
    print("-" * 70)

    carregador = unittest.TestLoader()
    if argv:
        suite = carregador.loadTestsFromNames(argv)
    else:
        suite = carregador.discover(AQUI, pattern="test_*.py", top_level_dir=AQUI)

    r = unittest.TextTestRunner(verbosity=2).run(suite)
    total = r.testsRun
    ruins = len(r.failures) + len(r.errors)
    print("-" * 70)
    print("%d testes, %d falhas, %d pulados" % (total, ruins, len(r.skipped)))
    return 0 if ruins == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
