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
