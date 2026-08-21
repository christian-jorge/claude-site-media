---
name: design-to-mcp
description: Gera imagens e vídeos de IA (Nano Banana Pro e Veo 3.1) para as áreas de mídia de uma página, com prompts ancorados na copy de cada bloco — seja um canvas do /design (artboards .dc.html) virando landing page nova, seja um site que já existe e roda (HTML, React/Next, Vue, Svelte, Astro, PHP e background-image de CSS), incluindo vídeo animado por rolagem. Use quando o pedido for "transforme o canvas em site", "gere as imagens do meu site", "criar a mídia dessa seção", "trocar essa imagem", "substituir as fotos da página", "preencher as imagens que faltam", "as imagens estão quebradas", "quero um vídeo no hero", "gerar com Nano Banana ou Veo", "/design-to-mcp" ou "/gerar-imagem".
---

# design-to-mcp

Entrega mídia real nas áreas de mídia de uma página. Duas portas de entrada, o mesmo
miolo:

- **canvas do `/design`** → a página ainda não existe; você a constrói e preenche (Etapas 1, 2, 3, 4);
- **site que já existe** → a página já está lá, rodando; você só lê as áreas dela, gera e
  aplica (Etapas 1-B, 3, 4 — a Etapa 2 não acontece).

Em ambos os casos, dois pontos de parada obrigatórios.

## Onde estão as ferramentas

Os scripts moram junto deste arquivo, não no projeto do usuário. Antes do primeiro comando,
resolva as duas variáveis abaixo e use-as em tudo que vier depois:

- **`$SKILL`** — a pasta que contém este `SKILL.md`. Instalada no usuário é
  `$HOME/.claude/skills/design-to-mcp`; instalada no projeto é
  `<projeto>/.claude/skills/design-to-mcp`. Se as duas existirem, a do projeto vence.
- **`$FERR`** — `$SKILL/ferramentas`.

`$HOME` funciona tanto no Bash quanto no PowerShell, então os comandos abaixo rodam nos dois:

```bash
FERR="$HOME/.claude/skills/design-to-mcp/ferramentas"
ls "$FERR"          # ler_design.py  ler_site.py  gerar_midia.py  mcp_google_midia.py  scroll-video.js
```

Se `ls` não achar, a skill está instalada no projeto — troque `$HOME` pela raiz dele.

**O cwd continua sendo o projeto do usuário.** Os scripts leem e escrevem em relação a onde
o Claude Code foi aberto; só o caminho *do próprio script* é que muda. O mesmo vale para o
servidor MCP: ele resolve caminhos relativos a partir do cwd, então `public/assets` é a
pasta do projeto, nunca a da skill.

## Etapa 1 — Ler o canvas

> Pule para a **Etapa 1-B** se o alvo é um site que já existe.

```bash
python "$FERR/ler_design.py" <arquivo.dc.html | pasta> --json briefing.json
```

O script devolve: ordem das seções, dimensões exatas de cada placeholder de mídia,
Google Fonts referenciadas, paleta por frequência de uso, design tokens (`--custom-props`)
e a copy detectada.

Sobre esse resultado, monte um briefing curto contendo:

- a ordem e a hierarquia das seções;
- cada placeholder com **largura × altura em pixels** e o aspect ratio derivado;
- tipografia (família, pesos, escala) e a paleta separada em primária / secundária / destaque;
- qualquer regra de design system que apareça nas notas do canvas.

**PARADA 1 — apresente o briefing e espere a confirmação antes de escrever código.**
Se o extractor não achar dimensão em algum placeholder, pergunte em vez de inventar.

## Etapa 1-B — Ler um site que já existe

Quando o pedido é "gere as imagens do meu site", "essa página aqui precisa de vídeo no
topo" ou "preenche as imagens que estão faltando", **não há canvas**. O alvo é o projeto
que já roda. Use o outro extractor:

```bash
# varrendo os arquivos do projeto
python "$FERR/ler_site.py" <pasta-do-projeto> --json briefing_site.json

# lendo do servidor que está no ar (uma ou mais rotas)
python "$FERR/ler_site.py" --url http://localhost:3000 --url http://localhost:3000/precos

# só o que está faltando, já montando o esqueleto do plano
python "$FERR/ler_site.py" . --so-faltando --plano midias.json
```

Ele lê `.html`, `.jsx/.tsx`, `.vue`, `.svelte`, `.astro`, `.php` e o `background-image`
de `.css/.scss`, e devolve, por slot:

