/* The sticker sheet playground.

   Drag an animal off the tray onto the canvas, then:
     drag            move it
     shift + drag    rotate it about its own centre
     hold S + wheel  resize it
     click           select it, for the panel and the keyboard
     delete / backspace  remove the selected one

   Everything is pointer events, so it works with a mouse, a trackpad and a
   finger without three code paths. The arrangement is kept in localStorage —
   it is one person messing about, not content, so it never goes to the
   server. */
(function () {
  'use strict';

  var canvas = document.querySelector('[data-canvas]');
  if (!canvas) { return; }

  var tray = document.querySelector('[data-tray]');
  var panel = document.querySelector('[data-panel]');
  var panelName = document.querySelector('[data-panel-name]');
  var rotInput = document.querySelector('[data-rot]');
  var scaleInput = document.querySelector('[data-scale]');

  var STORE = 'dipstick-sticker-sheet-v1';
  var items = [];          // {el, src, name, x, y, rot, size, flip, z}
  var selected = null;
  var topZ = 1;

  /* ---- persistence ----------------------------------------------------
     Wrapped because storage throws in a private window and comes back empty
     with site data cleared; the page has to work either way. */
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify(items.map(function (it) {
        return {src: it.src, name: it.name, kind: it.kind,
                media: it.media, poster: it.poster,
                outline: it.outline, ring: it.ring,
                mask: it.mask, crop: it.crop,
                x: it.x, y: it.y,
                rot: it.rot, size: it.size, flip: it.flip, z: it.z};
      })));
    } catch (e) { /* not worth bothering anyone about */ }
  }

  function restore() {
    var raw = null;
    try { raw = localStorage.getItem(STORE); } catch (e) { return; }
    if (!raw) { return; }
    try {
      JSON.parse(raw).forEach(function (d) {
        place(d.src, d.name, d.x, d.y, d);
      });
    } catch (e) { /* corrupt: start empty rather than half-broken */ }
  }

  /* ---- placing --------------------------------------------------------- */
  /* A still sticker is its die-cut PNG and nothing else. A moving one is
     rebuilt from its parts — outline art behind, media clipped to the inset
     mask, placed by the stored framing — because a PNG cannot move. The mask
     goes on the clip, never on the media: mask-size is relative to the
     element it sits on, and the media is sized to its crop box. */
  /* Every sticker is three layers, whatever kind it is:

       outline  the vinyl body and ink keyline
       clip     the sticker square, masked to the inset silhouette
       media    the picture, sized to its crop box

     A still could have been the flat die-cut PNG, and was — but music mode
     spins the outline while the picture holds still, so the two have to be
     separate elements. The mask stays on the clip and never on the media:
     mask-size is relative to whatever element it is on, and the media is
     deliberately larger than the square. */
  function build(d) {
    var wrap = document.createElement('div');
    wrap.className = 'sk__stuck';

    // Backing: the vinyl body, behind everything, so the sticker is opaque
    // where the picture does not reach.
    var backing = document.createElement('div');
    backing.className = 'sk__stuck-backing';
    if (d.outline) { backing.style.backgroundImage = "url('" + d.outline + "')"; }

    // The border, with its middle punched out, ON TOP of the picture. Once
    // the die-cut window turns, a picture in front of the vinyl can swing
    // past the orbiting edge and escape the sticker; behind the ring it is
    // always framed.
    var ring = document.createElement('div');
    ring.className = 'sk__stuck-ring';
    if (d.ring) { ring.style.backgroundImage = "url('" + d.ring + "')"; }

    var clip = document.createElement('div');
    clip.className = 'sk__stuck-clip';
    if (d.mask) {
      clip.style.webkitMaskImage = "url('" + d.mask + "')";
      clip.style.maskImage = "url('" + d.mask + "')";
    }

    var media;
    if (d.kind === 'video') {
      media = document.createElement('video');
      media.muted = true; media.loop = true; media.playsInline = true;
      media.autoplay = true; media.preload = 'auto';
      if (d.poster) { media.poster = d.poster; }
      media.src = d.media;
      // play() is called after the element is in the document, not here —
      // a video that is not yet in the DOM will not start, and the sticker
      // would sit on its poster.
    } else {
      media = document.createElement('img');
      media.src = d.media || d.src;      // GIFs keep the original, so they move
      media.alt = d.name || '';
    }
    media.className = 'sk__stuck-media';
    media.draggable = false;

    if (d.crop) {
      // The units matter. data-crop carries bare numbers, and CSS silently
      // drops a unitless length — which left the media falling back to the
      // stylesheet's 100%/100% and squashed into the square, i.e. the wrong
      // aspect ratio.
      var c = String(d.crop).split(',');
      if (c.length === 4) {
        media.style.width = c[0] + '%';
        media.style.height = c[1] + '%';
        media.style.left = c[2] + '%';
        media.style.top = c[3] + '%';
      }
    }

    /* The media sits inside a wrapper that is exactly the clip square, so
       that in animal disco the clip (carrying the mask) can rotate while this
       counter-rotates by the same amount — the die-cut window spins, the
       picture inside stays upright. Both boxes are the same square with the
       same centre, so the cancellation is exact; counter-rotating the media
       directly would not work, because its own centre is offset from the
       square's by the crop. */
    var spin = document.createElement('div');
    spin.className = 'sk__stuck-spin';
    spin.appendChild(media);
    clip.appendChild(spin);
    wrap.appendChild(backing);   // vinyl behind
    wrap.appendChild(clip);      // the picture
    wrap.appendChild(ring);      // vinyl border over the top
    return wrap;
  }

  function place(src, name, x, y, opts) {
    opts = opts || {};
    var el = build({
      src: src, name: name, kind: opts.kind || 'still',
      media: opts.media, poster: opts.poster,
      outline: opts.outline, ring: opts.ring,
      mask: opts.mask, crop: opts.crop
    });

    var it = {
      el: el, src: src, name: name || '',
      kind: opts.kind || 'still',
      media: opts.media, poster: opts.poster,
      outline: opts.outline, ring: opts.ring,
      mask: opts.mask, crop: opts.crop,
      x: x, y: y,
      rot: opts.rot || 0,
      size: opts.size || 140,
      flip: !!opts.flip,
      z: opts.z || ++topZ
    };
    if (it.z > topZ) { topZ = it.z; }

    el.addEventListener('pointerdown', onGrab);
    canvas.appendChild(el);
    items.push(it);
    draw(it);

    // Now that it is in the document, get it moving. Autoplay can still be
    // refused (battery saver, reduced data); the poster then stands in,
    // which is a perfectly good sticker.
    var video = el.querySelector && el.querySelector('video');
    if (video) {
      var playing = video.play();
      if (playing && playing.catch) { playing.catch(function () {}); }
    }
    return it;
  }

  function draw(it) {
    var el = it.el;
    el.style.width = it.size + 'px';
    el.style.height = it.size + 'px';
    el.style.left = it.x + 'px';
    el.style.top = it.y + 'px';
    el.style.zIndex = it.z;
    // `--pulse` is the beat. It multiplies whatever rotation and flip the
    // sticker already has, so a beat never disturbs how it was arranged.
    el.style.transform = 'translate(-50%, -50%) rotate(' + it.rot + 'deg)'
                       + ' scaleX(' + (it.flip ? -1 : 1) + ')'
                       + ' scale(var(--pulse, 1))';
  }

  function find(el) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].el === el) { return items[i]; }
    }
    return null;
  }

  /* ---- selection ------------------------------------------------------- */
  function select(it) {
    if (selected) { selected.el.classList.remove('is-picked'); }
    selected = it;
    if (!it) {
      panel.hidden = true;
      return;
    }
    it.el.classList.add('is-picked');
    panelName.textContent = it.name || 'sticker';
    rotInput.value = it.rot;
    scaleInput.value = it.size;
    panel.hidden = false;
  }

  function remove(it) {
    if (!it) { return; }
    it.el.remove();
    items = items.filter(function (o) { return o !== it; });
    if (selected === it) { select(null); }
    save();
  }

  /* ---- dragging, rotating ---------------------------------------------- */
  var drag = null;
  var peeled = false;   // a pointer peel just happened; skip the click

  /* Document coordinates, not viewport ones. A sticker is stuck to the PAGE,
     so it has to stay put when you scroll — and the layer starts at the top
     of the document, so pageX/pageY map straight onto it. */
  function canvasPoint(e) {
    var box = canvas.getBoundingClientRect();
    return {
      x: e.pageX - (box.left + window.scrollX),
      y: e.pageY - (box.top + window.scrollY)
    };
  }

  function onGrab(e) {
    var it = find(e.currentTarget);
    if (!it) { return; }
    e.preventDefault();
    select(it);
    it.z = ++topZ;
    draw(it);

    // Remember every finger on this sticker, so a second one starts a pinch.
    it._pointers = it._pointers || {};
    it._pointers[e.pointerId] = canvasPoint(e);
    if (Object.keys(it._pointers).length >= 2) {
      onPinchStart(it);
      return;
    }

    var p = canvasPoint(e);
    drag = {
      it: it,
      mode: e.shiftKey ? 'rotate' : 'move',
      dx: p.x - it.x,
      dy: p.y - it.y,
      startRot: it.rot,
      startAngle: Math.atan2(p.y - it.y, p.x - it.x) * 180 / Math.PI
    };
    it.el.setPointerCapture(e.pointerId);
    it.el.classList.add('is-held');
  }

  function onMove(e) {
    if (pinch && pinch.it._pointers[e.pointerId]) {
      pinch.it._pointers[e.pointerId] = canvasPoint(e);
      onPinchMove();
      return;
    }
    if (!drag) { return; }
    var p = canvasPoint(e);
    // Shift is read live, so you can start moving and rotate mid-drag.
    var mode = e.shiftKey ? 'rotate' : drag.mode;

    if (mode === 'rotate') {
      var angle = Math.atan2(p.y - drag.it.y, p.x - drag.it.x) * 180 / Math.PI;
      drag.it.rot = Math.round(drag.startRot + (angle - drag.startAngle));
      if (selected === drag.it) { rotInput.value = drag.it.rot; }
    } else {
      drag.it.x = Math.round(p.x - drag.dx);
      drag.it.y = Math.round(p.y - drag.dy);
    }
    draw(drag.it);
  }

  function onDrop(e) {
    if (pinch) {
      delete pinch.it._pointers[e.pointerId];
      if (Object.keys(pinch.it._pointers).length < 2) { pinch = null; save(); }
      return;
    }
    if (!drag) { return; }
    delete drag.it._pointers[e.pointerId];
    drag.it.el.classList.remove('is-held');
    try { drag.it.el.releasePointerCapture(e.pointerId); } catch (err) {}
    drag = null;
    save();
  }

  document.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onDrop);
  window.addEventListener('pointercancel', onDrop);

  /* ---- from the tray onto the canvas ----------------------------------- */
  function parts(peel) {
    return {
      src: peel.dataset.src, name: peel.dataset.name,
      kind: peel.dataset.kind || 'still',
      media: peel.dataset.media, poster: peel.dataset.poster,
      outline: peel.dataset.outline, ring: peel.dataset.ring,
      mask: peel.dataset.mask, crop: peel.dataset.crop
    };
  }

  Array.prototype.forEach.call(tray.querySelectorAll('.sk__peel'), function (peel) {
    /* Pointer events, not HTML5 drag-and-drop. dragstart/drop never fire on
       a touchscreen, so on a phone the tray was simply dead. Peeling by
       pointerdown works identically for mouse, trackpad and finger, and it
       reads better anyway: the sticker comes off under your finger rather
       than after a drag-image dance.

       dragstart is still wired for desktop, but only as a fallback for the
       case where a pointer never arrives. */
    peel.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0) { return; }
      e.preventDefault();
      var d = parts(peel);
      var p = canvasPoint(e);
      var it = place(d.src, d.name, Math.round(p.x), Math.round(p.y), d);
      select(it);
      peeled = true;

      // Hand the drag straight to the new sticker, so it follows the finger
      // out of the tray in one gesture.
      drag = {
        it: it, mode: 'move', dx: 0, dy: 0,
        startRot: it.rot, startAngle: 0
      };
      try { it.el.setPointerCapture(e.pointerId); } catch (err) {}
      it.el.classList.add('is-held');
      save();
    });

    peel.addEventListener('dragstart', function (e) {
      e.dataTransfer.setData('text/plain', JSON.stringify(parts(peel)));
      e.dataTransfer.effectAllowed = 'copy';
    });
    // Clicking also places one, in the middle — dragging is not the only way
    // in, and it is the only way that works from a keyboard.
    peel.addEventListener('click', function () {
      // A pointer already placed one; this is the keyboard path only.
      if (peeled) { peeled = false; return; }
      var box = canvas.getBoundingClientRect();
      var d = parts(peel);
      // Centre of the current view, converted to document coordinates —
      // otherwise a click after scrolling drops the sticker off-screen.
      select(place(d.src, d.name,
                   Math.round(window.innerWidth / 2 - box.left),
                   Math.round(window.innerHeight / 2 - box.top), d));
      save();
    });
  });

  // The layer takes no pointer events, so the document is what sees a drag
  // crossing the page. Dropping anywhere — over the text, the navbar, the
  // margin — is the entire point.
  document.addEventListener('dragover', function (e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    canvas.classList.add('is-target');
  });
  document.addEventListener('dragleave', function () {
    canvas.classList.remove('is-target');
  });
  document.addEventListener('drop', function (e) {
    e.preventDefault();
    canvas.classList.remove('is-target');
    var payload;
    try { payload = JSON.parse(e.dataTransfer.getData('text/plain')); }
    catch (err) { return; }
    if (!payload || !payload.src) { return; }
    var p = canvasPoint(e);
    select(place(payload.src, payload.name,
                 Math.round(p.x), Math.round(p.y), payload));
    save();
  });

  /* ---- keyboard --------------------------------------------------------- */
  window.addEventListener('keydown', function (e) {
    // Don't hijack typing.
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea') { return; }

    if (!selected) { return; }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      remove(selected);
    } else if (e.key === 'Escape') {
      select(null);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight'
            || e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      var step = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowLeft') { selected.x -= step; }
      if (e.key === 'ArrowRight') { selected.x += step; }
      if (e.key === 'ArrowUp') { selected.y -= step; }
      if (e.key === 'ArrowDown') { selected.y += step; }
      draw(selected);
      save();
    }
  });

  /* ---- two fingers scale and rotate ---------------------------------------
     On a phone there is no shift key and no wheel, so pinch is the only way
     to resize or turn a sticker. Tracked per-sticker rather than globally,
     so two people (or two hands) cannot fight over one gesture. */
  var pinch = null;

  function pinchPointers(it) {
    var ids = Object.keys(it._pointers || {});
    return ids.length >= 2 ? ids.slice(0, 2) : null;
  }

  function onPinchStart(it) {
    var ids = pinchPointers(it);
    if (!ids) { return; }
    var a = it._pointers[ids[0]], b = it._pointers[ids[1]];
    pinch = {
      it: it,
      dist: Math.hypot(b.x - a.x, b.y - a.y),
      angle: Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI,
      size: it.size,
      rot: it.rot
    };
    drag = null;              // a pinch is not a drag
  }

  function onPinchMove() {
    if (!pinch) { return; }
    var it = pinch.it;
    var ids = pinchPointers(it);
    if (!ids) { return; }
    var a = it._pointers[ids[0]], b = it._pointers[ids[1]];
    var dist = Math.hypot(b.x - a.x, b.y - a.y);
    var angle = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
    if (pinch.dist > 4) {
      it.size = Math.max(30, Math.min(400,
        Math.round(pinch.size * (dist / pinch.dist))));
    }
    it.rot = Math.round(pinch.rot + (angle - pinch.angle));
    if (selected === it) {
      scaleInput.value = it.size;
      rotInput.value = it.rot;
    }
    draw(it);
  }

  /* ---- shift + wheel resizes ---------------------------------------------
     Shift is already the modifier for rotating mid-drag, and a scroll is a
     different gesture from a drag, so the two cannot collide. It also means
     there is no held key to lose track of when the window loses focus —
     which the previous 'S' version could, leaving resize stuck on. */
  document.addEventListener('wheel', function (e) {
    if (!e.shiftKey) { return; }          // plain scrolling still scrolls
    var it = find(e.target) || selected;
    if (!it) { return; }
    e.preventDefault();
    it.size = Math.max(30, Math.min(400, it.size - Math.sign(e.deltaY) * 8));
    if (selected !== it) { select(it); }
    scaleInput.value = it.size;
    draw(it);
    save();
  }, {passive: false});

  // Clicking anything that is not a sticker deselects — including ordinary
  // page content, which still behaves normally underneath.
  document.addEventListener('pointerdown', function (e) {
    if (!e.target.closest || !e.target.closest('.sk__stuck, .sk__panel, .sk__tray')) {
      select(null);
    }
  });

  /* ---- the panel -------------------------------------------------------- */
  rotInput.addEventListener('input', function () {
    if (!selected) { return; }
    selected.rot = parseInt(rotInput.value, 10) || 0;
    draw(selected); save();
  });
  scaleInput.addEventListener('input', function () {
    if (!selected) { return; }
    selected.size = parseInt(scaleInput.value, 10) || 140;
    draw(selected); save();
  });
  document.querySelector('[data-front]').addEventListener('click', function () {
    if (!selected) { return; }
    selected.z = ++topZ; draw(selected); save();
  });
  document.querySelector('[data-flip]').addEventListener('click', function () {
    if (!selected) { return; }
    selected.flip = !selected.flip; draw(selected); save();
  });
  document.querySelector('[data-remove]').addEventListener('click', function () {
    remove(selected);
  });
  document.querySelector('[data-clear]').addEventListener('click', function () {
    items.slice().forEach(remove);
  });

  restore();
})();
