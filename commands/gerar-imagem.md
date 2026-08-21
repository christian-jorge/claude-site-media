---
description: Gera imagens e vídeos de IA para as áreas de mídia de um site (canvas do /design ou site já existente)
argument-hint: "[pasta, arquivo ou URL do site | vazio para o projeto atual]"
---

Invoque a skill `design-to-mcp` e siga-a do começo.

Alvo desta execução: **$ARGUMENTS**

Se o alvo veio vazio, descubra sozinho antes de perguntar qualquer coisa:

- há `.dc.html` no projeto → é canvas, entre pela **Etapa 1** (`ler_design.py`);
- há página pronta (`.html`, `.jsx/.tsx`, `.vue`, `.svelte`, `.astro`, `.php`) → é site
  existente, entre pela **Etapa 1-B** (`ler_site.py`);
- há os dois → mostre o que achou e pergunte qual é o alvo;
- não há nenhum → pergunte onde está o site.

Se o alvo for uma URL, use `ler_site.py --url <alvo>`.

Respeite as duas paradas obrigatórias da skill: briefing/slots antes de escrever prompt, e
lista com custo em dólar antes de qualquer chamada cobrada.