- **dimensão de exibição** e razão, resolvidas nesta ordem: atributo `width`/`height` →
  `style` inline → regra de CSS pela classe/id → `aspect-ratio`. O campo
  `origem_dimensao` diz de onde veio, e slots sem dimensão declarada são contados no
  rodapé — esses você **pergunta**, não inventa;
- **se o arquivo apontado existe em disco** — `ARQUIVO NAO EXISTE` é o slot vazio, a
  prioridade óbvia; `externo/dinamico` é `src={variavel}` ou URL de terceiro;
- **a copy do bloco** — o título e o parágrafo vizinhos ao slot. É a matéria-prima do
  prompt (veja *Como escrever o prompt*), e é o que faz a diferença entre a imagem daquele
  card e uma foto de banco de imagens;
- **os design tokens e a paleta** do CSS, que definem a grade de cor a pedir;
- o `alt` atual, quando houver.

Cuidados desta via:

- **`--url` só enxerga o HTML servido.** SPA renderizada no cliente devolve casca vazia —
  o extractor avisa. Nesse caso leia a pasta do projeto, ou salve o DOM já renderizado
  num `.html` e leia esse arquivo.
- **`src` dinâmico** (`src={hero}`, `:src="foto"`, `<?= $img ?>`) não diz qual arquivo é.
  Descubra para onde a variável aponta antes de decidir o `id` do asset, senão você gera
  um arquivo que a página nunca vai carregar.
- **Não invente slot.** Se o pedido é "um vídeo no topo" e não existe `<video>` lá, isso é
  mudança de marcação: proponha primeiro, não gere antes do aval.
- **Este é o site do usuário, em produção.** Nunca sobrescreva um asset existente sem
  pedir; o padrão é gerar só onde falta (`--so-faltando`).

**PARADA 1 — mostre os slots encontrados** (id, dimensão, estado do arquivo, copy do bloco)
**e confirme quais entram na rodada** antes de escrever prompt. Na dúvida entre "todos" e
"só os vazios", pergunte: os assets existentes podem ser de fotógrafo, não placeholder.

Confirmado, siga direto para a **Etapa 3** — a Etapa 2 não se aplica: a página já existe e
você não vai reescrevê-la.

## Etapa 2 — Construir a página

> Só na via do canvas. Site existente pula para a Etapa 3.

Escreva `index.html` como landing page de página única, responsiva.

Regras firmes:

- Fontes **apenas** via Google Fonts (`<link>` para `fonts.googleapis.com`), com fallback real
  na stack (`font-family: 'Inter', system-ui, sans-serif`).
- Containers de mídia ficam **vazios**, com as dimensões exatas do canvas e `aspect-ratio`
  declarado, para que nada mude de lugar quando o asset chegar.
- Tags de vídeo seguem `$SKILL/docs/video.md` sem exceção. `autoplay`, `loop` e `controls` são
  proibidos em animação por rolagem.
- Vídeo animado por rolagem precisa do `scroll-video.js` **dentro do projeto** — a
  página não carrega script de fora dela. Copie `$SKILL/ferramentas/scroll-video.js`
  para a pasta de estáticos (`public/js/`, `static/js/`, ao lado da página…) e
  referencie de lá: `<script src="/js/scroll-video.js"></script>`, imediatamente
  antes de `</body>`.
- Sem `backdrop-filter: blur()` em cards e fundos. Se o canvas pedir profundidade,
  resolva com camada de cor sólida ou gradiente.
- Nada de dependência externa além das fontes: CSS inline ou arquivo local.

## Etapa 3 — Planejar e gerar as mídias

**Caminho principal: MCP `google-midia`** (imagem pelo Nano Banana Pro, vídeo pelo Veo 3.1).
Fallback por API direta em `$FERR/gerar_midia.py`, se o servidor MCP não subir.

Escreva o plano em `midias.json` (veja `$SKILL/midias.example.json`), um item por placeholder,
com `id`, `prompt`, `largura` e `altura` vindos do briefing. O `id` vira o nome do arquivo.
Marque cada item com `"tipo": "imagem"` ou `"tipo": "video"`.

Vindo da Etapa 1-B, o `ler_site.py --plano midias.json` já escreve esse esqueleto: ids
tirados do nome do arquivo atual, dimensões resolvidas, a copy do bloco na `nota`, `saida`
apontando para a pasta onde os assets do projeto já moram, e `prompt`/`aceite` em branco
para você preencher. Confira o `saida` antes de gerar — é o que decide se o arquivo cai onde
a página vai procurar.

