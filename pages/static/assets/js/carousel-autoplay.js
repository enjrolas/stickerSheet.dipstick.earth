/* Hero carousel pacing.
 *
 * Bootstrap's own `interval` is a fixed timer, which cannot wait for a video.
 * So the carousel is created with interval:false and advanced by hand:
 *   - a slide holding a <video> advances when the clip fires `ended`
 *   - any other slide advances after IMAGE_MS
 *
 * The videos are deliberately NOT `autoplay loop` in the markup: `loop` means
 * `ended` never fires, and playback is started here instead so it begins when
 * the slide actually arrives.
 */
(function () {
  "use strict";

  var IMAGE_MS = 5000;

  var root = document.querySelector('#carousel-1');
  if (!root || !window.bootstrap || !window.bootstrap.Carousel) return;

  var carousel = window.bootstrap.Carousel.getOrCreateInstance(root, {
    interval: false,
    ride: false,
    pause: false,
    wrap: true
  });

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  var timer = null;
  var video = null;
  var held = false;   // hovered / focused / tab hidden

  function clearTimer() {
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function releaseVideo() {
    if (!video) return;
    video.removeEventListener('ended', advance);
    video.removeEventListener('error', fallback);
    video.pause();
    try { video.currentTime = 0; } catch (e) { /* not seekable yet */ }
    video = null;
  }

  function advance() {
    clearTimer();
    if (held || reduce.matches) return;
    carousel.next();
  }

  // Never strand the carousel on a clip that will not play.
  function fallback() {
    clearTimer();
    timer = setTimeout(advance, IMAGE_MS);
  }

  function schedule() {
    clearTimer();
    releaseVideo();
    if (held || reduce.matches) return;

    var item = root.querySelector('.carousel-item.active');
    if (!item) return;

    var el = item.querySelector('video');
    if (!el) {
      timer = setTimeout(advance, IMAGE_MS);
      return;
    }

    video = el;
    video.addEventListener('ended', advance);
    video.addEventListener('error', fallback);
    try { video.currentTime = 0; } catch (e) { /* not seekable yet */ }

    // If the clip stalls mid-play, move on a little after it should have ended.
    video.addEventListener('loadedmetadata', function onMeta() {
      video.removeEventListener('loadedmetadata', onMeta);
      if (video && isFinite(video.duration)) {
        clearTimer();
        timer = setTimeout(advance, video.duration * 1000 + 5000);
      }
    });

    var playing = video.play();
    if (playing && typeof playing.catch === 'function') {
      playing.catch(fallback);   // blocked by autoplay policy, or decode failed
    }
  }

  function hold(on) {
    held = on;
    if (on) { clearTimer(); if (video) video.pause(); }
    else { schedule(); }
  }

  // WCAG 2.2.2: give people a way to stop the movement.
  root.addEventListener('mouseenter', function () { hold(true); });
  root.addEventListener('mouseleave', function () { hold(false); });
  root.addEventListener('focusin', function () { hold(true); });
  root.addEventListener('focusout', function () {
    if (!root.contains(document.activeElement)) hold(false);
  });

  // Don't burn through slides in a background tab.
  document.addEventListener('visibilitychange', function () {
    hold(document.hidden);
  });

  root.addEventListener('slid.bs.carousel', schedule);

  var onReduceChange = function () { clearTimer(); releaseVideo(); schedule(); };
  if (reduce.addEventListener) reduce.addEventListener('change', onReduceChange);
  else if (reduce.addListener) reduce.addListener(onReduceChange);

  schedule();   // no slid event fires for the slide already on screen
})();
