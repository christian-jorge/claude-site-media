# claude-site-media

Skill do [Claude Code](https://claude.com/claude-code) que gera as **imagens e vídeos que
faltam no seu site** — com a API do Google Gemini (Nano Banana Pro para imagem, Veo 3.1
para vídeo) e prompts ancorados na copy de cada bloco da página.

Não é um gerador de imagem genérico. Ele lê a sua página primeiro: descobre onde estão os
slots de mídia, com que dimensão, quais estão vazios e **qual texto está ao lado de cada
um** — e é esse texto que vira o prompt. A diferença entre "carro de corrida em circuito
tropical" e "992 Cup cortando a zebra do S do Senna, volta de classificação sozinho na
pista" é a diferença entre foto de banco de imagens e a imagem daquele card.

## Duas portas de entrada

| Situação | O que acontece |
|---|---|
| **Site que já existe e roda** | lê os slots de mídia da página, gera só o que falta e aplica |
| **Canvas do `/design`** | constrói a landing page a partir dos artboards e preenche a mídia |

A primeira funciona em HTML puro, React/Next, Vue, Svelte, Astro, Markdown/MDX, PHP e nas
engines de template (Liquid do Shopify, Twig, Blade, Handlebars, Nunjucks, EJS, ERB,
Razor), mais o `background-image` de CSS/SCSS/Sass/Less — lendo os arquivos do projeto ou
o HTML servido por um `localhost` no ar.

## Instalação

Dentro do Claude Code, em qualquer projeto:

```
/plugin marketplace add christian-jorge/claude-site-media
/plugin install design-to-mcp@claude-site-media
```

Duas linhas, idênticas no Windows, no Linux e no macOS. Não há script para rodar, nada
para copiar à mão e nenhum `claude mcp add` para montar: a skill, o comando
`/gerar-imagem` e o servidor MCP do Gemini vêm no mesmo pacote. Versão nova depois é
`/plugin marketplace update`.

### O formulário de instalação

O `/plugin install` pergunta o que o servidor precisa saber:

| Campo | Para quê |
|---|---|
| **Chave da API do Gemini** | pegue em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Interpretador Python** | deixe `python` se o do PATH serve; se a máquina tem mais de um, cole o caminho do que tem Pillow |
| **Teto de 24 h / por chamada** | o servidor recusa a geração que passar disso, contando o que já gastou |
| **Exigir aprovação de custo** | **vem ligado**: gerar sem o token da estimativa falha **antes** de cobrar |

A chave é um campo `sensitive`: a digitação vem mascarada e o valor vai para o
**armazenamento seguro** do Claude Code. Ela não entra em `settings.json`, não entra em
`~/.claude.json`, não passa pela linha de comando de processo nenhum e não encosta num
arquivo do seu repositório. **As gerações são cobradas na sua conta Google.**

Depois de instalar, `/mcp` tem que mostrar `google-midia` conectado.

### Requisitos

| | Para quê |
|---|---|
| Python 3.9+ | todas as ferramentas (a CI testa 3.9 e 3.12) |
| [Pillow](https://pypi.org/project/pillow/) | reamostrar as imagens (`pip install pillow`) |
| ffmpeg no PATH | só vídeo: reencode e poster |
| Node | opcional, só para `node --check` depois de editar `.js` |

## Uso

Dentro do seu projeto, no Claude Code:

```
/gerar-imagem                          # descobre o alvo sozinho
/gerar-imagem ../meu-site              # aponta uma pasta
/gerar-imagem http://localhost:3000    # aponta o servidor no ar
```

A skill para **três vezes** e espera você: no briefing dos slots encontrados, na lista de
gerações com o custo em dólar somado, e na conferência final — que re-lê a página e prova
que cada arquivo pago está onde ela procura. Nada é cobrado sem esse aval.

### Direto no terminal, sem a skill

O `/plugin` instala em `~/.claude/plugins/cache/claude-site-media/design-to-mcp/<versao>/`.
Ache a pasta das ferramentas sem depender da versão:

```bash
# Bash / Git Bash
FERR=$(find ~/.claude/plugins -type d -path '*design-to-mcp*' -name ferramentas | head -1)
```
```powershell
# PowerShell
$FERR = (Get-ChildItem "$HOME\.claude\plugins" -Recurse -Directory -Filter ferramentas |
         Where-Object { $_.FullName -like '*design-to-mcp*' } | Select-Object -First 1).FullName
```

```bash
# o que a página tem, com a copy de cada bloco e o que está faltando
python "$FERR/ler_site.py" .

# lendo do servidor no ar, uma ou mais rotas
python "$FERR/ler_site.py" --url http://localhost:3000 --url http://localhost:3000/precos

# só os slots vazios, já virando esqueleto de plano
python "$FERR/ler_site.py" . --so-faltando --plano midias.json

# quanto custaria, sem chamar a API
python "$FERR/gerar_midia.py" midias.json --dry-run

# regravar o inventário visual a partir do que já está em disco
python "$FERR/gerar_midia.py" midias.json --so-inventario
```

| Flag de `ler_site.py` | Para quê |
|---|---|
| `--so-faltando` | só os slots cujo arquivo não está comprovadamente em disco |
| `--plano <arquivo>` | grava o esqueleto do `midias.json`; rodar de novo **funde por destino** e preserva prompt e aceite |
| `--forcar` | reescreve o `--plano` do zero, perdendo o que você escreveu |
| `--json <arquivo>` | grava o briefing estruturado, além do relatório na tela |
| `--incluir-externos` | traz para a lista a imagem hospedada fora do projeto e o asset de bundler |
| `--url` | lê do servidor no ar em vez do disco (repita para várias rotas) |

O esqueleto do plano sai com `prompt` e `aceite` em branco de propósito — é você (ou a
skill) que escreve, ancorado na copy que o extractor trouxe junto.

## Como funciona

```
ler_site.py       acha os slots: dimensão, arquivo faltando, copy vizinha, tokens de cor
      ↓
midias.json       um item por slot: destino, prompt, dimensão e o critério de aceite
      ↓
MCP google-midia  gerar_imagem (Nano Banana Pro) · gerar_video + preparar_video (Veo 3.1)
      ↓
o `destino`       JPEG progressivo no tamanho de exibição · MP4 com keyframe por frame
```

**Quem endereça o arquivo é o campo `destino` de cada item** — pasta, nome e extensão que a
*página* pede —, não o `id`, que é só rótulo humano. Um site com marca em `assets/`,
conteúdo em `public/img/` e vídeo em `public/video/` tem três destinos e nenhum problema.
`public/assets/` é apenas o *fallback* de item sem destino declarado.

O **critério de aceite** é o que separa esta skill de um wrapper de API: cada item declara,
antes de gerar, o que precisa estar na imagem — e só o que dá para **afirmar olhando o
arquivo**: "dois carros idênticos em movimento, zebra vermelha e branca, arquibancada ao
fundo, nenhuma letra na imagem". Não "Interlagos reconhecível ao fundo": identidade de
lugar, marca ou pessoa vira chute com cara de certeza na hora de conferir. Depois de gerar,
a skill **olha** cada arquivo e compara.
Reprovou, ela diz por quê, reescreve o prompt atacando o desvio pelo nome e pede seu aval
antes de gastar de novo.

### Vídeo animado por rolagem

`scroll-video.js` amarra o `currentTime` do vídeo à posição de rolagem. O Veo devolve MP4
com keyframes esparsos, e sem reencode o scrub trava — por isso `preparar_video` (keyframe
por frame, sem áudio, faststart) é obrigatório, não opcional. As regras de marcação estão em
[`skills/design-to-mcp/docs/video.md`](skills/design-to-mcp/docs/video.md).

## Custos (USD, tabela de 20/08/2026)

| Modelo | Uso | Custo |
|---|---|---|
| `gemini-3-pro-image` (Nano Banana Pro) | imagem 1K/2K | 0,134 |
| `gemini-3-pro-image` | imagem 4K | 0,24 |
| `gemini-3.1-flash-image` (Nano Banana 2) | imagem 1K / 2K / 4K | 0,067 / 0,101 / 0,151 |
| `gemini-2.5-flash-image` (Nano Banana) | imagem, qualquer tier | 0,039 |
| `veo-3.1-generate` | vídeo, por segundo 720p / 1080p | 0,40 |
| `veo-3.1-fast-generate` | vídeo, por segundo 720p / 1080p | 0,10 / 0,12 |
| `veo-3.1-lite-generate` | vídeo, por segundo 720p / 1080p | 0,05 / 0,08 |

Hero de 4s a 720p sai por US$ 0,40 — mais que três imagens Pro. **O Veo amarra resolução e
duração:** 1080p só existe com 8 segundos; 4s e 6s exigem 720p.

A tabela acima é um resumo. **A fonte é uma só:** `CUSTO_IMAGEM`/`CUSTO_VIDEO_S` em
[`skills/design-to-mcp/ferramentas/contrato.py`](skills/design-to-mcp/ferramentas/contrato.py),
de onde o MCP, o fallback e o `--dry-run` leem. Havia três cópias divergentes; ao atualizar
o preço, mexa só nela — e confira contra a
[página de preços](https://ai.google.dev/gemini-api/docs/pricing).

`estimar_custo` marca os itens que já existem em disco, mostra separado quanto custa gerar
só o que falta, e **avisa quando o total é apenas um piso** — quando algum modelo do plano
não está na tabela, o número vem marcado `(PISO)` em vez de sair silenciosamente menor.
O servidor também tem teto próprio, preenchido no formulário de instalação: um teto
acumulado em 24 h (padrão US$ 5,00) e um por chamada (padrão US$ 1,00). O gasto é
contado num ledger em disco gravado **antes** de cada POST cobrado, então sobrevive
a `/compact`, a reinício e a troca de sessão — e o ledger é por máquina, não por
projeto, senão o teto de 24 h valeria vezes o número de projetos abertos.

**Exigir aprovação de custo vem ligado**: gerar sem o token que a PARADA 2 emite falha
antes de cobrar, e a PARADA 2 deixa de ser um pedido educado. Desligue só se algum fluxo
seu gera fora da skill — aí a chamada passa, mas a resposta vem marcada
`AVISO: gerado SEM orcamento aprovado`. Os três só mudam em `/plugin` e valem no próximo
start do servidor — é isso que os torna uma trava, e não um lembrete. Quem instalou antes
desta versão mantém o valor que já escolheu: confira em `/plugin`.

O servidor diz em que estado subiu. Se `/mcp` mostrar o log dele, a linha
`orcamento da PARADA 2: EXIGIDO` é a confirmação de que a trava está de pé.

## Limitações conhecidas

- **SPA renderizada no cliente**: `--url` só enxerga o HTML servido. Se a rota devolver casca
  vazia, o extractor avisa — leia a pasta do projeto, ou salve o DOM renderizado num `.html`.
- **`src` dinâmico** (`src={hero}`, `:src="foto"`): o extractor marca, mas não resolve para
  qual arquivo aponta. Descubra antes de nomear o asset.
- **Dimensão não declarada**: quando não há `width`/`height` nem regra de CSS, o slot é
  contado no rodapé e a skill pergunta em vez de inventar.
- **Marca e semelhança**: os prompts pedem livery sem patrocinador e nada de texto, mas
  modelo de imagem erra. Olhe o que saiu antes de publicar.

## O que tem no repositório

```
.claude-plugin/     plugin.json (a versão e o formulário de instalação) + marketplace.json
.mcp.json           declara o servidor google-midia; é ele que passa a chave e os tetos
commands/           /gerar-imagem — a porta de entrada que descobre o alvo sozinho
skills/design-to-mcp/
  SKILL.md          o procedimento: 4 etapas, 3 paradas obrigatórias
  midias.example.json  o contrato v2 do plano, comentado por exemplo
  docs/             carregados sob demanda: video.md, provedores.md,
                    personagem.md, verificacao.md
  ferramentas/
    contrato.py           vocabulário do plano e a ÚNICA tabela de preço
    ler_design.py         artboards .dc.html do /design  → briefing
    ler_site.py           site que já existe            → briefing + esqueleto do plano
    gerar_midia.py        fallback por API direta, inventário HTML e --dry-run
    mcp_google_midia.py   o servidor MCP: 7 ferramentas, ledger de gasto e tetos
    scroll-video.js       amarra o currentTime do vídeo à rolagem
testes/             a suíte de stdlib pura, as 7 fixtures e os instantâneos
```

## Testes

Stdlib pura: não precisa de pytest, não precisa de chave, não toca a rede.

```bash
python testes/rodar.py                  # tudo
python testes/rodar.py test_extratores  # só um módulo
python testes/rodar.py --atualizar      # regrava os instantâneos
```

No GitHub Actions a mesma suíte roda em Linux e Windows, no 3.9 e no 3.12, e um passo extra
falha se a rodada tiver mexido em qualquer arquivo versionado de `testes/` — instantâneo que
muda sozinho é instantâneo que não prova nada.

Os instantâneos em `testes/instantaneos/` congelam o que o agente lê na PARADA 1 e o
`midias.json` que vira contrato com o gerador — ou seja, **a contagem que a PARADA 2
transforma em dólar**. Quando um diff aparece ali, leia linha a linha antes de regravar:
aceitar em bloco transforma a rede de segurança em teatro. As fixtures estão descritas em
[`testes/fixtures/LEIA-ME.md`](testes/fixtures/LEIA-ME.md).

## Licença

MIT — veja [LICENSE](LICENSE).
