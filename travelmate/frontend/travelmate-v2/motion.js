// Chuyển động của trang (đi cùng motion.css): đánh dấu các khối để chúng trượt lên khi cuộn tới, bóng của thanh
// trên cùng khi cuộn, trái tim "nảy" khi bấm yêu thích, tin nhắn chat mới trượt vào. Người dùng chọn giảm
// chuyển động thì không làm gì.

/* Marks blocks with data-reveal and adds .tm-in when they first come into view; siblings that appear together
   are staggered. Screens are drawn after data arrives, so new blocks are picked up as they are added.
   Only presentation: no screen depends on this file, and without it every block is simply visible. */
(() => {
  'use strict';
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const BLOCKS = [
    '.hero-copy > *', '.hero-photo', '.page-intro', '.tm-head', '.tm-admin-head', '.tm-section > .eyebrow', '.tm-section > h2',
    '.tm-feature-grid > *', '.tm-preview-main', '.tm-preview-side > *', '.tm-dest-grid > *', '.tm-chat-demo', '.tm-trip-grid > *', '.api-grid > *', '.tm-stats > *',
    '.api-card', '.tm-plan-card', '.tm-account-card', '.tm-table-wrap', '.tm-stop', '.tm-weather', '.tm-cta', '.tm-doc > *',
    '.tm-loading', '.tm-empty', '.tm-auth', '.tm-timeline > *',
  ].join(',');
  const STEP_MS = 45, MAX_STAGGER = 4;
  // animationend bubbles up from children (the cost bar, a spinner): only the element's own animation counts.
  const onOwnAnimationEnd = (el, done) => {
    const handler = ev => { if (ev.target !== el) return; el.removeEventListener('animationend', handler); done(); };
    el.addEventListener('animationend', handler);
  };
  const started = performance.now();

  const observer = new IntersectionObserver(entries => {
    // Blocks entering together are staggered in document order, per parent.
    const entering = entries.filter(e => e.isIntersecting).map(e => e.target);
    const perParent = new Map();
    for (const el of entering) {
      const n = perParent.get(el.parentElement) || 0;
      perParent.set(el.parentElement, n + 1);
      el.style.setProperty('--stagger', `${Math.min(n, MAX_STAGGER) * STEP_MS}ms`);
      el.classList.add('tm-in');
      observer.unobserve(el);
      onOwnAnimationEnd(el, () => { el.removeAttribute('data-reveal'); el.classList.remove('tm-in'); el.style.removeProperty('--stagger'); });
    }
  }, {rootMargin: '0px 0px -6% 0px', threshold: 0.01});

  const mark = root => {
    const found = root.matches?.(BLOCKS) ? [root] : [];
    found.push(...(root.querySelectorAll?.(BLOCKS) || []));
    for (const el of found) {
      // One animation per area: skip a block inside another block that is still waiting to appear.
      if (el.hasAttribute('data-reveal') || el.dataset.revealed || el.parentElement?.closest('[data-reveal]')) continue;
      el.dataset.revealed = '1';
      el.setAttribute('data-reveal', '');
      observer.observe(el);
    }
  };

  const markNewChat = node => {
    if (performance.now() - started < 1200) return; // history drawn at load stays still
    const msgs = node.matches?.('.chat-msg') ? [node] : [...(node.querySelectorAll?.('.chat-msg') || [])];
    for (const m of msgs) { m.classList.add('tm-new'); onOwnAnimationEnd(m, () => m.classList.remove('tm-new')); }
  };

  const start = () => {
    document.querySelectorAll('main').forEach(mark);
    new MutationObserver(records => {
      for (const r of records) for (const node of r.addedNodes) {
        if (node.nodeType !== 1) continue;
        mark(node);
        markNewChat(node);
      }
    }).observe(document.body, {childList: true, subtree: true});
  };

  // Header gets a shadow once the page is scrolled.
  const header = document.querySelector('header');
  const onScroll = () => header?.classList.toggle('tm-scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, {passive: true});
  onScroll();

  // The heart pops when pressed.
  document.addEventListener('click', e => {
    const fav = e.target.closest?.('.tm-fav');
    if (!fav) return;
    fav.classList.remove('tm-pop');
    void fav.offsetWidth; // restart the animation on quick repeated clicks
    fav.classList.add('tm-pop');
    onOwnAnimationEnd(fav, () => fav.classList.remove('tm-pop'));
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
