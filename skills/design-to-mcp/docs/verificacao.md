# Verificar no navegador

Carregue este arquivo **só quando houver navegador automatizado** (extensão do Chrome,
Playwright). A skill não exige e não instala nenhum: sem navegador, faça a verificação
possível e **declare o que ficou sem teste** — a Etapa 4.2 do `SKILL.md` traz a forma.

## Onde servir a página

- **Site existente:** use o **dev server do próprio projeto** (`npm run dev` e afins). É lá
  que a build resolve os imports e os caminhos de asset — abrir o arquivo direto mostra um
  site que não é o que o usuário vê.
- **Página estática sem build:** `file://` é bloqueado no navegador automatizado. Suba
  `python -m http.server` na raiz que a build serviria e use `127.0.0.1`.

A URL importa: `public/assets/hero.mp4` é onde o arquivo **mora**; o navegador pede
`/assets/hero.mp4`. Se a página abre com a imagem quebrada mas o arquivo está em disco, é
quase sempre esta confusão.

## O que conferir

1. **Layout shift.** A tag tem `width`/`height` (ou `aspect-ratio`) e o bloco não pula quando
   a imagem chega.
2. **Mobile em 390 px.** O redimensionamento de janela não desce abaixo de ~500 px no
   Windows. Para testar 390, monte uma página temporária com
   `<iframe width="390" height="800" src="http://127.0.0.1:PORTA/"></iframe>`: dentro do
   iframe as media queries valem de verdade.
3. **Scrub do vídeo por rolagem.** Não confie no olho: leia `video.currentTime` em várias
   posições de rolagem e confira que ele cresce de 0 até perto da duração.

```js
// no console da página, com o vídeo visível
const v = document.querySelector('video.scroll-driven');
for (const y of [0, 300, 600, 900, 1200]) {
  window.scrollTo(0, y);
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  console.log(y, v.currentTime.toFixed(2));
}
```

Um vídeo no topo da página que já começa perto do fim está sem `data-scroll-start="auto"` —
veja `docs/video.md`.

4. **Console limpo.** `scroll-video.js` avisa em `console.warn` quando `data-smooth` ou a
   faixa `data-scroll-start`/`data-scroll-end` estão fora do intervalo válido.

## Não dispare diálogos

`alert`, `confirm` e `prompt` bloqueiam o navegador automatizado e a sessão trava. Se a
página tiver um botão que abre diálogo, não clique nele: avise o usuário.
