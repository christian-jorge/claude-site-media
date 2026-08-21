<script>
  export let src = "/img/faixa-academia.jpg";
</script>

<section class="faixa">
  <h2>Primeira aula sem custo</h2>
  <p>Traga roupa de treino e uma garrafa d'agua.</p>
  <img {src} alt="sala de treino" />
  <img bind:src alt="mesma sala, outro angulo" srcset="/img/faixa-2x.jpg 2x" />
</section>