O plano é o roteiro para as chamadas MCP e serve de checklist do que já foi feito —
mantenha-o atualizado conforme os assets chegam. Se você reescrever um prompt no meio do
caminho, **atualize o item antes de seguir**: o plano tem que reproduzir o que foi gerado,
não a primeira ideia.

### Como escrever o prompt

O prompt não sai do nada, e não é decoração: é a diferença entre uma foto de banco de
imagens e a imagem daquele bloco. Cinco camadas, nesta ordem:

1. **Assunto concreto, tirado da copy do próprio bloco.** O card diz "vai ao Red Bull Ring"?
   O prompt nomeia Spielberg, os morros da Estíria, a subida depois da primeira curva. O card
   diz "sozinho na pista, a um milésimo"? Então é um carro só, volta de classificação, não uma
   disputa. Genérico ("circuito alpino", "produto sobre fundo claro") é o defeito mais comum e
   o mais caro — cada rodada errada custa uma geração.
2. **Grade de cor herdada dos tokens do canvas.** Um site com `--bg: #08090c` pede imagem
   *low-key*: sombra fechada, midtone dessaturado, um realce quente. Sem isso a foto acende no
   meio da página escura e briga com o layout.
3. **Câmera.** Lente, altura, enquadramento, o que ocupa o quadro: "50mm, câmera quase no
   asfalto, o carro ocupando dois terços". Sem isso o modelo escolhe o ângulo de catálogo.
4. **Espaço para o texto**, quando houver overlay. Peça explicitamente a região limpa:
   "terço inferior esquerdo escuro e sem detalhe, para o título sobreposto".
5. **Negativas, no fim e específicas.** "Sem texto, sem logotipo, sem marca d'água" sempre.
   E quando o modelo insistir num clichê, negue o clichê pelo nome: `"Not a static line-up,
   not parked cars, not a photo shoot"` foi o que tirou os carros da pose de catálogo e os
   pôs em movimento. Negativa genérica não resolve; negativa nomeada resolve.

Em vídeo, o mesmo, mais **uma frase só de movimento**: uma direção, velocidade constante,
sem corte. Vídeo com dois movimentos ou corte no meio arruína o scrub por rolagem.
Aqui o `negative_prompt` é campo próprio — use para `corte seco, zoom, tremor de câmera,
legenda, HUD`.

Os dois idiomas funcionam, mas mantenha **um só por plano**. O vocabulário fotográfico
(*low-key*, *swan-neck*, *motion blur*, *shallow depth of field*) é mais preciso em inglês e
é como os prompts deste projeto estão escritos — a copy do site continua em português, o
prompt é instrução para o modelo, não texto de página.

### Critério de aceite

Cada item leva um campo `aceite`: uma frase do que precisa estar na imagem para ela servir.
Escreva **antes** de gerar, enquanto a intenção está clara.

```json
{ "id": "destaque-2",
  "prompt": "...",
  "aceite": "dois carros idênticos, em movimento, Interlagos reconhecível ao fundo" }
```

Não é burocracia: é o que transforma "achei que ficou meio estranha" em decisão objetiva na
Etapa 4, e é o que entra no inventário para o usuário conferir junto.

**PARADA 2 — mostre a lista completa e o custo total, e espere aprovação explícita.**
Cada item é cobrado na conta Google do usuário. Nunca gere sem esse aval.
O total sai de `mcp__google-midia__estimar_custo` (aceita `plano: "midias.json"` ou os itens
inline) — some os valores de lá, não chute. Ele marca os itens que **já existem em disco** e
mostra separado quanto custa gerar só o que falta: é esse segundo número que vale, a menos
que a intenção declarada seja refazer a rodada inteira.

Se houver mascote ou personagem recorrente, gere nesta ordem e só então o resto:

1. *character model sheet* — mesma personagem em frente, perfil e 3/4;
2. folha de expressões;
3. todas as demais imagens, passando as duas folhas em `referencias` (lista de caminhos, no
   `gerar_imagem`) para manter o rosto, o cabelo e a roupa consistentes.

**Antes da primeira chamada, proteja o que já existe.** Se `public/assets/` já tem assets de
uma rodada anterior (outro provedor, outra direção de arte), mova-os para
`public/assets/_<provedor-anterior>/` e copie o plano para `midias.<provedor>.json`. As
ferramentas gravam **por cima** do mesmo caminho — sem esse passo, a versão anterior some sem
aviso e não há como comparar as duas.

