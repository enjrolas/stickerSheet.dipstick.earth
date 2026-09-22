/* Swap each sticker's LQIP placeholder for the real thumbnail once it has
   decoded, then unblur. Everything works without this — the placeholder is a
   real image and the links are plain hrefs; this only sharpens the grid. */
(function () {
  'use strict';

  function upgrade(img) {
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
    loader.onerror = function () {
      // Keep the placeholder rather than showing a broken image.
      img.classList.add('is-loaded');
    };
    loader.src = full;
  }

  var imgs = Array.prototype.slice.call(
    document.querySelectorAll('.ss-sticker__img[data-full]'));

  if (!('IntersectionObserver' in window)) {
    imgs.forEach(upgrade);
    return;
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        upgrade(entry.target);
        io.unobserve(entry.target);
      }
    });
  }, { rootMargin: '300px' });

  imgs.forEach(function (img) { io.observe(img); });
})();
