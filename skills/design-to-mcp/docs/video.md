# Regras de marcação de vídeo

Diretrizes obrigatórias para qualquer `<video>` gerado a partir de um artboard.

## 1. Atributos

Todo vídeo **deve** ter:

| Atributo | Por quê |
|---|---|
| `muted` | iOS e Chrome bloqueiam reprodução com áudio sem gesto do usuário. |
| `playsinline` | sem ele, o iOS abre o vídeo em fullscreen nativo e destrói o layout. |
| `poster="..."` | é o que aparece antes do carregamento; sem poster o bloco pisca em preto. |
| `preload="auto"` | scrub por rolagem exige os frames em buffer; `metadata` causa travamento. |
| `width` / `height` | reserva o espaço e evita layout shift (CLS). |

**Proibidos** em animação atrelada à rolagem: `autoplay`, `loop`, `controls`.
O tempo do vídeo é controlado por script — esses atributos brigam com o scrub.

## 2. Vídeo animado por rolagem

Adicione a classe `scroll-driven` e inclua o script:

```html
<video class="scroll-driven"
       src="/assets/hero.mp4"
       poster="/assets/hero-poster.jpg"
       width="1440" height="810"
       muted playsinline preload="auto"></video>

<script src="/js/scroll-video.js"></script>
```

**São URLs servidas, não caminhos de disco.** `public/assets/hero.mp4` é onde o arquivo
*mora*; o navegador pede `/assets/hero.mp4`, porque `public/` é a raiz que a build serve.
Escrever o caminho de disco na marcação dá 404 em todo framework que serve de `public/`.
E o `scroll-video.js` precisa estar **dentro** do projeto (copie de
`$SKILL/ferramentas/scroll-video.js` para `public/js/`): a página não carrega script de
fora dela.

Ajustes finos, todos opcionais:

- `data-scroll-start="auto"` — **para vídeo no topo da página.** O percurso vai de
  `-altura` (elemento inteiro abaixo da dobra) a `+viewport`, então um vídeo que já nasce
  visível começa com parte do percurso gasta e termina antes da primeira tela. `auto`
  calcula o ponto de partida a partir da caixa real, e continua certo quando a altura muda.
- `data-scroll-start="0.15"` — começa o scrub depois de 15% **do percurso**, que é
  `viewport + altura do elemento` — não 15% da viewport. Num vídeo de 810 px numa tela de
  900, 0.15 são 256 px de rolagem.
- `data-scroll-end="0.85"` — termina antes da saída completa.
- `data-smooth="0.12"` — suavização da interpolação, em **(0, 1]**. `1` desliga (scrub
  travado ao pixel). `0` não desliga: é valor inválido, avisado no console e trocado por
  0,12.

## 3. Codificação do arquivo

Scrub por rolagem depende de *seek* barato. Um MP4 comum tem keyframes a cada ~250
frames e o `currentTime` fica lento e granulado. Reencode com keyframe em todo frame:

```bash
ffmpeg -i entrada.mp4 -an -vf "scale=1440:-2,fps=30" \
       -c:v libx264 -crf 24 -g 1 -keyint_min 1 -pix_fmt yuv420p \
       -movflags +faststart public/assets/hero.mp4
```

- `-an` remove o áudio (o vídeo é mudo de qualquer forma; corta peso).
- `-g 1 -keyint_min 1` põe keyframe em todos os frames — arquivo maior, seek instantâneo.
- `-movflags +faststart` move o índice para o começo, permitindo início antes do download total.

Mantenha o resultado abaixo de ~6 MB. Se passar disso, reduza a resolução ou os FPS
antes de subir o CRF.

## 4. Acessibilidade

`scroll-video.js` respeita `prefers-reduced-motion: reduce` e não anima nesse caso —
o vídeo fica congelado no poster. Por isso o poster precisa ser um frame que funcione
sozinho, não um quadro intermediário sem sentido.

Mesmo sem animar, o script continua aplicando `muted`, `playsinline` e `pause()`: são o
que impede o iOS de abrir em tela cheia e o Chrome de bloquear a reprodução. E ele
escuta a troca da preferência — quem desliga a redução de movimento passa a ver o scrub
sem recarregar a página.

Duas formas de conseguir isso:

- **poster dirigido** — gere a imagem primeiro e passe-a como `imagem_inicial` do vídeo.
  O poster vira o primeiro frame, com resolução e composição que você escolheu (inclusive a
  área escura para o texto sobreposto). Rode o reencode com `poster: false` para não
  sobrescrevê-la;
- **poster extraído** — `frame_poster` num quadro que se sustente sozinho. Serve quando o
  vídeo é pano de fundo e ninguém vai olhar o frame parado com atenção.

## 5. Fallback

Se o vídeo não for essencial ao conteúdo, o poster já é fallback suficiente. Se for,
coloque uma `<img>` equivalente dentro de `<noscript>`.