Depois de aprovado, chame as ferramentas `mcp__google-midia__*` item por item:

- **imagem:** `gerar_imagem` com `id`, `prompt`, `largura`, `altura`. A ferramenta escolhe a
  razão e a resolução (1K/2K/4K) pelas dimensões, reamostra para o tamanho de exibição e
  salva JPEG progressivo q80 em `public/assets/<id>.jpg` — 25–80 KB, sem passo manual.
  Passe `manter_original: true` quando o arquivo cru de 2K/4K ainda for servir (poster de
  hero, imagem de referência de personagem, `imagem_inicial` de vídeo);
- **vídeo:** `gerar_video` devolve o **id da operação** e não espera nada. Consulte com
  `status_video` (`job` + `id` para já baixar o mp4). Depois rode `preparar_video`, que faz o
  reencode de `$SKILL/docs/video.md` (keyframe por frame, sem áudio, faststart). O reencode é
  obrigatório, não opcional, mesmo fora de `scroll-driven`;
- **nunca regere** um asset que já existe em `public/assets/` sem o usuário pedir — exceto
  pelo caminho de reprovação descrito na Etapa 4;
- ao final, rode `atualizar_inventario` (ou
  `python "$FERR/gerar_midia.py" midias.json --so-inventario`): ele varre os assets em
  disco e regrava `inventario_midias.html` com preview, caminho, dimensão, prompt e o
  `aceite` de cada um. Não gera nada e não cobra. Não escreva esse HTML na mão.

**Parâmetros de controle** — é onde mora a diferença entre pedir e dirigir:

| Parâmetro | Ferramenta | Para quê |
|---|---|---|
| `referencias` | `gerar_imagem` | caminhos de imagens que o modelo deve seguir — *model sheet* e folha de expressões de personagem, ou o asset anterior quando você quer variação e não recomeço |
| `imagem_inicial` | `gerar_video` | primeiro frame do clipe: o Veo parte dessa imagem em vez de inventar o enquadramento |
| `negative_prompt` | `gerar_video` | o que não pode aparecer (em imagem, a negativa vai no fim do próprio `prompt`) |
| `manter_original` | `gerar_imagem` | guarda o arquivo cru além do JPEG de exibição |
| `qualidade` | `gerar_imagem` | força 1K/2K/4K quando as dimensões não dão a resolução que você quer |

### O poster do hero

Duas rotas, e a escolha muda o resultado:

- **Hero com arte dirigida (padrão).** Gere o poster no Nano Banana Pro com
  `manter_original: true`, dirigindo composição, grade de cor e a área escura para o texto.
  Passe o arquivo cru como `imagem_inicial` do `gerar_video` — aí o poster **é** o primeiro
  frame, em resolução maior e com o enquadramento que você escolheu. Depois rode
  `preparar_video` com **`poster: false`** e aponte o `<video poster="...">` para a imagem
  gerada. Custa uma imagem a mais (US$ 0,134) e é o que vale o dinheiro: com
  `prefers-reduced-motion` esse frame é o que fica na tela o tempo todo.
- **Vídeo de pano de fundo.** Aí o poster sai do próprio clipe: `preparar_video` com
  `frame_poster` num quadro que se sustente sozinho. De graça, e casa com o vídeo por
  construção.

`preparar_video` não sobrescreve um poster que já exista no destino — avisa e mantém.
Para forçar a extração assim mesmo, passe `poster: true` explícito.

## Etapa 4 — Aplicar e verificar

### 4.0 — Olhe cada asset antes de aplicar

**Passo obrigatório, não pule.** Abra cada arquivo gerado com a ferramenta `Read` e compare
com o `aceite` que você escreveu. O modelo acerta a maior parte e erra de um jeito plausível:
o circuito vira outro circuito, os carros que deviam estar correndo aparecem estacionados em
pose de catálogo, a personagem muda de rosto. Nada disso aparece no texto de retorno da
ferramenta — só olhando.

Reprovou no `aceite`:

1. diga o que saiu, o que o item pedia e por que não serve;
2. reescreva o prompt atacando o desvio **pelo nome** (é aqui que a negativa específica
   funciona) e atualize o item no `midias.json`;
3. informe o custo da regeração (US$ 0,134 por imagem Pro) e **peça o ok** — salvo se o
   usuário já autorizou a rodada de correção;
4. regere com o mesmo `id`, para não criar arquivo órfão.

