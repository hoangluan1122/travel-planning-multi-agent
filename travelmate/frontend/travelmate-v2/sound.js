// Âm thanh khi bấm (mặc định tắt, bật ở chân trang): tiếng "tách" nhẹ cho nút và thẻ, tiếng "pop" khi thả tim, tiếng chuông ngắn khi có thông
// báo. Tạo bằng Web Audio ngay trên trình duyệt (không tải file). Nút "Âm thanh" ở chân trang bật/tắt, lựa chọn
// được nhớ trong trình duyệt.

/* UI sounds synthesised with the Web Audio API: no audio files, nothing loaded from elsewhere.
   The AudioContext starts on the visitor's first press (browsers allow sound only after a gesture).
   Off by default: localStorage 'tm-sound' = 'on' (set by the footer button) turns them on. */
(() => {
  'use strict';
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  const KEY = 'tm-sound';
  // Off until the visitor turns it on: sound on a website should be a choice, not a surprise.
  const read = () => { try { return localStorage.getItem(KEY) === 'on'; } catch { return false; } };
  let enabled = read();
  let ctx;

  // One short tone: frequency glides from f0 to f1, quick attack, exponential fade.
  const tone = (f0, f1, ms, gain, type = 'sine', delay = 0) => {
    const t = ctx.currentTime + delay;
    const osc = ctx.createOscillator(), amp = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, t);
    osc.frequency.exponentialRampToValueAtTime(f1, t + ms / 1000);
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + 0.006);
    amp.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
    osc.connect(amp).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + ms / 1000 + 0.02);
  };
  const SOUNDS = {
    tick: () => tone(1500, 900, 45, 0.035, 'triangle'),
    pop: () => { tone(520, 1100, 110, 0.06); tone(1100, 1500, 90, 0.025, 'sine', 0.05); },
    chime: () => { tone(880, 880, 180, 0.03); tone(1320, 1320, 260, 0.025, 'sine', 0.09); },
  };
  const play = name => {
    if (!enabled) return;
    try {
      ctx = ctx || new AC();
      if (ctx.state === 'suspended') ctx.resume();
      SOUNDS[name]();
    } catch { /* sound is decoration: never break a click */ }
  };
  window.tmSound = play;

  // Press feedback on pointerdown, so it is heard before a link changes the page.
  const PRESSABLE = 'button, .button, a.tm-feature, a.tm-dest, .tm-trip-card a, a.api-card, header nav a, .tm-tabs a, .tm-quick-chips a, input[type=checkbox], input[type=radio], summary';
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const el = e.target.closest?.(PRESSABLE);
    if (!el || el.disabled || el.closest('#tm-sound-toggle')) return;
    play(el.closest('.tm-fav') ? 'pop' : 'tick');
  }, {passive: true});
  // Keyboard presses on buttons count too.
  document.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.closest?.('button, .button')) play(e.target.closest('.tm-fav') ? 'pop' : 'tick');
  });

  // A notice appearing ("Đã lưu", "Đã sao chép") gets a soft chime.
  const watchToast = () => {
    const toast = document.getElementById('toast');
    if (!toast) return;
    new MutationObserver(() => { if (toast.classList.contains('show')) play('chime'); })
      .observe(toast, {attributes: true, attributeFilter: ['class'], childList: true});
  };

  // Footer switch.
  const addToggle = () => {
    const footer = document.querySelector('footer.tm-footer');
    if (!footer || document.getElementById('tm-sound-toggle')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'tm-sound-toggle';
    const label = () => {
      button.textContent = enabled ? '🔊 Âm thanh: bật' : '🔇 Âm thanh: tắt';
      button.setAttribute('aria-pressed', String(enabled));
    };
    label();
    button.addEventListener('click', () => {
      enabled = !enabled;
      try { localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch { /* private mode: this page only */ }
      label();
      play('tick');
    });
    (footer.querySelector('.tm-footer-brand') || footer).append(button);
  };

  const start = () => { watchToast(); addToggle(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
