/* The "add yours" framing editor.

   Two jobs:
     1. pick a die-cut outline from the ten, visually
     2. drag the media around under that outline, and zoom, to choose what
        the sticker actually shows

   The crop maths here is a deliberate duplicate of imaging.focal_crop() in
   Python. Both turn (focal_x, focal_y, zoom) into the same square of the
   source, so what someone frames here is what the server cuts. If you change
   the rule in one place, change it in the other.

   Degrades safely: with no JS the form still submits, the hidden inputs keep
   their defaults (centred, zoom 1) and the shape falls back to auto. */
(function () {
  'use strict';

  var root = document.querySelector('[data-framer]');
  if (!root) { return; }

  // /submit/ frames a file being chosen; /review/<slug>/ frames a sticker
  // that already exists and has no file input at all.
  var fileInput = document.getElementById('id_media');
  var existingUrl = root.getAttribute('data-existing-url');
  var existingKind = root.getAttribute('data-existing-kind') || 'image';
  var existingPoster = root.getAttribute('data-existing-poster') || '';
  var stage = root.querySelector('[data-stage]');
  var clip = root.querySelector('[data-clip]');
  var media = null;                       // the <img>/<video> being framed
  var zoomInput = root.querySelector('[data-zoom]');
  var hint = root.querySelector('[data-hint]');
  var empty = root.querySelector('[data-empty]');

  /* These four are the FORM's state, not the framer widget's, and submit.html
     renders them at the top of the <form> -- outside [data-framer]. Scoping the
     lookup to root returned null for all four, and the first `.value` read below
     threw, which killed the whole IIFE: no shape-button handlers, no file
     preview. Scope them to the owning form so it holds wherever in the form the
     template puts them. */
  var fields = root.closest('form') || document;
  var fx = fields.querySelector('input[name="focal_x"]');
  var fy = fields.querySelector('input[name="focal_y"]');
  var fz = fields.querySelector('input[name="zoom"]');
  var fshape = fields.querySelector('input[name="shape"]');

  /* This file already promises to degrade safely with no JS. Make it degrade
     safely with JS too: if a field is genuinely missing, leave the server to
     centre the crop and pick a shape rather than throwing. */
  if (!fx || !fy || !fz || !fshape) { return; }

  var state = {
    focalX: parseFloat(fx.value) || 0.5,
    focalY: parseFloat(fy.value) || 0.5,
    zoom: parseFloat(fz.value) || 1,
    natW: 0,
    natH: 0
  };

  /* ---- the shared crop rule (mirror of imaging.focal_crop) -------------
     Zoom 1 is the largest square that fits. Above 1 pushes in; BELOW 1 the
     square grows past the short side and the picture is padded, which is how
     you keep the edges of a landscape shot. Zooming out stops once the whole
     image is visible.

     Kept deliberately identical to focal_crop() in Python — change one,
     change the other, or the preview stops telling the truth. */
  var MIN_ZOOM = 0.2, MAX_ZOOM = 4;

  function fitZoom() {
    // The zoom at which the entire image is visible.
    if (!state.natW || !state.natH) { return 1; }
    return Math.min(state.natW, state.natH) / Math.max(state.natW, state.natH);
  }

  function cropBox() {
    var w = state.natW, h = state.natH;
    var zoom = Math.max(MIN_ZOOM, Math.min(state.zoom, MAX_ZOOM));
    var side = Math.min(Math.min(w, h) / zoom, Math.max(w, h));

    function place(focal, extent) {
      var start = focal * extent - side / 2;
      if (side <= extent) {
        return Math.max(0, Math.min(start, extent - side));
      }
      return (extent - side) / 2;   // wider than the image: centre it
    }
    return { left: place(state.focalX, w), top: place(state.focalY, h), side: side };
  }

  /* Lay the media out so exactly cropBox() fills the square stage. */
  function layout() {
    if (!media || !state.natW || !state.natH) { return; }
    var box = cropBox();
    var stageSize = stage.clientWidth;
    var scale = stageSize / box.side;
    media.style.width = (state.natW * scale) + 'px';
    media.style.height = (state.natH * scale) + 'px';
    media.style.left = (-box.left * scale) + 'px';
    media.style.top = (-box.top * scale) + 'px';

    // Fold the clamped values back into state, not just into the inputs.
    // Without this, dragging past an edge keeps pushing focal_* far outside
    // 0..1 and the next drag the other way does nothing until all that
    // invisible slack is wound back — which made the picture feel stuck,
    // especially vertically, where a landscape photo has little room to move.
    var w = state.natW, h = state.natH;
    state.focalX = (box.left + box.side / 2) / w;
    state.focalY = (box.top + box.side / 2) / h;

    fx.value = state.focalX.toFixed(4);
    fy.value = state.focalY.toFixed(4);
    fz.value = state.zoom.toFixed(3);

    // Tell the person which way this particular picture can actually move:
    // at zoom 1 a landscape photo has no vertical slack at all, because the
    // square is already exactly its height.
    var canX = box.side < w - 0.5, canY = box.side < h - 0.5;
    stage.style.cursor = (canX || canY) ? '' : 'default';
    if (hint) {
      if (!canX && !canY) {
        hint.textContent = 'Zoom in to move the picture around.';
      } else if (canX && !canY) {
        hint.textContent = 'Drag left and right. Zoom in to move up and down too.';
      } else if (canY && !canX) {
        hint.textContent = 'Drag up and down. Zoom in to move sideways too.';
      } else {
        hint.textContent = 'Drag to move it. Arrow keys nudge. Slider zooms.';
      }
    }
  }

  /* ---- dragging -------------------------------------------------------- */
  var dragging = false, lastX = 0, lastY = 0;

  function pointer(e) {
    var t = e.touches ? e.touches[0] : e;
    return { x: t.clientX, y: t.clientY };
  }

  function onDown(e) {
    if (!media) { return; }
    dragging = true;
    var p = pointer(e);
    lastX = p.x; lastY = p.y;
    stage.classList.add('is-dragging');
    if (e.cancelable) { e.preventDefault(); }
  }

  function onMove(e) {
    if (!dragging || !media) { return; }
    var p = pointer(e);
    var box = cropBox();
    // Convert the pixel drag back into source coordinates.
    var perPx = box.side / stage.clientWidth;
    state.focalX -= ((p.x - lastX) * perPx) / state.natW;
    state.focalY -= ((p.y - lastY) * perPx) / state.natH;
    lastX = p.x; lastY = p.y;
    layout();
    if (e.cancelable) { e.preventDefault(); }
  }

  function onUp() {
    dragging = false;
    stage.classList.remove('is-dragging');
  }

  stage.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  stage.addEventListener('touchstart', onDown, { passive: false });
  window.addEventListener('touchmove', onMove, { passive: false });
  window.addEventListener('touchend', onUp);

  // Keyboard nudging, so framing is not mouse-only.
  stage.addEventListener('keydown', function (e) {
    if (!media) { return; }
    var step = e.shiftKey ? 0.05 : 0.01;
    var moved = true;
    if (e.key === 'ArrowLeft') { state.focalX -= step; }
    else if (e.key === 'ArrowRight') { state.focalX += step; }
    else if (e.key === 'ArrowUp') { state.focalY -= step; }
    else if (e.key === 'ArrowDown') { state.focalY += step; }
    else { moved = false; }
    if (moved) { layout(); e.preventDefault(); }
  });

  zoomInput.addEventListener('input', function () {
    state.zoom = parseFloat(zoomInput.value) || 1;
    layout();
  });

  /* ---- shape picking --------------------------------------------------- */
  root.querySelectorAll('[data-shape]').forEach(function (button) {
    button.addEventListener('click', function () {
      root.querySelectorAll('[data-shape]').forEach(function (b) {
        b.classList.remove('is-on');
        b.setAttribute('aria-pressed', 'false');
      });
      button.classList.add('is-on');
      button.setAttribute('aria-pressed', 'true');
      var slug = button.getAttribute('data-shape');
      fshape.value = slug;
      applyShape(slug, button.getAttribute('data-mask'),
                 button.getAttribute('data-outline'));
    });
  });

  function applyShape(slug, maskUrl, outlineUrl) {
    // "Surprise me" posts an empty shape and lets the server choose, but the
    // preview still has to show a real sticker — an unmasked rectangle tells
    // you nothing about what you are making. Fall back to the first outline
    // and say so.
    if (!slug) {
      var first = root.querySelector('[data-shape]:not([data-shape=""])');
      if (!first) { return; }
      maskUrl = first.getAttribute('data-mask');
      outlineUrl = first.getAttribute('data-outline');
    }
    stage.style.setProperty('--shape-mask', "url('" + maskUrl + "')");
    stage.style.setProperty('--shape-outline', "url('" + outlineUrl + "')");
  }

  /* ---- loading the chosen file ---------------------------------------- */
  function clearMedia() {
    if (media) {
      if (media.dataset.revoke && media.src.indexOf('blob:') === 0) {
        URL.revokeObjectURL(media.src);
      }
      media.remove();
      media = null;
    }
  }

  function attach(url, isVideo, revoke, posterUrl) {
    clearMedia();
    media = document.createElement(isVideo ? 'video' : 'img');
    media.className = 'ss-framer__media';
    media.dataset.revoke = revoke ? '1' : '';
    if (isVideo) {
      media.muted = true; media.loop = true; media.playsInline = true;
      media.autoplay = true;
      // Something to look at while the clip loads, and the still we fall back
      // to if it never does.
      if (posterUrl) { media.poster = posterUrl; }
      media.addEventListener('loadedmetadata', function () {
        state.natW = media.videoWidth; state.natH = media.videoHeight; ready();
      });
    } else {
      media.alt = '';
      media.addEventListener('load', function () {
        state.natW = media.naturalWidth; state.natH = media.naturalHeight; ready();
      });
    }
    media.addEventListener('error', function () {
      // Not every browser decodes every container — Firefox will not touch
      // .mov. The poster has the same dimensions, so framing it produces the
      // identical crop; falling back beats a blank stage.
      if (isVideo && posterUrl) {
        hint.textContent = 'This browser cannot play that clip, so you are '
                         + 'framing a still from it. The crop is the same.';
        attach(posterUrl, false, false);
        return;
      }
      root.classList.remove('is-ready');
      hint.textContent = 'That file could not be previewed.';
    });
    media.src = url;
    clip.appendChild(media);
  }

  if (existingUrl) {
    // Re-framing an existing sticker: keep the stored focal point and zoom
    // rather than recentring, or opening the editor would silently discard
    // the framing someone already chose.
    attach(existingUrl, existingKind === 'video', false, existingPoster);
  }

  if (fileInput) { fileInput.addEventListener('change', function () {
    var file = fileInput.files && fileInput.files[0];
    clearMedia();
    if (!file) {
      root.classList.remove('is-ready');
      return;
    }

    var isVideo = /^video\//.test(file.type) ||
                  /\.(mp4|mov|m4v|webm)$/i.test(file.name);
    attach(URL.createObjectURL(file), isVideo, true);
  }); }

  function ready() {
    // A NEW file is recentred; an existing sticker keeps whatever framing was
    // stored for it. The slider's floor is per-image: a square photo cannot
    // zoom out at all, a wide one can pull back to its full width.
    if (!existingUrl) {
      state.focalX = 0.5; state.focalY = 0.5; state.zoom = 1;
    }
    zoomInput.min = fitZoom().toFixed(3);
    zoomInput.value = state.zoom;
    root.classList.add('is-ready');
    if (empty) { empty.hidden = true; }
    hint.textContent = 'Drag to move it. Arrow keys nudge. Slider zooms.';
    layout();
  }

  window.addEventListener('resize', layout);

  // If the form came back with errors, the file input is empty again but the
  // values the person chose are still in the hidden inputs — keep them.
  var chosen = fshape.value;
  var initial = chosen
    ? root.querySelector('[data-shape="' + chosen + '"]')
    : root.querySelector('[data-shape=""]');
  if (initial) { initial.click(); }
})();
