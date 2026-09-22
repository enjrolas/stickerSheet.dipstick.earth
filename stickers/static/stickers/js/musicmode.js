/* Animal disco.

   Toggled on, two things happen to every sticker:

     - its OUTLINE spins at ~20rpm (one turn every 3s). The picture inside
       does not move: the vinyl orbits the animal. That is why a sticker is
       built as separate outline and media layers rather than one flat PNG.
     - a beat makes it swell and settle, driven by the microphone.

   The beat detector is deliberately simple. It watches energy in the low
   band (roughly kick-drum territory), keeps a running average, and calls a
   beat when the current frame jumps well above that average and enough time
   has passed since the last one. That is far less clever than a real onset
   detector and much harder to make behave badly — no training, no tuning per
   track, and it degrades into "pulses a bit too often" rather than silence.

   The mic needs a user gesture and explicit permission, so nothing is
   requested until the toggle is pressed. If permission is refused the spin
   still runs; only the beat is lost, and the page says so. */
(function () {
  'use strict';

  var button = document.querySelector('[data-music]');
  var layer = document.querySelector('[data-canvas]');
  if (!button || !layer) { return; }

  var on = false;
  var audio = null, analyser = null, stream = null, data = null;
  var frame = null;

  // Beat detection state.
  var average = 0;            // running mean of low-band energy
  var lastBeat = 0;
  var MIN_GAP = 260;          // ms; ~230bpm ceiling, stops double-triggering
  var THRESHOLD = 1.45;       // how far above average counts as a beat

  // Pulse state, decayed every frame rather than by CSS transition so a beat
  // arriving mid-decay just restarts it instead of queueing.
  var pulse = 1;

  function stickers() {
    return layer.querySelectorAll('.sk__stuck');
  }

  function applyPulse() {
    var value = pulse.toFixed(3);
    Array.prototype.forEach.call(stickers(), function (el) {
      el.style.setProperty('--pulse', value);
    });
  }

  function lowBandEnergy() {
    analyser.getByteFrequencyData(data);
    // The first ~8% of the bins is roughly up to 900Hz at 44.1kHz — kick and
    // bass, which is what people actually hear as the beat.
    var bins = Math.max(4, Math.floor(data.length * 0.08));
    var sum = 0;
    for (var i = 0; i < bins; i++) { sum += data[i]; }
    return sum / bins / 255;
  }

  function tick() {
    frame = requestAnimationFrame(tick);

    if (analyser) {
      var energy = lowBandEnergy();
      // Seed the average on the first frames so the opening beat is not
      // swallowed by an average of zero.
      average = average ? average * 0.92 + energy * 0.08 : energy;

      var now = performance.now();
      if (energy > average * THRESHOLD && energy > 0.04
          && now - lastBeat > MIN_GAP) {
        lastBeat = now;
        // Louder beats hit harder, within reason.
        pulse = Math.min(1.35, 1 + Math.min(energy, 0.6) * 0.45);
      }
    }

    // Settle back towards rest.
    pulse += (1 - pulse) * 0.12;
    if (Math.abs(pulse - 1) < 0.002) { pulse = 1; }
    applyPulse();
  }

  function say(message) {
    var hint = document.querySelector('[data-music-note]');
    if (hint) { hint.textContent = message || ''; }
  }

  async function listen() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {echoCancellation: false, noiseSuppression: false,
                autoGainControl: false}
      });
    } catch (err) {
      // Refused, or no mic. The spin is the bigger half of the effect and
      // costs nothing, so keep it and say what is missing.
      say('No microphone, so the stickers spin but will not follow a beat.');
      return false;
    }
    var Ctx = window.AudioContext || window.webkitAudioContext;
    audio = new Ctx();
    if (audio.state === 'suspended') { await audio.resume(); }
    analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.6;
    audio.createMediaStreamSource(stream).connect(analyser);
    data = new Uint8Array(analyser.frequencyBinCount);
    say('Listening. Play something.');
    return true;
  }

  function stop() {
    if (frame) { cancelAnimationFrame(frame); frame = null; }
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    if (audio) { audio.close().catch(function () {}); audio = null; }
    analyser = null; data = null; average = 0; pulse = 1;
    applyPulse();
    Array.prototype.forEach.call(stickers(), function (el) {
      el.style.removeProperty('--pulse');
    });
    say('');
  }

  button.addEventListener('click', async function () {
    on = !on;
    button.setAttribute('aria-pressed', String(on));
    button.classList.toggle('is-on', on);
    document.body.classList.toggle('sk-music', on);

    if (on) {
      await listen();          // spin runs either way
      tick();
    } else {
      stop();
    }
  });

  // Stickers placed while music mode is running need the current pulse, and
  // the spin comes from the body class so it applies on its own.
  layer.addEventListener('DOMNodeInserted', function () {
    if (on) { applyPulse(); }
  });
})();
