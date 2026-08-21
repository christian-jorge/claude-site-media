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

A primeira funciona em HTML puro, React/Next, Vue, Svelte, Astro, PHP e `background-image`
de CSS — lendo os arquivos do projeto ou o HTML servido por um `localhost` no ar.

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
| **Exigir aprovação de custo** | ligado, gerar sem o token da estimativa falha **antes** de cobrar |

A chave é um campo `sensitive`: a digitação vem mascarada e o valor vai para o
**armazenamento seguro** do Claude Code. Ela não entra em `settings.json`, não entra em
`~/.claude.json`, não passa pela linha de comando de processo nenhum e não encosta num
arquivo do seu repositório. **As gerações são cobradas na sua conta Google.**

Depois de instalar, `/mcp` tem que mostrar `google-midia` conectado.

### Requisitos

| | Para quê |
|---|---|
| Python 3 | todas as ferramentas |
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

```bash
FERR="$HOME/.claude/skills/design-to-mcp/ferramentas"

# o que a página tem, com a copy de cada bloco e o que está faltando
python "$FERR/ler_site.py" .

# só os slots vazios, já virando esqueleto de plano
python "$FERR/ler_site.py" . --so-faltando --plano midias.json

# quanto custaria, sem chamar a API
python "$FERR/gerar_midia.py" midias.json --dry-run

# regravar o inventário visual a partir do que já está em disco
python "$FERR/gerar_midia.py" midias.json --so-inventario
```

O esqueleto do plano sai com `prompt` e `aceite` em branco de propósito — é você (ou a
skill) que escreve, ancorado na copy que o extractor trouxe junto.

## Como funciona

```
ler_site.py       acha os slots: dimensão, arquivo faltando, copy vizinha, tokens de cor
      ↓
midias.json       um item por slot: prompt, dimensão e o critério de aceite
      ↓
MCP google-midia  gerar_imagem (Nano Banana Pro) · gerar_video + preparar_video (Veo 3.1)
      ↓
public/assets/    JPEG progressivo no tamanho de exibição · MP4 com keyframe por frame
```

O **critério de aceite** é o que separa esta skill de um wrapper de API: cada item declara,
antes de gerar, o que precisa estar na imagem ("dois carros idênticos, em movimento,
Interlagos reconhecível ao fundo"). Depois de gerar, a skill **olha** cada arquivo e compara.
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

Com **exigir aprovação de custo** ligado, gerar sem o token que a PARADA 2 emite
falha antes de cobrar. Desligado, a chamada passa mas a resposta vem marcada
`AVISO: gerado SEM orcamento aprovado`. Os três só mudam em `/plugin` e valem no
próximo start do servidor — é isso que os torna uma trava, e não um lembrete.

## Limitações conhecidas

- **SPA renderizada no cliente**: `--url` só enxerga o HTML servido. Se a rota devolver casca
  vazia, o extractor avisa — leia a pasta do projeto, ou salve o DOM renderizado num `.html`.
- **`src` dinâmico** (`src={hero}`, `:src="foto"`): o extractor marca, mas não resolve para
  qual arquivo aponta. Descubra antes de nomear o asset.
- **Dimensão não declarada**: quando não há `width`/`height` nem regra de CSS, o slot é
  contado no rodapé e a skill pergunta em vez de inventar.
- **Marca e semelhança**: os prompts pedem livery sem patrocinador e nada de texto, mas
  modelo de imagem erra. Olhe o que saiu antes de publicar.

## Testes

Stdlib pura: não precisa de pytest, não precisa de chave, não toca a rede.

```bash
python testes/rodar.py                  # tudo
python testes/rodar.py test_extratores  # só um módulo
python testes/rodar.py --atualizar      # regrava os instantâneos
```

Os instantâneos em `testes/instantaneos/` congelam o que o agente lê na PARADA 1 e o
`midias.json` que vira contrato com o gerador — ou seja, **a contagem que a PARADA 2
transforma em dólar**. Quando um diff aparece ali, leia linha a linha antes de regravar:
aceitar em bloco transforma a rede de segurança em teatro. As fixtures estão descritas em
[`testes/fixtures/LEIA-ME.md`](testes/fixtures/LEIA-ME.md).

## Licença

MIT — veja [LICENSE](LICENSE).