Duas tentativas no mesmo item sem passar no aceite: pare e leve ao usuário. A terceira
costuma ser dinheiro jogado fora — o que falta é decisão de direção de arte, não outra
rodada.

### 4.1 — Aplicar

**Num site que já existe, o menor toque possível.** Se você manteve o `id` do plano igual ao
nome do arquivo que a página já pedia, o asset cai no lugar e **não há nada para editar** —
é o caminho preferido. Quando precisar mexer na marcação:

| Onde | O que muda |
|---|---|
| HTML puro | `src` e `alt`; mantenha `width`/`height` para não criar layout shift |
| React/Next (`src="/img/x.jpg"`) | nada, se o nome bater. `next/image` exige `width`/`height` ou `fill` |
| import de bundler (`import hero from "..."`) | grave o arquivo **no caminho do import**, não em `public/` |
| Vue/Svelte/Astro | igual ao HTML; `:src`/`{src}` dinâmico exige achar a variável antes |
| `background-image` no CSS | troque a `url()` na regra; a dimensão vem do CSS, não da tag |

Não reformate o arquivo, não reordene atributos, não "melhore" o CSS de passagem: num
projeto em produção, um diff grande esconde a mudança que importa.

1. Aponte cada `<img>`/`<video>` para o asset final, mantendo `width`/`height` do canvas.
2. Use `object-fit: cover` quando o provedor devolver um aspect ratio diferente do pedido.
   O `gerar_imagem` já entrega no tamanho exato, mas escolhe a razão suportada mais próxima
   (`16:9`, `4:5`, …) antes de reamostrar — dimensões fora dessas razões ganham um leve
   esticamento. Se for perceptível, peça `redimensionar: false` e corte você mesmo.
3. Abra a página e confira: nenhum layout shift, o scrub do vídeo acompanha a rolagem,
   e o mobile não quebra em 390 px de largura.
   - Site existente: use o **dev server do próprio projeto** (`npm run dev` e afins), que é
     onde o build resolve os imports e os caminhos de asset. Página estática sem build:
     `file://` é bloqueado no navegador automatizado — suba `python -m http.server` e use `127.0.0.1`.
   - O redimensionamento de janela não desce abaixo de ~500 px no Windows. Para testar 390,
     monte uma página temporária com `<iframe width="390">` apontando para a `index.html`:
     dentro do iframe as media queries valem de verdade.
   - **Hero no topo com `scroll-driven`:** a fórmula do `scroll-video.js` é
     `(vh - top) / (vh + altura)`, que pressupõe o elemento *entrando* pela base. Um vídeo
     no topo da página já nasce com ~56% do percurso gasto e termina antes da primeira tela.
     Corrija com `data-scroll-start="0.58" data-scroll-end="1"` e confira lendo
     `video.currentTime` em várias posições de rolagem — não confie no olho.
4. **Escreva o `alt` olhando a imagem, não o prompt.** O prompt é o que você pediu; o `alt` é
   o que está lá. Quando um asset é trocado, o `alt` correspondente é revisto no mesmo passo —
   `alt` herdado de uma rodada anterior descreve uma imagem que não existe mais, e é a parte
   do site que só quem usa leitor de tela percebe que está errada.
5. Reporte o que foi gerado, o que foi reaproveitado, o que reprovou e foi regerado, e o
   custo somado da rodada.

## Provedores

**Principal — MCP `google-midia`**, servidor stdio que acompanha a skill
(`$FERR/mcp_google_midia.py`). Fala com a API do Gemini; a chave fica no `env` do
registro, nunca no código. Registre uma vez, no escopo de usuário, para valer em
qualquer projeto:

```bash
claude mcp add google-midia -s user --env GEMINI_API_KEY=<sua-chave>   -- python "$HOME/.claude/skills/design-to-mcp/ferramentas/mcp_google_midia.py"
```

Confira com `claude mcp list` — tem que aparecer `✔ Connected`.

Se as ferramentas `mcp__google-midia__*` sumirem, o servidor não subiu: Python fora do
PATH, caminho errado ou chave ausente. Não é token vencido — a chave do Gemini não expira
como sessão. Editar o `.py` exige reiniciar o Claude Code para valer.

**Onde os arquivos caem:** o servidor resolve caminho relativo a partir do cwd, ou seja, do
projeto onde você abriu o Claude Code — `public/assets/hero.jpg` é do projeto, não da
skill. `listar_modelos` imprime a raiz em uso no rodapé; se ela vier errada, force com a
variável `MIDIA_RAIZ` no registro do MCP.

