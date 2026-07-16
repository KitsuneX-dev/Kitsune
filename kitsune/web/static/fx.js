/* ==========================================================================
   Kitsune Web UI — ambient FX layer
   Плавающие "духи-огоньки" (kitsune-bi) на canvas: тёплые лисьи угольки и
   холодные фиолетовые искры, мягко поднимающиеся вверх.
   Не влияет на логику страницы, чисто декоративный слой.
   ========================================================================== */
(function () {
  'use strict';

  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var canvas = document.getElementById('fx');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'fx';
    document.body.appendChild(canvas);
  }
  var ctx = canvas.getContext('2d');
  var W = 0, H = 0, DPR = Math.min(window.devicePixelRatio || 1, 2);
  var particles = [];
  var COLORS = [
    { r: 255, g: 110, b: 60 },   // fox ember
    { r: 255, g: 150, b: 90 },   // warm spark
    { r: 190, g: 80, b: 255 },   // violet spirit
    { r: 216, g: 140, b: 255 },  // light violet
  ];

  function resize() {
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function count() {
    var base = Math.round((W * H) / 26000);
    return Math.max(14, Math.min(46, base));
  }

  function spawn(initial) {
    var c = COLORS[(Math.random() * COLORS.length) | 0];
    return {
      x: Math.random() * W,
      y: initial ? Math.random() * H : H + 12,
      r: 0.8 + Math.random() * 2.2,
      vy: 0.12 + Math.random() * 0.4,
      vx: (Math.random() - 0.5) * 0.16,
      sway: Math.random() * Math.PI * 2,
      swaySpeed: 0.004 + Math.random() * 0.012,
      swayAmp: 0.2 + Math.random() * 0.5,
      alpha: 0.25 + Math.random() * 0.5,
      tw: Math.random() * Math.PI * 2,
      twSpeed: 0.01 + Math.random() * 0.03,
      c: c,
    };
  }

  function reset() {
    particles = [];
    var n = count();
    for (var i = 0; i < n; i++) particles.push(spawn(true));
  }

  var last = 0;
  function tick(t) {
    var dt = Math.min(48, t - last) / 16.7;
    last = t;
    ctx.clearRect(0, 0, W, H);

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.sway += p.swaySpeed * dt;
      p.tw += p.twSpeed * dt;
      p.x += (p.vx + Math.sin(p.sway) * p.swayAmp * 0.4) * dt;
      p.y -= p.vy * dt;

      if (p.y < -14 || p.x < -14 || p.x > W + 14) {
        particles[i] = spawn(false);
        continue;
      }

      var a = p.alpha * (0.55 + 0.45 * Math.sin(p.tw));
      var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
      g.addColorStop(0, 'rgba(' + p.c.r + ',' + p.c.g + ',' + p.c.b + ',' + a.toFixed(3) + ')');
      g.addColorStop(1, 'rgba(' + p.c.r + ',' + p.c.g + ',' + p.c.b + ',0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(tick);
  }

  var rt;
  window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () { resize(); reset(); }, 150);
  });

  resize();
  reset();
  requestAnimationFrame(tick);
})();
