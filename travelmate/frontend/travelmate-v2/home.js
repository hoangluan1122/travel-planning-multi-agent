// Trang chủ: phần "Xem trước một lịch trình" (Huế 3 ngày, dữ liệu minh họa) với các tab Ngày 1/2/3, sơ đồ
// điểm dừng và vé theo ngày; và lời mời cuối trang đổi theo trạng thái đăng nhập.

/* Home page only. The preview is illustrative: ticket prices are the sourced ones in app/data/ticket_prices.json
   (Huế), the costs follow app/data/cost_reference.json (Huế, mid style, 2 people, 2 nights), the weather is made up
   and the page says so. Switching day cross-fades the list and redraws the route on the sketch map. */
(() => {
  'use strict';
  const root = document.getElementById('tm-preview');
  if (!root || !document.getElementById('home')?.classList.contains('visible')) return;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Sketch-map positions (viewBox 320×250): river runs west to east through the city.
  const PLACES = {
    daiNoi: {name: 'Đại Nội Huế', x: 150, y: 78}, thienMu: {name: 'Chùa Thiên Mụ', x: 56, y: 100},
    songHuong: {name: 'Phố đi bộ ven sông Hương', x: 212, y: 122}, coVat: {name: 'Bảo tàng Cổ vật Cung đình', x: 176, y: 62},
    khaiDinh: {name: 'Lăng Khải Định', x: 236, y: 208}, tuDuc: {name: 'Lăng Tự Đức', x: 112, y: 168},
    minhMang: {name: 'Lăng Minh Mạng', x: 74, y: 222}, dongBa: {name: 'Chợ Đông Ba', x: 214, y: 84},
  };
  const DAYS = [
    {weather: ['i-sun', 'Nắng, 30°C'], stops: [
      ['08:00', 'daiNoi', 'Vé 200.000 ₫'], ['11:30', null, 'Ăn trưa: bún bò Huế'], ['15:30', 'thienMu'], ['18:30', 'songHuong', 'Dạo tối, ăn chè']]},
    {weather: ['i-rain', 'Mưa rào, 25°C · một điểm ngoài trời'], stops: [
      ['08:30', 'coVat', 'Vé 50.000 ₫ · trong nhà'], ['11:30', null, 'Ăn trưa: cơm hến'], ['14:30', 'khaiDinh', 'Vé 150.000 ₫'], ['18:30', null, 'Ăn tối: bánh khoái']]},
    {weather: ['i-cloud', 'Nhiều mây, 27°C'], stops: [
      ['08:00', 'tuDuc', 'Vé 150.000 ₫'], ['10:30', 'minhMang', 'Vé 150.000 ₫'], ['12:30', null, 'Ăn trưa: bánh bèo, nậm, lọc'], ['15:00', 'dongBa', 'Mua đặc sản']]},
  ];
  const TICKETS = [200000, 200000, 300000];  // per person, per day (sum 700.000 ₫ = 1,4 triệu for 2 people)

  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const money = n => `${Math.round(n).toLocaleString('vi-VN')} ₫`;
  const tabs = [...root.querySelectorAll('[role=tab]')];
  const panel = root.querySelector('.tm-pv-panel');
  const list = root.querySelector('.tm-pv-stops');
  const weather = root.querySelector('.tm-pv-weather');
  const pinsLayer = root.querySelector('.tm-pv-pins');
  const route = root.querySelector('.tm-pv-route');
  const tickets = root.querySelector('[data-pv-tickets]');
  const svgNS = 'http://www.w3.org/2000/svg';

  // Every place gets a pin once; the day's pins are numbered and highlighted.
  const pins = {};
  for (const [key, place] of Object.entries(PLACES)) {
    const g = document.createElementNS(svgNS, 'g');
    g.setAttribute('class', 'tm-pv-pin');
    g.setAttribute('transform', `translate(${place.x} ${place.y})`);
    g.innerHTML = '<g class="tm-pv-pin-body"><circle r="11"></circle><text dy="4" text-anchor="middle"></text></g>';
    pinsLayer.append(g);
    pins[key] = g;
  }

  let current = 0, tween;
  const countTo = (el, from, to) => {
    cancelAnimationFrame(tween);
    if (still) { el.textContent = money(to); return; }
    const t0 = performance.now(), ms = 320;
    const step = now => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - (1 - k) ** 3;
      el.textContent = money(Math.round((from + (to - from) * e) / 1000) * 1000);
      if (k < 1) tween = requestAnimationFrame(step);
    };
    tween = requestAnimationFrame(step);
  };

  const draw = day => {
    const d = DAYS[day];
    weather.innerHTML = `<svg class="tm-i" aria-hidden="true"><use href="#${d.weather[0]}"></use></svg> ${esc(d.weather[1])}`;
    let n = 0;
    const order = [];
    list.innerHTML = d.stops.map(([time, key, note]) => {
      const place = key ? PLACES[key] : null;
      if (place) order.push(key);
      const num = place ? ++n : '';
      return `<li${key ? ` data-place="${key}"` : ' class="meal"'} style="--i:${order.length}">
        <span class="tm-pv-time">${time}</span>
        <span class="tm-pv-dot">${num || '<svg class="tm-i" aria-hidden="true"><use href="#i-food"></use></svg>'}</span>
        <span class="tm-pv-what"><b>${esc(place ? place.name : note)}</b>${place && note ? `<small>${esc(note)}</small>` : ''}</span>
      </li>`;
    }).join('');
    for (const [key, pin] of Object.entries(pins)) {
      const at = order.indexOf(key);
      pin.classList.toggle('on', at >= 0);
      pin.querySelector('text').textContent = at >= 0 ? String(at + 1) : '';
    }
    route.setAttribute('points', order.map(k => `${PLACES[k].x},${PLACES[k].y}`).join(' '));
    if (!still) { route.classList.remove('draw'); void route.getBBox(); route.classList.add('draw'); }
  };

  const select = (day, focus) => {
    if (day === current) return;
    const before = TICKETS[current];
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === day));
      tab.tabIndex = i === day ? 0 : -1;
    });
    panel.setAttribute('aria-labelledby', tabs[day].id);
    if (focus) tabs[day].focus();
    current = day;
    countTo(tickets, before, TICKETS[day]);
    if (still) { draw(day); return; }
    panel.classList.add('out');
    setTimeout(() => { draw(day); panel.classList.remove('out'); }, 180);
  };

  tabs.forEach((tab, i) => tab.addEventListener('click', () => select(i)));
  root.querySelector('[role=tablist]').addEventListener('keydown', e => {
    const move = {ArrowRight: 1, ArrowLeft: -1}[e.key];
    if (move) { e.preventDefault(); select((current + move + tabs.length) % tabs.length, true); }
    if (e.key === 'Home') { e.preventDefault(); select(0, true); }
    if (e.key === 'End') { e.preventDefault(); select(tabs.length - 1, true); }
  });

  // Pointing at a stop lights up its pin.
  const light = (key, on) => pins[key]?.classList.toggle('hot', on);
  list.addEventListener('pointerover', e => { const li = e.target.closest('li[data-place]'); if (li) light(li.dataset.place, true); });
  list.addEventListener('pointerout', e => { const li = e.target.closest('li[data-place]'); if (li) light(li.dataset.place, false); });

  draw(0);
  tickets.textContent = money(TICKETS[0]);

  // Signed in: the closing invitation talks to a member, not a visitor.
  let signedIn = false;
  try { signedIn = !!JSON.parse(localStorage.getItem('tm-session'))?.user; } catch { /* no session */ }
  if (signedIn) {
    document.querySelectorAll('.tm-cta [data-member-text]').forEach(el => { el.textContent = el.dataset.memberText; });
    document.querySelectorAll('.tm-cta [data-member-only]').forEach(el => { el.hidden = false; });
    document.querySelectorAll('.tm-cta [data-guest-only]').forEach(el => { el.hidden = true; });
  }
})();
