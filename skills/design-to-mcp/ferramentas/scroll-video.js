/**
 * scroll-video.js — vincula o currentTime de um <video> a posicao de rolagem.
 *
 * Uso no HTML:
 *   <video class="scroll-driven" src="public/assets/hero.mp4"
 *          poster="public/assets/hero-poster.jpg" muted playsinline preload="auto"></video>
 *
 * Atributos opcionais:
 *   data-scroll-start="0.0"   fracao da viewport em que o scrub comeca (0 = topo)
 *   data-scroll-end="1.0"     fracao da viewport em que o scrub termina
 *   data-smooth="0.12"        suavizacao 0..1 (menor = mais suave; 1 = sem suavizacao)
 *
 * Detalhes que importam:
 *   - o scrub roda em requestAnimationFrame, nao no evento de scroll (evita jank);
 *   - espera loadedmetadata, pois video.duration e NaN antes disso;
 *   - IntersectionObserver desliga o loop quando o video sai da tela;
 *   - respeita prefers-reduced-motion: o video congela no poster/primeiro frame.
 */
(function () {
  "use strict";

  var SEM_MOVIMENTO = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function limitar(v, min, max) {
    return v < min ? min : v > max ? max : v;
  }

  function Scrubber(video) {
    this.video = video;
    this.inicio = parseFloat(video.dataset.scrollStart);
    this.fim = parseFloat(video.dataset.scrollEnd);
    this.suavizacao = parseFloat(video.dataset.smooth);
    if (isNaN(this.inicio)) this.inicio = 0;
    if (isNaN(this.fim)) this.fim = 1;
    if (isNaN(this.suavizacao)) this.suavizacao = 0.12;

    this.tempoAtual = 0;
    this.visivel = false;
    this.rodando = false;
    this.pronto = false;

    video.muted = true;
    video.playsInline = true;
    video.pause();

    var self = this;
    if (video.readyState >= 1) {
      this.pronto = true;
    } else {
      video.addEventListener("loadedmetadata", function () {
        self.pronto = true;
        self.agendar();
      }, { once: true });
    }

    new IntersectionObserver(function (entradas) {
      self.visivel = entradas[0].isIntersecting;
      if (self.visivel) self.agendar();
    }, { rootMargin: "20% 0px" }).observe(video);
  }

  /** Progresso 0..1 do elemento atravessando a viewport. */
  Scrubber.prototype.progresso = function () {
    var r = this.video.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var percorrido = vh - r.top;
    var total = vh + r.height;
    var bruto = total > 0 ? percorrido / total : 0;
    var faixa = this.fim - this.inicio;
    return limitar(faixa > 0 ? (bruto - this.inicio) / faixa : bruto, 0, 1);
  };

  Scrubber.prototype.agendar = function () {
    if (this.rodando || !this.visivel || !this.pronto) return;
    this.rodando = true;
    var self = this;
    requestAnimationFrame(function () {
      self.rodando = false;
      self.aplicar();
    });
  };

  Scrubber.prototype.aplicar = function () {
    var duracao = this.video.duration;
    if (!duracao || !isFinite(duracao)) return;

    var alvo = this.progresso() * duracao;
    this.tempoAtual += (alvo - this.tempoAtual) * this.suavizacao;

    // Snap no fim da interpolacao para nao ficar oscilando em fracoes de frame.
    if (Math.abs(alvo - this.tempoAtual) < 0.01) this.tempoAtual = alvo;

    if (this.video.seeking === false) {
      this.video.currentTime = limitar(this.tempoAtual, 0, duracao - 0.001);
    }

    // Continua o loop enquanto ainda houver distancia a percorrer.
    if (this.visivel && this.tempoAtual !== alvo) this.agendar();
  };

  function iniciar() {
    var videos = document.querySelectorAll("video.scroll-driven");
    if (!videos.length || SEM_MOVIMENTO) return;

    var scrubbers = Array.prototype.map.call(videos, function (v) {
      return new Scrubber(v);
    });

    function atualizarTodos() {
      for (var i = 0; i < scrubbers.length; i++) scrubbers[i].agendar();
    }

    window.addEventListener("scroll", atualizarTodos, { passive: true });
    window.addEventListener("resize", atualizarTodos, { passive: true });
    atualizarTodos();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
