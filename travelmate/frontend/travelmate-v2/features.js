/* Account, trips, favourites, place pages, reviews, trip editing and admin screens.
   Uses helpers exposed by integration.js (window.tm). Everything shown comes from the API;
   user text is always escaped. */
(() => {
  'use strict';
  const tm = window.tm;
  if (!tm) return;
  const {api, render, esc, money, time, kind, photo, price, stars, hours, placeLinks, ticketSource, read, save, records, session, route, params, fmtDate, dateRange, emptyState, head, loginGate, dialog, notify} = tm;
  const get = path => api(path, null, undefined, 'GET');
  const del = path => api(path, null, undefined, 'DELETE');
  const patch = (path, data) => api(path, data, undefined, 'PATCH');
  const put = (path, data) => api(path, data ?? {}, undefined, 'PUT');
  const go = view => { location.href = '?view=' + view; };
  const user = () => session()?.user || null;
  const date = s => s ? new Date(s * 1000).toLocaleString('vi-VN', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
  const btn = (text, attrs = '', cls = 'button outline') => `<button type="button" class="${cls}" ${attrs}>${text}</button>`;
  const status = id => `<p class="api-meta" id="${id}" role="status"></p>`;
  const say = (el, text, ok = false) => { el.textContent = text; el.style.color = ok ? '#1b6e3a' : '#a33'; };
  const field = (label, name, type = 'text', value = '', extra = '') =>
    `<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
  const statusLabel = {pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Bị từ chối', hidden: 'Đã ẩn'};
  const starText = n => '★'.repeat(n) + '☆'.repeat(5 - n);

  const style = document.createElement('style');
  style.textContent = '.tm-table{width:100%;border-collapse:collapse;font-size:14px}.tm-table th,.tm-table td{border-bottom:1px solid #e5e2da;padding:8px;text-align:left;vertical-align:top}.tm-badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;background:#ece8dd}.tm-badge.pending{background:#fff1c2}.tm-badge.approved{background:#d8f0dd}.tm-badge.rejected,.tm-badge.hidden{background:#f6d6d6}.tm-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tm-tabs a.active{background:#16302b;color:#fff}.tm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.tm-stats .api-card strong{font-size:28px;display:block}.tm-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.tm-row input[type=time]{padding:6px}.tm-auth{max-width:440px}.tm-fav{font-size:22px;background:none;border:0;cursor:pointer}';
  document.head.prepend(style);  // before the stylesheets, so theme.css can restyle it

  // Header: avatar goes to the account; admins get a link to the admin area.
  const avatar = document.querySelector('header .avatar');
  if (avatar) {
    const u = user();
    avatar.href = u ? '?view=profile' : '?view=login';
    if (u) { avatar.innerHTML = `<b>${esc((u.name.trim()[0] || 'T').toUpperCase())}</b><span>${esc(u.name)}</span>`; avatar.classList.add('tm-user'); }
    else { avatar.textContent = 'Đăng nhập'; avatar.classList.add('tm-login'); }
    avatar.setAttribute('aria-label', u ? `Tài khoản của ${u.name}` : 'Đăng nhập');
    const nav = document.querySelector('header nav');
    if (nav && u) {
      nav.insertAdjacentHTML('beforeend', `<a href="?view=favorites"${route === 'favorites' ? ' aria-current="page"' : ''}>Yêu thích</a>`);
      if (u.role === 'admin') nav.insertAdjacentHTML('beforeend', `<a href="?view=admin"${['admin', 'admin-users', 'admin-places', 'moderation', 'admin-messages'].includes(route) ? ' aria-current="page"' : ''}>Quản trị</a>`);
    }
  }
  // Offers that only make sense before signing in.
  if (user()) document.querySelectorAll('[data-guest-only]').forEach(e => { e.hidden = true; });

  function needLogin() {
    if (user()) return false;
    render(loginGate('Trang này gắn với tài khoản của bạn.'));
    return true;
  }
  const signedIn = (data, next) => {
    localStorage.setItem('tm-session', JSON.stringify({user: data.user}));  // the token stays in the HttpOnly cookie
    location.href = next && next.startsWith('?') ? next : '?view=saved';
  };
  const refreshUser = u => { const s = session(); if (s) localStorage.setItem('tm-session', JSON.stringify({...s, user: u})); };

  // --- login / signup / forgot -----------------------------------------------------------
  const next = params.get('next');
  const nextQ = next ? '&next=' + encodeURIComponent(next) : '';
  const authShell = (eyebrow, title, text, body) => `<div class="tm-auth-layout"><div class="auth-visual"><img src="/ui/travelmate-ui/assets/beach.jpg" alt=""><div><div class="eyebrow">MỌI HÀNH TRÌNH ĐỀU BẮT ĐẦU TỪ BẠN.</div><h2>Để những điều<br>đáng nhớ bắt đầu.</h2><p>Một tài khoản để lưu lịch trình, địa điểm yêu thích và các cuộc trò chuyện.</p></div></div>
    <section class="tm-auth"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${text}</p>${body}</section></div>`;
  if (route === 'login' || route === 'signup') {
    const login = route === 'login';
    if (user()) { location.replace(next && next.startsWith('?') ? next : '?view=saved'); return; }
    const main = render(authShell(login ? 'CHÀO MỪNG TRỞ LẠI' : 'TẠO TÀI KHOẢN', login ? 'Rất vui gặp lại bạn.' : 'Bắt đầu điều mới.',
      login ? 'Lịch trình và địa điểm đã lưu vẫn ở đây.' : 'Miễn phí. Chỉ cần tên, email và mật khẩu.',
      `<form class="api-card" id="tm-auth">${login ? '' : field('Họ và tên', 'name', 'text', '', 'required maxlength="80" autocomplete="name"')}
      ${field('Email', 'email', 'email', '', 'required maxlength="254" autocomplete="email"')}
      ${field('Mật khẩu' + (login ? '' : ' (ít nhất 8 ký tự)'), 'password', 'password', '', `required ${login ? '' : 'minlength="8"'} maxlength="128" autocomplete="${login ? 'current-password' : 'new-password'}"`)}
      <button class="button dark full">${login ? 'Đăng nhập' : 'Tạo tài khoản'} <span>→</span></button>${status('tm-auth-status')}</form>
      <p class="tm-auth-switch">${login ? `Chưa có tài khoản? <a href="?view=signup${nextQ}">Đăng ký</a> · <a href="?view=forgot">Quên mật khẩu?</a>` : `Đã có tài khoản? <a href="?view=login${nextQ}">Đăng nhập</a>`}</p>`));
    main.querySelector('#tm-auth').onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(e.target), out = main.querySelector('#tm-auth-status'), b = e.target.querySelector('button');
      b.disabled = true; say(out, 'Đang xử lý…', true);
      try {
        const body = {email: f.get('email'), password: f.get('password'), ...(login ? {} : {name: f.get('name')})};
        signedIn(await api(login ? '/api/v1/auth/login' : '/api/v1/auth/signup', body), next);
      } catch (err) { say(out, err.message); b.disabled = false; }
    };
    if (!login) tm.health.then(h => { if (h && h.signup_open === false) main.querySelector('#tm-auth').outerHTML = '<p class="tm-note">Hiện chưa mở đăng ký tài khoản mới. Hãy liên hệ quản trị viên để được cấp tài khoản.</p>'; });
  }
  if (route === 'forgot') {
    const token = params.get('reset');
    const main = render(token
      ? authShell('ĐẶT LẠI MẬT KHẨU', 'Đặt mật khẩu mới.', 'Chọn một mật khẩu bạn chưa dùng ở nơi khác.', `<form class="api-card" id="tm-reset">${field('Mật khẩu mới (ít nhất 8 ký tự)', 'password', 'password', '', 'required minlength="8" maxlength="128" autocomplete="new-password"')}<button class="button dark full">Lưu mật khẩu <span>→</span></button>${status('tm-reset-status')}</form>`)
      : authShell('TÌM LẠI TÀI KHOẢN', 'Quên mật khẩu?', 'Nhập email để tạo link đặt lại mật khẩu, hiệu lực 30 phút.', `<form class="api-card" id="tm-forgot">${field('Email', 'email', 'email', '', 'required maxlength="254" autocomplete="email"')}<button class="button dark full">Tạo link đặt lại <span>→</span></button>${status('tm-forgot-status')}</form><p class="tm-auth-switch"><a href="?view=login">← Quay lại đăng nhập</a></p>`));
    const form = main.querySelector('form'), out = main.querySelector('[role=status]');
    form.onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(form);
      try {
        if (token) { await api('/api/v1/auth/reset', {token, password: f.get('password')}); say(out, 'Đã đổi mật khẩu. Đang chuyển tới đăng nhập…', true); setTimeout(() => go('login'), 1200); }
        else { const r = await api('/api/v1/auth/forgot', {email: f.get('email')}); say(out, r.message, true); }
      } catch (err) { say(out, err.message); }
    };
  }

  // --- profile ---------------------------------------------------------------------------
  if (route === 'profile' && !needLogin()) {
    const u = user();
    const main = render(head('TÀI KHOẢN', `Xin chào, ${esc(u.name)}.`, `${esc(u.email)} · ${u.role === 'admin' ? 'Quản trị viên' : 'Thành viên'}`,
      `${tm.link('saved', 'Chuyến đi của tôi')}${tm.link('favorites', 'Địa điểm yêu thích')}${u.role === 'admin' ? tm.link('admin', 'Quản trị') : ''}${btn('Đăng xuất', 'id="tm-logout"')}`) + `<div class="tm-profile-grid">
      <form class="api-card" id="tm-profile"><h3>Thông tin cá nhân</h3>${field('Họ và tên', 'name', 'text', u.name, 'required maxlength="80"')}
      ${field('Sở thích du lịch (cách nhau bằng dấu phẩy, tối đa 10)', 'interests', 'text', (u.interests || []).join(', '), 'maxlength="440"')}
      <p class="api-meta">Sở thích được điền sẵn khi bạn tạo chuyến đi mới.</p><button class="button dark">Lưu thay đổi</button>${status('tm-profile-status')}</form>
      <form class="api-card" id="tm-password"><h3>Đổi mật khẩu</h3>${field('Mật khẩu hiện tại', 'current', 'password', '', 'required autocomplete="current-password"')}${field('Mật khẩu mới (ít nhất 8 ký tự)', 'next', 'password', '', 'required minlength="8" maxlength="128" autocomplete="new-password"')}<button class="button dark">Đổi mật khẩu</button>${status('tm-password-status')}</form>
      <section class="api-card"><h3>Đánh giá của bạn</h3><div id="tm-my-reviews">Đang tải…</div></section>
      <form class="api-card tm-danger-zone" id="tm-delete"><h3>Xoá tài khoản</h3><p>Xoá vĩnh viễn tài khoản, chuyến đi, yêu thích và đánh giá của bạn.</p>${field('Nhập mật khẩu để xác nhận', 'password', 'password', '', 'required autocomplete="current-password"')}<button class="button danger">Xoá tài khoản</button>${status('tm-delete-status')}</form></div>`);
    main.querySelector('#tm-logout').onclick = async () => { try { await api('/api/v1/auth/logout', {}); } catch {} localStorage.removeItem('tm-session'); go('home'); };
    main.querySelector('#tm-profile').onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target), out = main.querySelector('#tm-profile-status');
      const interests = String(f.get('interests')).split(',').map(s => s.trim()).filter(Boolean);
      try { refreshUser(await patch('/api/v1/me', {name: f.get('name'), interests})); say(out, 'Đã lưu.', true); notify('Đã lưu thông tin cá nhân.'); } catch (err) { say(out, err.message); }
    };
    main.querySelector('#tm-password').onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target), out = main.querySelector('#tm-password-status');
      try { await api('/api/v1/me/password', {current_password: f.get('current'), new_password: f.get('next')}); e.target.reset(); say(out, 'Đã đổi mật khẩu; các thiết bị khác đã bị đăng xuất.', true); } catch (err) { say(out, err.message); }
    };
    main.querySelector('#tm-delete').onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target), out = main.querySelector('#tm-delete-status');
      if (!await dialog({title: 'Xoá vĩnh viễn tài khoản?', text: 'Chuyến đi, yêu thích và đánh giá của bạn sẽ bị xoá và không khôi phục được.', ok: 'Xoá tài khoản', danger: true})) return;
      try { await api('/api/v1/me/delete', {password: f.get('password')}); localStorage.removeItem('tm-session'); go('home'); } catch (err) { say(out, err.message); }
    };
    get('/api/v1/me/reviews').then(list => {
      main.querySelector('#tm-my-reviews').innerHTML = list.length ? list.map(r => `<p><a href="?view=place&id=${encodeURIComponent(r.place_id)}">${esc(r.place_name)}</a> · <span class="tm-stars">${starText(r.rating)}</span> · <span class="tm-badge ${r.status}">${statusLabel[r.status]}</span>${r.moderation_note ? ` · Ghi chú: ${esc(r.moderation_note)}` : ''}</p>`).join('') : '<p>Bạn chưa viết đánh giá nào. Mở một địa điểm để chia sẻ trải nghiệm.</p>';
    }).catch(err => { main.querySelector('#tm-my-reviews').textContent = err.message; });
  }

  // Create form: pre-fill interests from the profile (as free-text notes when no checkbox matches).
  if (route === 'create' && user()?.interests?.length && !read('tm-request', null)) {
    const form = document.querySelector('[data-form=create]');
    if (form) {
      const boxes = [...form.querySelectorAll('[name=interests]')];
      const rest = user().interests.filter(i => { const box = boxes.find(b => b.value.toLowerCase() === i.toLowerCase()); if (box) box.checked = true; return !box; });
      if (rest.length && form.elements.notes && !form.elements.notes.value) form.elements.notes.value = 'Sở thích: ' + rest.join(', ');
    }
  }

  // --- saved trips (account) -------------------------------------------------------------
  const openTrip = (trip, day = null) => {
    const record = {request: trip.request, result: trip.result, trip_id: trip.id, title: trip.title};
    save('tm-plans', [record, ...records().filter(r => r.result.request_id !== trip.result.request_id)].slice(0, 20));
    save('tm-current', trip.result.request_id);
    const id = encodeURIComponent(trip.result.request_id);
    location.replace(day === null ? `?view=plan&id=${id}` : `?view=day&id=${id}&day=${encodeURIComponent(day)}`);
  };
  // A plan link opened in another tab or device: plans live per tab, so find it among the saved trips.
  const planId = params.get('id');
  if ((route === 'plan' || route === 'day') && planId && !records().some(r => r.result.request_id === planId)) {
    const missing = () => render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-map"></use></svg>', 'Không mở được lịch trình này.', user()
      ? 'Lịch trình không có trong tài khoản của bạn. Lịch chưa lưu chỉ mở được trong thẻ trình duyệt đã tạo ra nó.'
      : 'Lịch trình chưa lưu chỉ mở được trong thẻ trình duyệt đã tạo ra nó. Nếu bạn đã lưu chuyến đi này, hãy đăng nhập để mở lại.',
      user() ? tm.link('saved', 'Chuyến đi của tôi', 'button dark') + tm.link('create', 'Tạo chuyến đi')
        : tm.link(`login&next=${encodeURIComponent(location.search)}`, 'Đăng nhập', 'button dark') + tm.link('create', 'Tạo chuyến đi')));
    if (user()) {
      render('<p class="tm-loading-line">Đang mở lịch trình…</p>');
      get('/api/v1/me/trips')
        .then(list => list.find(t => t.request_id === planId))
        .then(t => t ? get(`/api/v1/me/trips/${encodeURIComponent(t.id)}`).then(trip => openTrip(trip, route === 'day' ? params.get('day') || '0' : null)) : missing())
        .catch(missing);
    } else missing();
  }
  if (route === 'trip' && !needLogin()) {
    render('<p class="tm-loading-line">Đang mở chuyến đi…</p>');
    get(`/api/v1/me/trips/${encodeURIComponent(params.get('id') || '')}`).then(openTrip).catch(err => render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-alert"></use></svg>', 'Không mở được chuyến đi.', esc(err.message), tm.link('saved', 'Chuyến đi của tôi', 'button dark'))));
  }
  if (route === 'saved' && user()) {
    const main = render(head(`XIN CHÀO, ${esc(user().name.toUpperCase())}`, 'Chuyến đi của bạn.', 'Mở lại, chỉnh sửa hoặc đổi tên các lịch trình đã lưu.', tm.link('create', 'Tạo chuyến đi', 'button dark') + tm.link('chat', 'Hỏi Trợ lý AI')) + '<div id="tm-trips"><p class="tm-loading-line">Đang tải…</p></div>');
    const box = main.querySelector('#tm-trips');
    const draw = list => {
      box.innerHTML = list.length ? `<div class="tm-trip-grid">${list.map(t => `<article class="tm-trip-card"><div class="eyebrow">${esc(dateRange(t.start_date, t.end_date))}</div><h3>${esc(t.title)}</h3><p>${esc(t.destination)} · ${t.days} ngày · cập nhật ${date(t.updated_at)}</p><div class="tm-row"><a class="button dark" href="?view=trip&id=${encodeURIComponent(t.id)}">Mở</a><a class="button outline" href="?view=edit&id=${encodeURIComponent(t.id)}">Chỉnh sửa</a>${btn('Đổi tên', `data-rename="${esc(t.id)}" data-title="${esc(t.title)}"`)}${btn('Xoá', `data-delete="${esc(t.id)}" data-title="${esc(t.title)}"`, 'button outline tm-danger-text')}</div></article>`).join('')}</div>`
        : emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-luggage"></use></svg>', 'Chưa có chuyến đi nào.', 'Tạo chuyến đầu tiên: nhập điểm đến, ngày đi và ngân sách.', tm.link('create', 'Tạo chuyến đi', 'button dark') + tm.link('explore', 'Tìm địa điểm'));
    };
    const load = () => get('/api/v1/me/trips').then(draw).catch(err => { box.innerHTML = `<p class="api-error">${esc(err.message)}</p>`; });
    box.onclick = async e => {
      const rename = e.target.dataset.rename, remove = e.target.dataset.delete;
      try {
        if (rename) { const title = await dialog({title: 'Đổi tên chuyến đi', input: {label: 'Tên mới', value: e.target.dataset.title, max: 120}, ok: 'Lưu'}); if (title) { await patch(`/api/v1/me/trips/${rename}`, {title: title.slice(0, 120)}); notify('Đã đổi tên chuyến đi.'); load(); } }
        if (remove && await dialog({title: 'Xoá chuyến đi này?', text: `“${e.target.dataset.title}” sẽ bị xoá khỏi tài khoản và không khôi phục được.`, ok: 'Xoá', danger: true})) { await del(`/api/v1/me/trips/${remove}`); notify('Đã xoá chuyến đi.'); load(); }
      } catch (err) { notify(err.message); }
    };
    load();
  }

  // Plan page: save to account / edit.
  const planBox = document.querySelector('#tm-plan-account');
  if (planBox) {
    const id = params.get('id') || read('tm-current', '');
    const record = records().find(r => r.result.request_id === id);
    const drawBox = () => {
      if (!user()) { planBox.innerHTML = `<p class="tm-note"><a href="?view=login&next=${encodeURIComponent(location.search)}">Đăng nhập</a> để lưu chuyến đi vào tài khoản, chỉnh sửa và thêm địa điểm yêu thích.</p>`; return; }
      planBox.innerHTML = record?.trip_id
        ? `<div class="tm-row"><span class="tm-badge approved">Đã lưu vào tài khoản</span><a class="button outline" href="?view=edit&id=${encodeURIComponent(record.trip_id)}">Chỉnh sửa lịch trình</a>${record.result.edited ? '<span class="api-meta">Lịch đã được bạn chỉnh sửa; chi phí đã tính lại.</span>' : ''}</div>`
        : `<div class="tm-row">${btn('Lưu vào tài khoản', 'id="tm-save-trip"', 'button dark')}<span class="api-meta" id="tm-save-status"></span></div>`;
      planBox.querySelector('#tm-save-trip')?.addEventListener('click', async () => {
        try { const t = await api('/api/v1/me/trips', {request: record.request, result: record.result}); record.trip_id = t.id; save('tm-plans', records().map(r => r.result.request_id === id ? record : r)); drawBox(); }
        catch (err) { planBox.querySelector('#tm-save-status').textContent = err.message; }
      });
    };
    if (record) drawBox();
  }

  // --- favourites ------------------------------------------------------------------------
  const card = (p, extra = '') => `<article class="api-card">${photo(p, 'api-thumb')}<h3><a href="?view=place&id=${encodeURIComponent(p.id)}">${esc(p.name)}</a></h3>${kind(p) ? `<p class="api-meta">${esc(kind(p))}</p>` : ''}<p>${esc(p.address || '')}</p><p>${esc(price(p))}</p>${extra}</article>`;
  if (route === 'favorites' && !needLogin()) {
    const main = render(head('YÊU THÍCH', 'Những nơi bạn muốn ghé.', 'Bấm nút trái tim ở trang địa điểm để lưu. Địa điểm yêu thích có thể thêm vào lịch khi chỉnh sửa chuyến đi.') + '<div id="tm-favs"><p class="tm-loading-line">Đang tải…</p></div>');
    const box = main.querySelector('#tm-favs');
    const load = () => get('/api/v1/me/favorites').then(list => { box.innerHTML = list.length ? `<div class="api-grid">${list.map(p => card(p, btn('Bỏ yêu thích', `data-unfav="${esc(p.id)}"`))).join('')}</div>` : emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-heart"></use></svg>', 'Chưa có địa điểm yêu thích.', 'Tìm một nơi bạn thích rồi bấm trái tim để giữ lại cho chuyến đi sau.', tm.link('explore', 'Tìm địa điểm', 'button dark')); }).catch(err => { box.innerHTML = `<p class="api-error">${esc(err.message)}</p>`; });
    box.onclick = async e => { const id = e.target.dataset.unfav; if (id) { try { await del(`/api/v1/me/favorites/${encodeURIComponent(id)}`); notify('Đã bỏ khỏi yêu thích.'); load(); } catch (err) { notify(err.message); } } };
    load();
  }

  // --- place page --------------------------------------------------------------------------
  if (route === 'place') {
    const id = params.get('id');
    const main = render('<p class="tm-loading-line">Đang tải địa điểm…</p>');
    if (!id) { render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-pin"></use></svg>', 'Chưa chọn địa điểm.', 'Mở một địa điểm từ lịch trình, trang Khám phá hoặc Trợ lý AI.', tm.link('explore', 'Tìm địa điểm', 'button dark'))); return; }
    const draw = data => {
      const p = data.place, u = user();
      const reviews = data.reviews.map(r => `<article class="api-card"><div class="tm-row"><strong>${esc(r.author)}</strong><span class="tm-stars">${starText(r.rating)}</span>${r.status !== 'approved' ? `<span class="tm-badge ${r.status}">${statusLabel[r.status]}</span>` : ''}</div><p>${esc(r.text)}</p><p class="api-meta">${date(r.updated_at)}${r.mine ? ' · đánh giá của bạn' : ''}${r.moderation_note && r.mine ? ` · Ghi chú kiểm duyệt: ${esc(r.moderation_note)}` : ''}</p>${u && !r.mine && r.status === 'approved' ? btn('Báo cáo', `data-report="${esc(r.id)}"`) : ''}</article>`).join('');
      const mine = data.reviews.find(r => r.mine);
      main.innerHTML = `<div class="page-shell tm-place"><button type="button" class="back" id="tm-back">← Quay lại</button>
        <div class="tm-place-top">${photo(p, 'tm-place-photo')}<div class="tm-place-info"><div class="eyebrow">${esc((kind(p) || 'ĐỊA ĐIỂM').toUpperCase())}${data.hidden ? ' · ĐANG ẨN (chỉ quản trị viên thấy)' : ''}</div>
        <div class="tm-row tm-place-title"><h1>${esc(p.name)}</h1>${u ? `<button class="tm-fav" id="tm-fav" aria-pressed="${data.favorite}" aria-label="${data.favorite ? 'Bỏ yêu thích' : 'Thêm yêu thích'}" title="${data.favorite ? 'Bỏ yêu thích' : 'Thêm yêu thích'}"><svg class="tm-i" aria-hidden="true"><use href="#i-heart"></use></svg></button>` : ''}</div>
        <p>${esc(p.address || 'Chưa có địa chỉ')}</p>${stars(p)}
        <p><strong>${data.average_rating != null ? `${data.average_rating}/5 từ ${data.review_count} đánh giá TravelMate` : 'Chưa có đánh giá TravelMate'}</strong></p>
        <p>${esc(price(p))}</p>${ticketSource(p)}${hours(p)}<p>${placeLinks(p)}</p>
        ${data.admin_note ? `<div class="tm-note"><strong>Ghi chú từ TravelMate</strong><br>${esc(data.admin_note)}</div>` : ''}
        <p class="api-meta">Nguồn: ${esc(p.attribution || p.source || 'Chưa xác định')}</p>
        <div class="api-actions">${u ? `<a class="button dark" href="?view=review&id=${encodeURIComponent(p.id)}">${mine ? 'Sửa đánh giá của bạn' : 'Viết đánh giá'}</a>` : tm.link('login&next=' + encodeURIComponent(location.search), 'Đăng nhập để lưu và đánh giá', 'button dark')}${tm.link('chat&q=' + encodeURIComponent(`${p.name} có gì đặc biệt?`), 'Hỏi Trợ lý AI về nơi này')}</div></div></div>
        <h2 class="tm-section-title">Đánh giá</h2><p class="api-meta">Đánh giá mới hiển thị sau khi được kiểm duyệt.</p>${reviews || '<p class="tm-reviews-empty">Chưa có đánh giá nào. Bạn đã đến đây? Hãy chia sẻ trải nghiệm để giúp người đi sau.</p>'}</div>`;
      main.querySelector('#tm-back').onclick = () => { history.length > 1 ? history.back() : go('explore'); };
      main.querySelector('#tm-fav')?.addEventListener('click', async () => {
        try { data.favorite ? await del(`/api/v1/me/favorites/${encodeURIComponent(p.id)}`) : await put(`/api/v1/me/favorites/${encodeURIComponent(p.id)}`); data.favorite = !data.favorite; draw(data); notify(data.favorite ? 'Đã thêm vào yêu thích.' : 'Đã bỏ khỏi yêu thích.'); } catch (err) { notify(err.message); }
      });
      main.querySelectorAll('[data-report]').forEach(b => b.onclick = async () => {
        const reason = await dialog({title: 'Báo cáo đánh giá', input: {label: 'Lý do (ví dụ: spam, xúc phạm, sai sự thật)', max: 300}, ok: 'Gửi báo cáo'});
        if (!reason) return;
        try { await api(`/api/v1/reviews/${b.dataset.report}/report`, {reason: reason.trim().slice(0, 300)}); b.replaceWith(Object.assign(document.createElement('span'), {className: 'api-meta', textContent: 'Đã gửi báo cáo cho quản trị viên.'})); } catch (err) { notify(err.message); }
      });
    };
    get(`/api/v1/places/${encodeURIComponent(id)}`).then(draw).catch(err => render(err.auth ? loginGate('Đăng nhập để xem địa điểm này.') : emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-pin"></use></svg>', 'Không tìm thấy địa điểm.', esc(err.message), tm.link('explore', 'Tìm địa điểm', 'button dark'))));
  }

  // --- review form -------------------------------------------------------------------------
  if (route === 'review' && !needLogin()) {
    const id = params.get('id');
    const main = render('<p class="tm-loading-line">Đang tải…</p>');
    get(`/api/v1/places/${encodeURIComponent(id || '')}`).then(data => {
      const mine = data.reviews.find(r => r.mine);
      main.innerHTML = `<div class="page-shell tm-narrow">${head('VIẾT ĐÁNH GIÁ', esc(data.place.name), 'Đánh giá trung thực giúp người đi sau có thêm góc nhìn.')}
        <form class="api-card" id="tm-review"><fieldset><legend>Điểm của bạn</legend><div class="tm-rating">${[1, 2, 3, 4, 5].map(n => `<label><input type="radio" name="rating" value="${n}" required ${mine?.rating === n ? 'checked' : ''}><span>${starText(n)}</span></label>`).join('')}</div></fieldset>
        <label class="field">Trải nghiệm của bạn (10–1000 ký tự)<textarea name="text" required minlength="10" maxlength="1000" rows="5">${esc(mine?.text || '')}</textarea></label>
        <p class="api-meta">Đánh giá được quản trị viên duyệt trước khi hiển thị công khai. Sửa đánh giá sẽ cần duyệt lại.</p>
        <div class="tm-row"><button class="button dark">Gửi đánh giá</button>${mine ? btn('Xoá đánh giá', 'id="tm-review-delete"') : ''}<a class="button outline" href="?view=place&id=${encodeURIComponent(id)}">Quay lại</a></div>${status('tm-review-status')}</form></div>`;
      const out = main.querySelector('#tm-review-status');
      main.querySelector('#tm-review').onsubmit = async e => {
        e.preventDefault(); const f = new FormData(e.target);
        try { await put(`/api/v1/places/${encodeURIComponent(id)}/review`, {rating: Number(f.get('rating')), text: String(f.get('text'))}); say(out, 'Đã gửi. Đánh giá sẽ hiển thị sau khi được duyệt.', true); setTimeout(() => { location.href = `?view=place&id=${encodeURIComponent(id)}`; }, 1200); } catch (err) { say(out, err.message); }
      };
      main.querySelector('#tm-review-delete')?.addEventListener('click', async () => {
        if (!await dialog({title: 'Xoá đánh giá của bạn?', ok: 'Xoá', danger: true})) return;
        try { await del(`/api/v1/places/${encodeURIComponent(id)}/review`); location.href = `?view=place&id=${encodeURIComponent(id)}`; } catch (err) { say(out, err.message); }
      });
    }).catch(err => render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-pin"></use></svg>', 'Không tìm thấy địa điểm.', esc(err.message), tm.link('explore', 'Tìm địa điểm', 'button dark'))));
  }

  // --- edit a saved trip -------------------------------------------------------------------
  if (route === 'edit' && !needLogin()) {
    const id = params.get('id');
    if (!id) { render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-pencil"></use></svg>', 'Chọn chuyến đi để chỉnh sửa.', 'Chỉ chuyến đi đã lưu vào tài khoản mới chỉnh sửa được.', tm.link('saved', 'Chuyến đi của tôi', 'button dark'))); return; }
    const main = render('<p class="tm-loading-line">Đang tải chuyến đi…</p>');
    const toMin = v => { const [h, m] = String(v).split(':').map(Number); return h * 60 + m; };
    Promise.all([get(`/api/v1/me/trips/${encodeURIComponent(id)}`), get('/api/v1/me/favorites')]).then(([trip, favs]) => {
      const places = new Map([...trip.result.places, ...favs].map(p => [p.id, p]));
      const days = trip.result.draft.days.map(d => ({date: d.date, activities: d.activities.map(a => ({...a}))}));
      const added = new Set();
      const costs = (trip.result.user_costs || []).map(c => ({...c}));
      const costKinds = {lodging: 'Lưu trú', food: 'Ăn uống', transport: 'Di chuyển', other: 'Khác'};
      const costRows = () => costs.map((c, i) => `<div class="tm-row tm-edit-row"><select data-cost="${i}" data-ck="category" aria-label="Loại chi phí">${Object.entries(costKinds).map(([k, t]) => `<option value="${k}" ${c.category === k ? 'selected' : ''}>${t}</option>`).join('')}</select><input data-cost="${i}" data-ck="label" value="${esc(c.label)}" maxlength="80" placeholder="Ví dụ: Khách sạn 2 đêm" aria-label="Tên khoản chi"><input data-cost="${i}" data-ck="amount_vnd" type="number" min="1" step="1000" value="${c.amount_vnd}" aria-label="Số tiền (₫)"> ₫ ${btn('Bỏ', `data-cost-remove="${i}"`, 'button outline tm-small')}</div>`).join('');
      const draw = () => {
        main.innerHTML = `<div class="page-shell tm-edit"><a class="back" href="?view=trip&id=${encodeURIComponent(id)}">← Về lịch trình</a>${head('CHỈNH SỬA LỊCH TRÌNH', esc(trip.title), `${esc(trip.request.destination)} · ${esc(dateRange(days[0].date, days[days.length - 1].date))}`)}
          ${field('Tên chuyến đi', 'title', 'text', trip.title, 'maxlength="120" id="tm-title"')}
          <section class="api-card"><h3>Ngày và sắp xếp</h3><div class="tm-row"><label>Ngày đi mới <input type="date" id="tm-new-start" value="${esc(trip.request.start_date)}" min="${new Date().toISOString().slice(0, 10)}"></label>${btn('Đổi ngày (giữ nguyên lịch)', 'id="tm-move-dates"')}${btn('Xếp lại tự động', 'id="tm-auto-arrange"')}</div><div class="tm-row"><label>Mức chi tiêu <select id="tm-style">${[['budget', 'Tiết kiệm'], ['mid', 'Vừa phải'], ['high', 'Cao cấp']].map(([k, t]) => `<option value="${k}" ${(trip.request.travel_style || 'mid') === k ? 'selected' : ''}>${t}</option>`).join('')}</select></label>${btn('Tính lại chi phí', 'id="tm-restyle"')}</div><p class="api-meta">Đổi ngày sẽ dời cả chuyến; dự báo thời tiết cũ bị bỏ. “Xếp lại tự động” dùng luật: ưu tiên bữa trưa, tránh ngoài trời khi mưa, không lặp địa điểm.</p></section>
          ${days.map((d, di) => `<section class="api-card"><h3>Ngày ${di + 1} · ${esc(fmtDate(d.date))}</h3>${d.activities.map((a, ai) => `<div class="tm-row tm-edit-row"><input type="time" value="${time(a.start_minute)}" data-day="${di}" data-act="${ai}" data-k="start_minute" aria-label="Giờ bắt đầu"> → <input type="time" value="${time(a.end_minute)}" data-day="${di}" data-act="${ai}" data-k="end_minute" aria-label="Giờ kết thúc"> <strong>${esc(places.get(a.place_id)?.name || a.place_id)}</strong> ${btn('Bỏ', `data-remove="${di}:${ai}" aria-label="Bỏ ${esc(places.get(a.place_id)?.name || '')} khỏi ngày ${di + 1}"`, 'button outline tm-small')}</div>`).join('')}
            <div class="tm-row"><select data-add-day="${di}" aria-label="Thêm địa điểm yêu thích"><option value="">+ Thêm địa điểm yêu thích…</option>${favs.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></div></section>`).join('')}
          <section class="api-card"><h3>Chi phí bạn tự nhập</h3><p class="api-meta">Ví dụ tiền khách sạn đã đặt, ngân sách ăn uống, vé xe. Các khoản này được cộng vào chi phí đã biết và ghi rõ “do bạn nhập”.</p><div id="tm-costs">${costRows()}</div>${btn('+ Thêm khoản chi', 'id="tm-cost-add"')}</section>
          ${favs.length ? '' : `<p class="tm-note">Muốn thêm địa điểm vào lịch? Bấm trái tim ở trang địa điểm để đưa vào <a href="?view=favorites">Yêu thích</a>, rồi quay lại đây.</p>`}
          <div class="tm-row tm-edit-save"><button class="button dark" id="tm-save-edit">Lưu thay đổi</button><a class="button outline" href="?view=saved">Huỷ</a></div>${status('tm-edit-status')}
          <p class="api-meta">Mỗi ngày cần ít nhất một hoạt động; giờ không được chồng nhau. Khi lưu, chi phí được tính lại và lịch được tự kiểm tra (bữa trưa, ngày mưa, lặp địa điểm).</p></div>`;
      };
      draw();
      main.addEventListener('input', e => {
        const t = e.target;
        if (t.dataset.cost !== undefined) costs[t.dataset.cost][t.dataset.ck] = t.dataset.ck === 'amount_vnd' ? Number(t.value) : t.value;
      });
      const replaceWith = async body => {
        const out = main.querySelector('#tm-edit-status');
        try { const saved = await patch(`/api/v1/me/trips/${encodeURIComponent(id)}`, body); say(out, 'Đã lưu. Đang mở lịch trình…', true); setTimeout(() => openTrip(saved), 600); }
        catch (err) { say(out, err.message); }
      };
      main.addEventListener('change', e => {
        const t = e.target;
        if (t.dataset.k) days[t.dataset.day].activities[t.dataset.act][t.dataset.k] = toMin(t.value);
        if (t.dataset.addDay !== undefined && t.value) {
          const d = days[t.dataset.addDay], last = Math.max(540, ...d.activities.map(a => a.end_minute));
          if (d.activities.some(a => a.place_id === t.value)) { notify('Địa điểm đã có trong ngày này.'); draw(); return; }
          d.activities.push({place_id: t.value, start_minute: Math.min(last, 1320), end_minute: Math.min(last + 90, 1439)});
          if (!trip.result.places.some(p => p.id === t.value)) added.add(t.value);
          draw();
        }
      });
      main.addEventListener('click', async e => {
        if (e.target.id === 'tm-cost-add') { costs.push({category: 'lodging', label: '', amount_vnd: 0}); draw(); return; }
        if (e.target.dataset.costRemove !== undefined) { costs.splice(Number(e.target.dataset.costRemove), 1); draw(); return; }
        if (e.target.id === 'tm-move-dates') { const v = main.querySelector('#tm-new-start').value; if (v && v !== trip.request.start_date) replaceWith({start_date: v}); return; }
        if (e.target.id === 'tm-restyle') { replaceWith({travel_style: main.querySelector('#tm-style').value}); return; }
        if (e.target.id === 'tm-auto-arrange') { if (await dialog({title: 'Xếp lại toàn bộ lịch tự động?', text: 'Thay đổi chưa lưu trên trang này sẽ mất.', ok: 'Xếp lại'})) replaceWith({auto_arrange: true}); return; }
        if (e.target.dataset.remove) { const [di, ai] = e.target.dataset.remove.split(':').map(Number); days[di].activities.splice(ai, 1); draw(); }
        if (e.target.id === 'tm-save-edit') {
          const out = main.querySelector('#tm-edit-status');
          if (days.some(d => !d.activities.length)) { say(out, 'Mỗi ngày cần ít nhất một hoạt động.'); return; }
          if (costs.some(c => !c.label.trim() || !(c.amount_vnd > 0))) { say(out, 'Mỗi khoản chi cần tên và số tiền lớn hơn 0.'); return; }
          try {
            const usedAdded = [...added].filter(pid => days.some(d => d.activities.some(a => a.place_id === pid)));
            const saved = await patch(`/api/v1/me/trips/${encodeURIComponent(id)}`, {title: main.querySelector('#tm-title').value.trim() || trip.title, draft: {days}, added_place_ids: usedAdded, user_costs: costs.map(c => ({...c, label: c.label.trim()}))});
            say(out, 'Đã lưu. Đang mở lịch trình…', true);
            setTimeout(() => openTrip(saved), 600);
          } catch (err) { say(out, err.message); }
        }
      });
    }).catch(err => render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-alert"></use></svg>', 'Không mở được chuyến đi.', esc(err.message), tm.link('saved', 'Chuyến đi của tôi', 'button dark'))));
  }

  // --- admin -------------------------------------------------------------------------------
  const adminTabs = current => `<div class="tm-tabs">${[['admin', 'Tổng quan'], ['admin-users', 'Người dùng'], ['admin-places', 'Địa điểm'], ['moderation', 'Kiểm duyệt'], ['admin-messages', 'Liên hệ']].map(([v, t]) => `<a class="button outline ${v === current ? 'active' : ''}" href="?view=${v}">${t}</a>`).join('')}</div>`;
  const adminOnly = () => { if (needLogin()) return false; if (user().role !== 'admin') { render(emptyState('<svg class="tm-i" aria-hidden="true"><use href="#i-lock"></use></svg>', 'Chỉ dành cho quản trị viên.', 'Tài khoản của bạn không có quyền vào khu vực này.', tm.link('home', 'Về trang chủ', 'button dark'))); return false; } return true; };
  const actionLabel = a => ({signup: 'Đăng ký', change_password: 'Đổi mật khẩu', delete_account: 'Xoá tài khoản', reset_requested: 'Tạo link đặt lại', reset_password: 'Đặt lại mật khẩu', hide_place: 'Ẩn địa điểm', show_place: 'Hiện địa điểm', note_place: 'Ghi chú địa điểm'}[a] || a.replace('set_role:', 'Đổi quyền: ').replace('set_status:', 'Trạng thái: ').replace('moderate:', 'Kiểm duyệt: '));

  if (route === 'admin' && adminOnly()) {
    const main = render(`<div class="tm-head tm-admin-head"><div class="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Tổng quan hệ thống.</h1></div>${adminTabs('admin')}<div id="tm-stats">Đang tải…</div>`);
    get('/api/v1/admin/stats').then(s => {
      const cards = [['Người dùng', s.users, 'admin-users'], ['Quản trị viên', s.admins, 'admin-users'], ['Tài khoản bị khoá', s.locked_users, 'admin-users'], ['Chuyến đi đã lưu', s.trips, null], ['Địa điểm đã ghi nhận', s.places, 'admin-places'], ['Địa điểm đang ẩn', s.hidden_places, 'admin-places'], ['Đánh giá', s.reviews, 'moderation'], ['Chờ duyệt', s.pending_reviews, 'moderation'], ['Báo cáo chưa xử lý', s.open_reports, 'moderation'], ['Tin nhắn liên hệ mới', s.new_messages, 'admin-messages']];
      main.querySelector('#tm-stats').innerHTML = `<div class="tm-stats">${cards.map(([t, n, v]) => `<div class="api-card"><strong>${n}</strong>${v ? `<a href="?view=${v}">${t}</a>` : t}</div>`).join('')}</div>
        <h2>Hoạt động gần đây</h2><div class="tm-table-wrap"><table class="tm-table"><tr><th>Thời gian</th><th>Người thực hiện</th><th>Hành động</th></tr>${s.recent.map(r => `<tr><td>${date(r.at)}</td><td>${esc(r.actor || '—')}</td><td>${esc(actionLabel(r.action))}</td></tr>`).join('') || '<tr><td colspan="3">Chưa có hoạt động.</td></tr>'}</table></div>`;
    }).catch(err => { main.querySelector('#tm-stats').textContent = err.message; });
  }

  if (route === 'admin-users' && adminOnly()) {
    const main = render(`<div class="tm-head tm-admin-head"><div class="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Người dùng.</h1></div>${adminTabs('admin-users')}<form class="tm-row tm-filter" id="tm-user-search"><input name="q" placeholder="Tìm theo tên hoặc email" maxlength="100" aria-label="Tìm người dùng"><button class="button dark">Tìm</button></form>${status('tm-users-status')}<div id="tm-users">Đang tải…</div>`);
    const box = main.querySelector('#tm-users'), out = main.querySelector('#tm-users-status');
    let q = '';
    const load = () => get(`/api/v1/admin/users?q=${encodeURIComponent(q)}`).then(list => {
      box.innerHTML = `<div class="tm-table-wrap"><table class="tm-table"><tr><th>Người dùng</th><th>Quyền</th><th>Trạng thái</th><th>Chuyến đi</th><th>Đánh giá</th><th>Đăng nhập gần nhất</th><th></th></tr>${list.map(u => `<tr><td><strong>${esc(u.name)}</strong><br><span class="api-meta">${esc(u.email)}</span></td>
        <td><select data-role="${esc(u.id)}"><option value="user" ${u.role === 'user' ? 'selected' : ''}>Thành viên</option><option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Quản trị</option></select></td>
        <td><span class="tm-badge ${u.status === 'locked' ? 'rejected' : 'approved'}">${u.status === 'locked' ? 'Đã khoá' : 'Hoạt động'}</span></td><td>${u.trip_count}</td><td>${u.review_count}</td><td>${date(u.last_login)}</td>
        <td class="tm-row">${btn(u.status === 'locked' ? 'Mở khoá' : 'Khoá', `data-status="${esc(u.id)}" data-to="${u.status === 'locked' ? 'active' : 'locked'}"`, 'button outline tm-small')}${btn('Link đặt lại mật khẩu', `data-reset="${esc(u.id)}"`, 'button outline tm-small')}</td></tr>`).join('')}</table></div>`;
    }).catch(err => { box.textContent = err.message; });
    main.querySelector('#tm-user-search').onsubmit = e => { e.preventDefault(); q = new FormData(e.target).get('q'); load(); };
    box.addEventListener('change', async e => { const id = e.target.dataset.role; if (!id) return; try { await patch(`/api/v1/admin/users/${id}`, {role: e.target.value}); say(out, 'Đã đổi quyền.', true); } catch (err) { say(out, err.message); } load(); });
    box.addEventListener('click', async e => {
      const t = e.target;
      try {
        if (t.dataset.status) { await patch(`/api/v1/admin/users/${t.dataset.status}`, {status: t.dataset.to}); say(out, t.dataset.to === 'locked' ? 'Đã khoá tài khoản và đăng xuất mọi thiết bị.' : 'Đã mở khoá.', true); load(); }
        if (t.dataset.reset) { const r = await api(`/api/v1/admin/users/${t.dataset.reset}/reset-link`, {}); out.style.color = '#1b6e3a'; out.innerHTML = `Gửi link này cho người dùng (hiệu lực ${r.expires_in_minutes} phút): <input readonly value="${esc(r.link)}" style="width:100%" onclick="this.select()">`; }
      } catch (err) { say(out, err.message); }
    });
    load();
  }

  if (route === 'admin-places' && adminOnly()) {
    const main = render(`<div class="tm-head tm-admin-head"><div class="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Địa điểm.</h1></div><p>Địa điểm được ghi nhận khi xuất hiện trong tìm kiếm, lịch trình hoặc Trợ lý AI. Ẩn một địa điểm sẽ loại nó khỏi kết quả tìm kiếm, Trợ lý AI, yêu thích và trang chi tiết.</p>${adminTabs('admin-places')}
      <form class="tm-row tm-filter" id="tm-place-search"><input name="q" placeholder="Tìm theo tên hoặc địa chỉ" maxlength="100" aria-label="Tìm địa điểm"><select name="hidden" aria-label="Trạng thái hiển thị"><option value="">Tất cả</option><option value="false">Đang hiện</option><option value="true">Đang ẩn</option></select><button class="button dark">Lọc</button></form>${status('tm-places-status')}<div id="tm-places">Đang tải…</div>`);
    const box = main.querySelector('#tm-places'), out = main.querySelector('#tm-places-status');
    let filter = '';
    const load = () => get(`/api/v1/admin/places?${filter}`).then(list => {
      box.innerHTML = `<div class="tm-table-wrap"><table class="tm-table"><tr><th>Địa điểm</th><th>Loại</th><th>Đánh giá</th><th>Yêu thích</th><th>Ghi chú hiển thị</th><th></th></tr>${list.map(r => `<tr><td><a href="?view=place&id=${encodeURIComponent(r.place.id)}">${esc(r.place.name)}</a><br><span class="api-meta">${esc(r.place.address || '')}</span></td><td>${esc(kind(r.place))}</td><td>${r.review_count}</td><td>${r.favorite_count}</td>
        <td><textarea data-note="${esc(r.place.id)}" rows="2" maxlength="500" placeholder="Ví dụ: đang trùng tu đến 12/2026">${esc(r.admin_note)}</textarea></td>
        <td class="tm-row"><span class="tm-badge ${r.hidden ? 'hidden' : 'approved'}">${r.hidden ? 'Đang ẩn' : 'Đang hiện'}</span>${btn(r.hidden ? 'Hiện lại' : 'Ẩn', `data-hide="${esc(r.place.id)}" data-to="${!r.hidden}"`, 'button outline tm-small')}</td></tr>`).join('') || '<tr><td colspan="6">Chưa có địa điểm nào.</td></tr>'}</table></div>`;
    }).catch(err => { box.textContent = err.message; });
    main.querySelector('#tm-place-search').onsubmit = e => { e.preventDefault(); const f = new FormData(e.target); filter = new URLSearchParams([...f].filter(([, v]) => v)).toString(); load(); };
    box.addEventListener('click', async e => { const id = e.target.dataset.hide; if (!id) return; try { await patch(`/api/v1/admin/places/${encodeURIComponent(id)}`, {hidden: e.target.dataset.to === 'true'}); say(out, 'Đã cập nhật.', true); load(); } catch (err) { say(out, err.message); } });
    box.addEventListener('change', async e => { const id = e.target.dataset.note; if (!id) return; try { await patch(`/api/v1/admin/places/${encodeURIComponent(id)}`, {admin_note: e.target.value}); say(out, 'Đã lưu ghi chú.', true); } catch (err) { say(out, err.message); } });
    load();
  }

  if (route === 'moderation' && adminOnly()) {
    const main = render(`<div class="tm-head tm-admin-head"><div class="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Kiểm duyệt.</h1></div>${adminTabs('moderation')}${status('tm-mod-status')}<div id="tm-mod">Đang tải…</div>`);
    const box = main.querySelector('#tm-mod'), out = main.querySelector('#tm-mod-status');
    const item = (r, reported) => `<article class="api-card"><div class="tm-row"><strong>${esc(r.place_name)}</strong><span class="tm-stars">${starText(r.rating)}</span><span class="tm-badge ${r.status}">${statusLabel[r.status]}</span>${reported ? `<span class="tm-badge rejected">${r.report_count} báo cáo</span>` : ''}</div>
      <p>${esc(r.text)}</p><p class="api-meta">${esc(r.author)} · ${esc(r.author_email)} · ${date(r.updated_at)}</p>${reported ? `<p class="api-meta">Lý do: ${esc(r.reasons)}</p>` : ''}
      <input data-note-for="${esc(r.id)}" placeholder="Ghi chú cho người viết (tuỳ chọn)" maxlength="300" style="width:100%">
      <div class="tm-row">${btn(reported ? 'Giữ lại' : 'Duyệt', `data-mod="${esc(r.id)}" data-action="approve"`, 'button dark')}${reported ? btn('Ẩn đánh giá', `data-mod="${esc(r.id)}" data-action="hide"`) : btn('Từ chối', `data-mod="${esc(r.id)}" data-action="reject"`)}</div></article>`;
    const load = () => get('/api/v1/admin/moderation').then(q => {
      box.innerHTML = `<h2>Đánh giá chờ duyệt (${q.pending.length})</h2>${q.pending.map(r => item(r, false)).join('') || '<p>Không có đánh giá chờ duyệt.</p>'}
        <h2>Đánh giá bị báo cáo (${q.reported.length})</h2>${q.reported.map(r => item(r, true)).join('') || '<p>Không có báo cáo chưa xử lý.</p>'}`;
    }).catch(err => { box.textContent = err.message; });
    box.addEventListener('click', async e => {
      const id = e.target.dataset.mod; if (!id) return;
      const note = box.querySelector(`[data-note-for="${CSS.escape(id)}"]`)?.value || '';
      try { await api(`/api/v1/admin/reviews/${id}/moderate`, {action: e.target.dataset.action, note}); say(out, 'Đã xử lý.', true); load(); } catch (err) { say(out, err.message); }
    });
    load();
  }
})();
