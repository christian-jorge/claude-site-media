<template>
  <figure class="cartao">
    <h3>Plano Semestral</h3>
    <p>Seis meses de acompanhamento com avaliacao a cada trinta dias.</p>
    <img :src="foto" alt="aluna treinando" />
    <NuxtImg src="/img/selo-semestral.png" width="240" height="240" alt="selo" />
  </figure>
</template>

<script setup>
const foto = "/img/aluna-treino.jpg"
</script>

<style scoped>
.cartao img { width: 360px; height: 240px; }
</style>
