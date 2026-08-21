/**
 * scroll-video.js — vincula o currentTime de um <video> a posicao de rolagem.
 *
 * Uso no HTML:
 *   <video class="scroll-driven" src="/assets/hero.mp4"
 *          poster="/assets/hero-poster.jpg" muted playsinline preload="auto"></video>
 *
 * Atributos opcionais:
 *   data-scroll-start="0.0"    fracao do percurso em que o scrub comeca
 *   data-scroll-start="auto"   calcula sozinho para video que ja nasce visivel (hero no topo)
 *   data-scroll-end="1.0"      fracao do percurso em que o scrub termina
 *   data-smooth="0.12"         suavizacao em (0,1]; 1 = sem suavizacao
 *
 * Detalhes que importam:
 *   - o scrub roda em requestAnimationFrame, nao no evento de scroll (evita jank);
 *   - espera loadedmetadata, pois video.duration e NaN antes disso;
 *   - IntersectionObserver desliga o loop quando o video sai da tela;
 *   - respeita prefers-reduced-motion: o video congela no poster/primeiro frame,
 *     mas continua mudo, inline e pausado -- e volta a animar se a preferencia mudar.
 */
(function () {
  "use strict";

  var CONSULTA_MOVIMENTO = window.matchMedia("(prefers-reduced-motion: reduce)");
  var reduzido = CONSULTA_MOVIMENTO.matches;
  // abaixo disto o navegador nem repinta o frame: escrever de novo so gera seek
  var TOLERANCIA = 0.005;

  function limitar(v, min, max) {
    return v < min ? min : v > max ? max : v;
  }

  function avisar(video, msg) {
    if (window.console && console.warn) {
      console.warn("scroll-video: " +
        (video.id || video.currentSrc || video.src || "<video>") + ": " + msg);
    }
  }

  function preparar(video) {
    video.muted = true;
    video.playsInline = true;
    video.pause();
  }

  function Scrubber(video) {
    this.video = video;
    // "auto" resolve o hero no topo da pagina: ele ja nasce com parte do percurso
    // gasta, e sem isto o clipe termina antes da primeira tela
    this.inicioAuto = video.dataset.scrollStart === "auto";
    this.inicio = parseFloat(video.dataset.scrollStart);
    this.fim = parseFloat(video.dataset.scrollEnd);
    this.suavizacao = parseFloat(video.dataset.smooth);
    if (isNaN(this.inicio)) this.inicio = 0;
    if (isNaN(this.fim)) this.fim = 1;
    if (isNaN(this.suavizacao)) this.suavizacao = 0.12;

    if (!(this.suavizacao > 0) || this.suavizacao > 1) {
      // data-smooth="0" era sugerido pela propria doc e travava o rAF para sempre
      avisar(video, 'data-smooth="' + video.dataset.smooth + '" fora de (0,1]; usando 0.12');
      this.suavizacao = 0.12;
    }
    if (!this.inicioAuto && !(this.fim > this.inicio)) {
      avisar(video, "data-scroll-start (" + this.inicio + ") >= data-scroll-end (" +
        this.fim + "); usando 0..1");
      this.inicio = 0;
      this.fim = 1;
    }

    this.tempoAtual = 0;
    this.escrito = undefined;
    this.visivel = false;
    this.rodando = false;
    this.pronto = false;

    var self = this;
    if (video.readyState >= 1) {
      this.pronto = true;
    } else {
      video.addEventListener("loadedmetadata", function () {
        self.pronto = true;
        self.agendar();
      }, { once: true });
    }
    // sem isto o loop morria durante um seek e so voltava no proximo scroll
    video.addEventListener("seeked", function () { self.agendar(); });

    new IntersectionObserver(function (entradas) {
      // a ULTIMA entrada e o estado atual; a primeira e a mais velha do lote
      self.visivel = entradas[entradas.length - 1].isIntersecting;
      if (self.visivel) self.agendar();
    }, { rootMargin: "20% 0px" }).observe(video);
  }

  /** Progresso 0..1 do elemento atravessando a viewport. */
  Scrubber.prototype.progresso = function () {
    var r = this.video.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    // altura 0 no instante do loadedmetadata devolvia 100%: o hero abria no ULTIMO frame
    if (!r.height || !vh) return 0;
    var bruto = (vh - r.top) / (vh + r.height);
    var inicio = this.inicioAuto ? vh / (vh + r.height) : this.inicio;
    if (!(this.fim > inicio)) return limitar(bruto, 0, 1);
    return limitar((bruto - inicio) / (this.fim - inicio), 0, 1);
  };

  Scrubber.prototype.agendar = function () {
    if (reduzido || this.rodando || !this.visivel || !this.pronto) return;
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
    if (this.video.seeking) return;   // seek em curso: o 'seeked' reagenda

    var alvo = this.progresso() * duracao;
    this.tempoAtual += (alvo - this.tempoAtual) * this.suavizacao;
    // snap no fim da interpolacao para nao ficar oscilando em fracoes de frame
    if (Math.abs(alvo - this.tempoAtual) < 0.01) this.tempoAtual = alvo;

    var novo = limitar(this.tempoAtual, 0, duracao - 0.001);
    if (this.escrito === undefined || Math.abs(this.escrito - novo) > TOLERANCIA) {
      this.escrito = novo;
      this.video.currentTime = novo;
    }
    // continua enquanto houver distancia REAL a percorrer; comparar floats por
    // igualdade deixava o loop vivo indefinidamente
    if (this.visivel && Math.abs(alvo - this.tempoAtual) > TOLERANCIA) this.agendar();
  };

  function iniciar() {
    var videos = document.querySelectorAll("video.scroll-driven");
    if (!videos.length) return;

    // muted/playsInline/pause valem SEMPRE: sem eles, o iOS abre em fullscreen e
    // o Chrome bloqueia -- inclusive sob prefers-reduced-motion
    Array.prototype.forEach.call(videos, preparar);

    var scrubbers = Array.prototype.map.call(videos, function (v) {
      return new Scrubber(v);
    });

    function atualizarTodos() {
      for (var i = 0; i < scrubbers.length; i++) scrubbers[i].agendar();
    }

    window.addEventListener("scroll", atualizarTodos, { passive: true });
    window.addEventListener("resize", atualizarTodos, { passive: true });

    // o layout tambem muda sem scroll e sem resize: fonte que carrega, imagem que
    // chega, acordeao que abre acima do video
    if (typeof ResizeObserver === "function") {
      var ro = new ResizeObserver(atualizarTodos);
      ro.observe(document.documentElement);
      for (var j = 0; j < videos.length; j++) ro.observe(videos[j]);
    }

    if (CONSULTA_MOVIMENTO.addEventListener) {
      CONSULTA_MOVIMENTO.addEventListener("change", function (e) {
        reduzido = e.matches;
        if (!reduzido) atualizarTodos();
      });
    }

    atualizarTodos();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
