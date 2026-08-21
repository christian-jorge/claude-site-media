# Fixtures de teste

Sete arquetipos, escolhidos por **caminho de codigo distinto**, nao por tecnologia.
Cada uma prende um defeito que ja custou dinheiro. Mexer numa delas muda o
instantaneo correspondente — regrave com `python testes/rodar.py --atualizar` e
**revise o diff linha a linha** antes de aceitar.

| Fixture | O que ela exercita | Nao mexa em |
|---|---|---|
| `site-html-css` | HTML puro com `<header>`/`<section>`, CSS externo com seletor descendente `.card .card-media`, `background-image`, `<video poster>` + `<source>`, copy acentuada, **um** asset ja em disco | o `torno.jpg` existente — e ele que faz `pasta_de_saida` escolher por frequencia em vez de cair no fallback |
| `site-pastas-mistas` | assets em `public/img/` **e** `assets/equipe/`, extensoes `.webp` e `.png`, `src` root-absoluto, e um background cujo arquivo nao tem relacao com o seletor | as duas raizes de asset — e a fixture que so fecha quando o campo `destino` existir |
| `site-next-jsx` | `import` de bundler (`src={hero}`), `src` literal ao lado, `width={N}` em chaves, dois blocos de copy seguidos | a ordem dos dois blocos: e o que exercita a janela de copy do `ler_framework` |
| `site-vue-svelte` | `:src`, `{src}`, `bind:src`, `<NuxtImg>` e `srcset` | a tag capitalizada `NuxtImg` e o `:` do binding |
| `site-quebrado` | `<div>` nao fechada, `<` solto no texto, atributo sem aspas | a marcacao quebrada — e o ponto do arquivo |
| `site-colisao-de-id` | dois `hero.jpg` em pastas diferentes, dois `alt` identicos, dois backgrounds com o mesmo seletor | os nomes repetidos |
| `canvas-basico` | o contrato REAL do `/design`: dois `.dc.html` (cada um e um artboard), `canvas.json` como manifesto, `<sc-for>` + `<script data-dc-script>`, um embrulho `.col-arte` e um `media-nav` que NAO podem virar slot | o `canvas.json`, os nomes dos arquivos e o `renderVals()` |

Nenhuma fixture e escrita pelos testes: `ajuda.copiar_fixture` copia para um
diretorio temporario e o teste mexe na copia.
