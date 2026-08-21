# Personagem recorrente

Carregue este arquivo quando o site tiver **mascote ou personagem que aparece em mais de uma
imagem**. Sem ele, cada geração inventa um rosto novo e a página fica com cinco pessoas
diferentes que deviam ser a mesma.

## A ordem importa, e ela custa duas imagens a mais

1. **Folha de modelo** (*character model sheet*): a mesma personagem em frente, perfil e 3/4,
   num fundo neutro, roupa e cabelo definidos. Gere com `manter_original: true`.
2. **Folha de expressões**: o mesmo rosto em quatro ou cinco estados (neutro, sorrindo,
   concentrado, surpreso). Também com `manter_original: true`.
3. **Todas as demais imagens**, passando as duas folhas em `referencias` (lista de caminhos,
   no `gerar_imagem`).

**As duas folhas entram no orçamento da PARADA 2.** São duas gerações Pro (US$ 0,268 no
total) que não estão em nenhum slot da página — se você as omitir da lista, o número que o
usuário aprovou não é o número que vai sair. Inclua-as no `midias.json` como itens normais,
com `destino` numa pasta fora da que a build serve (por exemplo
`_referencias/ana-modelo.jpg`), para não virarem asset publicado por acidente.

## O que escrever no prompt das folhas

A folha de modelo é a única imagem em que descrever a pessoa em detalhe vale a pena: idade
aparente, tipo de cabelo, cor de pele, roupa, acessórios. Nas imagens seguintes, **não repita
a descrição** — diga "a mesma personagem das imagens de referência" e gaste as palavras na
cena. Descrever de novo faz o modelo negociar entre a descrição e a referência, e o rosto
muda.

## Pessoas reais

Se a personagem representa alguém que existe — um sócio, uma cliente, um depoimento com nome
e sobrenome —, **pare e pergunte**. Gerar o rosto de uma pessoa real e publicá-lo como se
fosse ela é problema de direito de imagem, não de direção de arte. O caminho é foto de
verdade, ilustração declaradamente ilustrativa, ou nenhuma imagem.

## Aceite

Para as imagens que usam as folhas, o `aceite` verificável é sobre **traços estáveis**, não
sobre identidade: "mesmo tom de pele, mesmo comprimento e cor de cabelo, mesma roupa das
folhas de referência". Você consegue conferir isso abrindo os dois arquivos lado a lado.
