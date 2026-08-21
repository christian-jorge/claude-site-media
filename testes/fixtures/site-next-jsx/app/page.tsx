import Image from "next/image"
import hero from "../assets/hero-cozinha.jpg"

export default function Home() {
  return (
    <main>
      <section className="hero">
        <h1>Marmita de comida de verdade</h1>
        <p>Cozinhamos de madrugada e entregamos antes das onze.</p>
        <Image src={hero} width={1440} height={720} alt="cozinha em operacao" priority />
      </section>

      <section className="grade">
        <h2>Como funciona</h2>
        <p>Voce escolhe na segunda, a gente entrega na quarta.</p>
        <img src="/img/etapa-escolha.jpg" width={480} height={320} alt="tela de escolha" />
        <h3>Entrega refrigerada</h3>
        <p>Caixa termica que aguenta seis horas fora da geladeira.</p>
        <img src="/img/etapa-entrega.jpg" width={480} height={320} alt="caixa termica" />
      </section>
    </main>
  )
}
