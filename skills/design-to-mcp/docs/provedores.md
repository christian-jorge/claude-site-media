# Provedores

Carregue este arquivo quando: as ferramentas `mcp__google-midia__*` **não aparecerem**,
quando for preciso registrar o servidor pela primeira vez, ou quando quiser trocar de
modelo. Numa rodada normal nada aqui é necessário.

**Principal — MCP `google-midia`**, servidor stdio declarado no `.mcp.json` do
plugin. Ele sobe junto com o plugin; não há comando de registro a rodar. A chave
vem do campo `sensitive` do formulário de `/plugin install`, que a guarda no
armazenamento seguro do Claude Code — nunca no código, num argumento de comando
ou num arquivo do projeto.

Confira com `/mcp` — `google-midia` tem que aparecer conectado.

Se as ferramentas `mcp__google-midia__*` sumirem, o servidor não subiu. A causa quase
sempre é o campo **Interpretador Python**: se o que está lá não existe ou não tem
Pillow, o servidor recusa. Rode `/plugin` e corrija o campo. Não é token vencido — a
chave do Gemini não expira como sessão. Editar o `.py` exige `/reload-plugins`, ou
reiniciar o Claude Code, para valer.

**Onde os arquivos caem:** o manifesto do plugin passa `${CLAUDE_PROJECT_DIR}` como raiz,
ou seja, o projeto onde você abriu o Claude Code — não um cwd adivinhado — `public/assets/hero.jpg` é do projeto, não da
skill. `listar_modelos` imprime a raiz em uso no rodapé; se ela vier errada, force com a
variável `MIDIA_RAIZ` no registro do MCP.

| Ferramenta | Cobra? | O que faz |
|---|---|---|
| `listar_modelos` | não | modelos de imagem e vídeo liberados para a chave; imprime a raiz em uso no rodapé |
| `estimar_custo` | não | custo em USD do `midias.json` (ou de itens inline) e o token `orc-...` — é a ferramenta da PARADA 2 |
| `gerar_imagem` | **sim** | Nano Banana Pro → grava no `destino` do item, recortado (não esticado) para a caixa do slot |
| `gerar_video` | **sim** | Veo 3.1: submete, devolve o id da operação e não espera |
| `status_video` | não | consulta a operação (long-poll ~55 s) e baixa `<destino sem extensão>-original.mp4` quando pronta |
| `preparar_video` | não | reencode de `$SKILL/docs/video.md` + poster, via ffmpeg |
| `atualizar_inventario` | não | regrava `inventario_midias.html` a partir dos assets em disco |

**Toda chamada leva `plano: "midias.json"`.** É de lá que sai o `destino`; sem ele a
ferramenta cai no default `public/assets/<id>.jpg` — pasta e extensão erradas, e o arquivo
pago não aparece na página. As duas que cobram declaram `destructiveHint: true` no schema,
que é o que faz o cliente MCP pedir confirmação.

Modelos padrão: `gemini-3-pro-image-preview` (imagem) e `veo-3.1-fast-generate-preview`
(vídeo). Dá para trocar por chamada (`modelo`) ou no `env` do registro
(`GEMINI_IMAGE_MODEL`, `GEMINI_VIDEO_MODEL`).

### O que o servidor lê do ambiente

O `.mcp.json` do plugin preenche tudo isto a partir do formulário de `/plugin install`;
a tabela existe para o registro manual e para diagnóstico.

| Variável | Padrão | Para quê |
|---|---|---|
| `GEMINI_API_KEY` | — | obrigatória; vem do campo `sensitive`, nunca de um arquivo do projeto |
| `MIDIA_RAIZ` | cwd do servidor | raiz dos caminhos relativos; o plugin passa `${CLAUDE_PROJECT_DIR}` |
| `MIDIA_LEDGER` | `<raiz>/.claude/state/midias-gastos.jsonl` | o `.jsonl` de gasto. O plugin o move para `${CLAUDE_PLUGIN_DATA}`, **por máquina**: no padrão, que é por projeto, o teto de 24 h valeria vezes o número de projetos abertos |
| `MIDIA_TETO_USD` | `5` | teto acumulado em 24 h |
| `MIDIA_TETO_CHAMADA_USD` | `1` | teto de uma única geração |
| `MIDIA_EXIGE_ORCAMENTO` | **ligado** pelo formulário do plugin | `1`/`true`/`sim`/`on` liga; qualquer outro valor, **e a ausência da variável**, desliga. Ligado, gerar sem o token `orc-...` da PARADA 2 **falha antes de cobrar**; desligado, passa e a resposta vem marcada `AVISO: gerado SEM orcamento aprovado` |
| `GEMINI_IMAGE_MODEL` / `GEMINI_VIDEO_MODEL` | os padrões acima | troca de modelo sem mexer no código |

Nos dois tetos, `off` (ou `none`, `sem`, `-1`) desliga a trava e **`0` bloqueia tudo** —
não é o mesmo campo em branco. Valor ilegível cai no padrão, em silêncio.

`MIDIA_EXIGE_ORCAMENTO` é o único que **não** tem padrão seguro no código: ausente, ele
fica desligado. É de propósito — se o padrão do código fosse "ligado", um formulário que
serializasse o campo desmarcado como string vazia tornaria o *desligar* do usuário inerte,
que é justamente a configuração-que-ninguém-lê. Quem registra o MCP à mão e quer a trava
passa `MIDIA_EXIGE_ORCAMENTO=1` explicitamente; o servidor imprime o estado em que subiu na
linha `orcamento da PARADA 2: ...`, então não há como ficar em dúvida.

As três travas de custo só mudam em `/plugin` e valem no **próximo start do servidor** — é
isso que as torna uma trava, e não um lembrete: não há como levantá-las de dentro da
sessão. O gasto é gravado no ledger **antes** de cada POST cobrado, então sobrevive a
`/compact`, a reinício e a troca de sessão.

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
custa **US$ 0,96**. Some com `estimar_custo` antes da PARADA 2. A tabela acima é cópia de leitura:
a fonte é `CUSTO_IMAGEM`/`CUSTO_VIDEO_S` em `$FERR/contrato.py`, de onde o MCP, o fallback
e o `--dry-run` leem. O casamento é por **prefixo**, para que um id datado
(`-preview`, `-001`) não caia fora da tabela e suma do total da PARADA 2.

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
