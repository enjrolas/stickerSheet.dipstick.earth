/* Sheet behaviour, all progressive enhancement:
   - photos: swap the tiny LQIP for the real thumbnail, then unblur
   - videos: only attach a source, and only play, while on screen

   The page is fully usable without any of this — every card is a plain link,
   photos already show their placeholder, and videos keep their poster. */
/* The navbar shrink lives in assets/js/startup-modern.js, which every page
   loads. It was duplicated here from before the sites merged. */

(function () {
  'use strict';

  var cards = Array.prototype.slice.call(
    document.querySelectorAll('.ss-sticker'));
  if (!cards.length) { return; }

  function upgradePhoto(img) {
    var full = img.getAttribute('data-full');
    if (!full || full === img.getAttribute('src')) {
      img.classList.add('is-loaded');
      return;
    }
    var loader = new Image();
    loader.onload = function () {
      img.src = full;
      img.classList.add('is-loaded');
    };
    // Keep the placeholder rather than showing a broken image.
    loader.onerror = function () { img.classList.add('is-loaded'); };
    loader.src = full;
  }

  function startVideo(video, card) {
    if (!video.src) {
      var src = video.getAttribute('data-src');
      if (!src) { return; }
      video.src = src;           // deferred so the sheet doesn't pull every clip
    }
    video.classList.add('is-loaded');
    var playing = video.play();
    if (playing && playing.catch) {
      // Autoplay can be refused (battery saver, reduced data). The poster
      // stays up, which is a perfectly good still sticker.
      playing.catch(function () { card.classList.remove('ss-sticker--playing'); });
    }
    card.classList.add('ss-sticker--playing');
  }

  function stopVideo(video, card) {
    if (!video.paused) { video.pause(); }
    card.classList.remove('ss-sticker--playing');
  }

  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function activate(card, on) {
    var video = card.querySelector('video.ss-sticker__media');
    if (video) {
      if (on && !reduceMotion) { startVideo(video, card); }
      else if (!on) { stopVideo(video, card); }
      return;
    }
    if (on) {
      var img = card.querySelector('img.ss-sticker__media[data-full]');
      if (img) { upgradePhoto(img); }
    }
  }

  if (!('IntersectionObserver' in window)) {
    cards.forEach(function (card) { activate(card, true); });
    return;
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      activate(entry.target, entry.isIntersecting);
      // Photos only need upgrading once; videos keep being observed so they
      // pause when scrolled away.
      if (entry.isIntersecting &&
          !entry.target.querySelector('video.ss-sticker__media')) {
        io.unobserve(entry.target);
      }
    });
  }, { rootMargin: '200px' });

  cards.forEach(function (card) { io.observe(card); });

  // A hidden tab should not keep decoding video.
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { return; }
    cards.forEach(function (card) {
      var video = card.querySelector('video.ss-sticker__media');
      if (video) { stopVideo(video, card); }
    });
  });
})();