| Ferramenta | O que faz |
|---|---|
| `listar_modelos` | modelos de imagem e vídeo liberados para a chave |
| `estimar_custo` | custo em USD do `midias.json` (ou de itens inline) — use na PARADA 2 |
| `gerar_imagem` | Nano Banana Pro → `public/assets/<id>.jpg` já reamostrado |
| `gerar_video` | Veo 3.1, submete e devolve o id da operação |
| `status_video` | consulta a operação e baixa o mp4 quando pronta |
| `preparar_video` | reencode de `$SKILL/docs/video.md` + poster, via ffmpeg |
| `atualizar_inventario` | regrava `inventario_midias.html` a partir dos assets em disco (não cobra) |

Modelos padrão: `gemini-3-pro-image-preview` (imagem) e `veo-3.1-fast-generate-preview`
(vídeo). Dá para trocar por chamada (`modelo`) ou no `env` do registro
(`GEMINI_IMAGE_MODEL`, `GEMINI_VIDEO_MODEL`).

### Custos (ai.google.dev/gemini-api/docs/pricing, 20/08/2026, USD)

| Modelo | Uso | Custo |
|---|---|---|
| `gemini-3-pro-image` (Nano Banana Pro) | imagem 1K/2K | 0,134 |
| `gemini-3-pro-image` | imagem 4K | 0,24 |
| `gemini-3.1-flash-image` (Nano Banana 2) | imagem 1K / 2K / 4K | 0,067 / 0,101 / 0,151 |
| `gemini-2.5-flash-image` (Nano Banana) | imagem | 0,039 |
| `veo-3.1-generate` | vídeo, por segundo 720p/1080p | 0,40 |
| `veo-3.1-fast-generate` | vídeo, por segundo 720p / 1080p | 0,10 / 0,12 |
| `veo-3.1-lite-generate` | vídeo, por segundo 720p / 1080p | 0,05 / 0,08 |

O vídeo é sempre a linha cara do plano. O combo padrão de hero — 4s a 720p no `fast` — sai
por **US$ 0,40**, mais que três imagens Pro; o mesmo clipe em 1080p obriga a 8 segundos e
custa **US$ 0,96**. Some com `estimar_custo` antes da PARADA 2; a mesma tabela vive no topo
do `.py` e precisa ser revisada junto com a página de preços.

**O Veo amarra resolução e duração:** 1080p só sai em **8 segundos**; 4s e 6s exigem 720p.
Pedir 1080p com 4s devolve `400 INVALID_ARGUMENT` — não chega a cobrar, mas custa uma ida
inútil. Para hero curto, 720p a 4s (US$ 0,40) é o combo padrão; a página escala o vídeo
para a largura do container de qualquer forma.

**Quatro armadilhas que custam dinheiro:**

1. **Gere um item por vez.** Nada de disparar o plano inteiro em paralelo: erro no meio deixa
   metade cobrada e nenhum controle de qual asset ficou de pé.
2. **`gerar_video` não espera o vídeo.** Ele submete e devolve a operação — quem espera é
   `status_video`, que faz long-poll de até ~55s e pode voltar `ainda processando` várias
   vezes. Isso é normal: chame de novo. Tratar como falha e ressubmeter cobra o vídeo duas vezes.
3. **A imagem cobra por resolução, não por tamanho pedido.** `largura`/`altura` de 1440 px
   levam a ferramenta a gerar em 2K. Se o placeholder for pequeno, deixe as dimensões reais —
   não peça 4K "por garantia".
4. **Prompt vago cobra duas vezes.** Toda geração que reprova no `aceite` é dinheiro gasto
   num arquivo que vai para o lixo. Os cinco minutos escrevendo o prompt com a copy do bloco
   na frente valem mais que qualquer rodada de correção.

**Fallback — API direta** via `$FERR/gerar_midia.py`, só imagem, sem passar pelo MCP:

| Provedor | Chave | Modelo (env, opcional) |
|---|---|---|
| `gemini` | `GEMINI_API_KEY` | `GEMINI_IMAGE_MODEL` |
| `openai` | `OPENAI_API_KEY` | `OPENAI_IMAGE_MODEL` |
| `replicate` | `REPLICATE_API_TOKEN` | `REPLICATE_IMAGE_MODEL` |

`python "$FERR/gerar_midia.py" --listar-modelos` lista os modelos de imagem
disponíveis na conta Gemini, para confirmar o nome antes de gerar.
