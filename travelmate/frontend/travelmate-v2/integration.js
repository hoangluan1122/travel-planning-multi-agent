/* Same-origin API integration. Provider credentials never enter the browser. */
(() => {
  'use strict';
  const params = new URLSearchParams(location.search);
  const route = params.get('view') || 'home';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => Number(value).toLocaleString('vi-VN') + ' ₫';
  const time = value => `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;
  const wmo = code => code==null?null:code===0?'☀️ Trời quang':code<=2?'🌤️ Ít mây':code===3?'☁️ Nhiều mây':code<=48?'🌫️ Sương mù':code<=57?'🌦️ Mưa phùn':code<=67?'🌧️ Mưa':code<=77?'❄️ Tuyết':code<=82?'🌧️ Mưa rào':code<=86?'❄️ Mưa tuyết':'⛈️ Dông';
  const kinds = {museum:'Bảo tàng',tomb:'Lăng tẩm',temple:'Đền cổ',archaeological_site:'Di tích khảo cổ',castle:'Thành / cung điện',monument:'Tượng đài',memorial:'Đài tưởng niệm',gallery:'Phòng trưng bày',attraction:'Điểm tham quan',viewpoint:'Điểm ngắm cảnh',park:'Công viên',beach:'Bãi biển',restaurant:'Nhà hàng',cafe:'Quán cà phê',fast_food:'Đồ ăn nhanh',food_court:'Khu ẩm thực',hotel:'Khách sạn'};
  const kind = p => (p?.types||[]).map(t=>kinds[t]).find(Boolean)||'';
  const mapLink = p => p&&Number.isFinite(p.latitude)?`<a href="https://www.openstreetmap.org/?mlat=${p.latitude}&mlon=${p.longitude}#map=17/${p.latitude}/${p.longitude}" target="_blank" rel="noopener noreferrer">Xem trên bản đồ ↗</a>`:'';
  const levels = {free:'Miễn phí',inexpensive:'₫ · bình dân',moderate:'₫₫ · vừa phải',expensive:'₫₫₫ · cao',very_expensive:'₫₫₫₫ · rất cao'};
  const safeUrl = u => /^(https:\/\/|\/api\/v1\/places\/photo\?)/.test(u||'') ? u : '';
  const photo = (p, cls='api-photo') => p?.photo && safeUrl(p.photo.url) ? `<figure class="${cls}"><img src="${esc(safeUrl(p.photo.url))}" alt="${esc(p.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('figure').remove()"><figcaption>${p.photo.source_url&&/^https:\/\//.test(p.photo.source_url)?`<a href="${esc(p.photo.source_url)}" target="_blank" rel="noopener noreferrer">${esc(p.photo.attribution)}</a>`:esc(p.photo.attribution)}</figcaption></figure>` : '';
  const vnd = v => Number(v).toLocaleString('vi-VN') + ' ₫';
  const price = p => {
    if (p?.estimated_visit_cost_vnd != null) return `Giá tham khảo: ${vnd(p.estimated_visit_cost_vnd)}`;
    const t = p?.ticket;
    if (t) return `${t.label}: ${t.adult_vnd != null ? (Number(t.adult_vnd) === 0 ? 'miễn phí' : vnd(t.adult_vnd) + '/người lớn') : `${vnd(t.low_vnd ?? t.high_vnd)} – ${vnd(t.high_vnd ?? t.low_vnd)}`}${t.note ? ' · ' + t.note : ''}`;
    const r = p?.price_range, lo = r?.low_vnd, hi = r?.high_vnd;
    const range = lo != null || hi != null ? (lo != null && hi != null ? `${vnd(lo)} – ${vnd(hi)}` : vnd(lo ?? hi)) + '/người' : '';
    const level = p?.price_level ? levels[p.price_level] : '';
    return range || level ? `Giá: ${[range, level].filter(Boolean).join(' · ')}` : 'Chưa có giá tham khảo';
  };
  const ticketSource = p => p?.ticket?.sources?.length ? `<p class="api-meta">Nguồn giá vé: ${p.ticket.sources.filter(u=>/^https:\/\//.test(u)).map(u=>`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(new URL(u).hostname.replace(/^www\./,''))}</a>`).join(', ')} · kiểm tra ${esc(p.ticket.checked)} · giá có thể thay đổi</p>` : '';
  const stars = p => p?.rating != null ? `<span class="api-rating">★ ${Number(p.rating).toFixed(1)}${p.rating_count?` (${Number(p.rating_count).toLocaleString('vi-VN')} đánh giá)`:''}</span>` : '';
  const hours = p => p?.opening_hours_raw ? `<details class="api-hours"><summary>Giờ mở cửa</summary><p>${p.opening_hours_raw.split('; ').map(esc).join('<br>')}</p></details>` : '';
  const placeLinks = p => [p?.maps_url&&/^https:\/\//.test(p.maps_url)?`<a href="${esc(p.maps_url)}" target="_blank" rel="noopener noreferrer">Google Maps ↗</a>`:mapLink(p), p?.website_url&&/^https:\/\//.test(p.website_url)?`<a href="${esc(p.website_url)}" target="_blank" rel="noopener noreferrer">Website ↗</a>`:''].filter(Boolean).join(' · ');
  const nextDay = d => {const x=new Date(d+'T00:00:00Z');x.setUTCDate(x.getUTCDate()+1);return x.toISOString().slice(0,10)};
  const bookingLink = (p, request) => `https://www.booking.com/searchresults.html?${new URLSearchParams({ss:`${p.name}, ${request.destination}`,checkin:request.start_date,checkout:nextDay(request.end_date),group_adults:String(request.travelers),no_rooms:'1',lang:'vi'})}`;
  const stays = (items, request) => items?.length ? `<h2>Nơi ở gợi ý</h2><p class="api-meta">Giá phòng theo đêm chưa có từ nguồn dữ liệu; bấm “Xem giá phòng” để xem giá thật cho đúng ngày và số người.</p><div class="api-grid">${items.map(p=>`<article class="api-card">${photo(p)}<h3>${esc(p.name)}</h3>${stars(p)}<p>${esc(p.address||'')}</p><p>${esc(price(p))}</p><p>${placeLinks(p)} · <a href="${esc(bookingLink(p, request))}" target="_blank" rel="noopener noreferrer">Xem giá phòng ↗</a></p></article>`).join('')}</div>` : '';
  const agentLabels = {places:'Tìm địa điểm chung',place_search:'Tìm theo nhu cầu',weather:'Thời tiết',recommendation:'Xếp hạng',itinerary:'Xếp lịch',budget:'Chi phí'};
  const outcomeLabels = {ok:'tìm thấy',no_results:'không thấy',failed:'lỗi nguồn'};
  const planningTrace = t => !t ? '' : `<details class="api-card"><summary><strong>Agent đã lên kế hoạch thế nào</strong> · ${t.planner==='llm'?'Planning Agent (LLM)':'kế hoạch mặc định'} · ${t.rounds.length} vòng</summary>${t.rounds.map(r=>`<h4>Vòng ${r.round}</h4>${r.note?`<p class="api-meta">${esc(r.note)}</p>`:''}<ol>${r.plan.subtasks.map(s=>{const o=r.observations.find(x=>x.subtask_id===s.id);return `<li><strong>${esc(agentLabels[s.agent]||s.agent)}</strong>${s.inputs?.keyword?` · ${esc(s.inputs.category||'')} “${esc(s.inputs.keyword)}”`:''} — ${esc(s.goal)}${o?` <em>(${esc(outcomeLabels[o.outcome]||o.outcome)}${o.count?`, ${o.count} nơi`:''})</em>`:''}</li>`}).join('')}</ol>`).join('')}${t.rounds.length>1?'<p class="api-meta">Vòng sau được lập lại vì có lượt tìm không ra kết quả.</p>':''}</details>`;
  const selfCheck = r => { if(!r) return ''; const chosen = r.rounds.find(x=>x.round===r.chosen_round) || r.rounds[r.rounds.length-1]; const failed = chosen.checks.filter(c=>!c.passed).length; return `<details class="api-card"${failed?' open':''}><summary><strong>Agent tự kiểm tra</strong> · ${failed?`còn ${failed} điểm chưa đạt`:'đạt mọi tiêu chí'}${r.revisions?` · đã tự sửa ${r.revisions} lần`:''}</summary><ul>${chosen.checks.map(c=>`<li>${c.passed?'✅':'⚠️'} <strong>${esc(c.label)}</strong> — ${esc(c.detail)}</li>`).join('')||'<li>Không có tiêu chí nào áp dụng cho chuyến này.</li>'}</ul>${r.rounds.length>1?`<p class="api-meta">Đã kiểm tra ${r.rounds.length} bản nháp; hiển thị bản ${r.chosen_round} (ít lỗi nhất). ${r.rounds.map(x=>`Bản ${x.round}: ${x.checks.filter(c=>!c.passed).length} lỗi`).join(' · ')}.</p>`:''}</details>`; };
  const read = (key, fallback) => {try {return JSON.parse(sessionStorage.getItem(key)) ?? fallback} catch {return fallback}};
  const save = (key, value) => sessionStorage.setItem(key, JSON.stringify(value));
  const link = (view, text, cls = 'button outline') => `<a class="${cls}" href="?view=${view}">${text}</a>`;
  const fmtDate = d => d ? new Date(d + 'T00:00:00').toLocaleDateString('vi-VN', {weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric'}) : '';
  const dateRange = (a, b) => a === b ? fmtDate(a) : `${fmtDate(a)} → ${fmtDate(b)}`;
  const dev = params.has('dev') || (() => {try {return !!localStorage.getItem('tm-dev')} catch {return false}})();
  // One look for every "nothing here yet" and "sign in first" screen.
  const emptyState = (icon, title, text, actions = '') => `<div class="tm-empty"><span class="tm-empty-ico" aria-hidden="true">${icon}</span><h2>${title}</h2><p>${text}</p>${actions ? `<div class="api-actions">${actions}</div>` : ''}</div>`;
  const head = (eyebrow, title, text = '', actions = '') => `<div class="tm-head"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${text ? `<p>${text}</p>` : ''}${actions ? `<div class="api-actions">${actions}</div>` : ''}</div>`;
  // In-page replacements for confirm()/prompt()/alert(): resolves to true, the typed text, or null when cancelled.
  const dialog = ({title, text = '', input = null, ok = 'Đồng ý', danger = false}) => new Promise(resolve => {
    const d = document.createElement('dialog');
    d.className = 'tm-dialog';
    d.innerHTML = `<form method="dialog"><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ''}${input ? `<label class="field">${esc(input.label)}<input name="value" value="${esc(input.value || '')}" maxlength="${input.max || 120}" required autocomplete="off"></label>` : ''}<div class="tm-row"><button class="button ${danger ? 'danger' : 'dark'}" value="ok">${esc(ok)}</button><button class="button outline" value="cancel" formnovalidate>Huỷ</button></div></form>`;
    document.body.append(d);
    d.addEventListener('close', () => {const value = d.returnValue === 'ok' ? (input ? d.querySelector('input').value.trim() : true) : null; d.remove(); resolve(value)});
    d.showModal();
  });
  const notify = text => window.tmToast ? window.tmToast(text) : alert(text);
  const loginGate = (text, next = location.search) => emptyState('🔐', 'Đăng nhập để tiếp tục.', text, link('login&next=' + encodeURIComponent(next), 'Đăng nhập', 'button dark') + link('signup&next=' + encodeURIComponent(next), 'Tạo tài khoản'));
  const style = document.createElement('style');
  style.textContent = '.api-photo{margin:-24px -24px 16px;overflow:hidden;border-radius:20px 20px 0 0}.api-photo img{display:block;width:100%;height:220px;object-fit:cover}.api-photo figcaption{font-size:11px;color:#667;padding:6px 24px 0}.api-thumb{margin:-24px -24px 12px;overflow:hidden;border-radius:20px 20px 0 0}.api-thumb img{display:block;width:100%;height:140px;object-fit:cover}.api-thumb figcaption{display:none}.api-rating{color:#b26a00;font-weight:600}.api-hours summary{cursor:pointer}.api-banner{padding:12px 5%;background:#eef1ff;font-size:13px}.api-banner input{max-width:240px;padding:8px}.api-card{padding:24px;margin:16px 0;border:1px solid #e1e5ee;border-radius:20px;background:white;overflow-wrap:anywhere}.api-actions{display:flex;gap:12px;flex-wrap:wrap}.api-warning{padding:16px;background:#fff5dc;border-radius:12px;margin:12px 0}.api-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:16px}.api-error{color:#a32424}.api-card h3{margin:12px 0}.api-card p{margin:12px 0}.api-meta{color:#647084;font-size:13px}.api-banner summary{cursor:pointer}';
  style.textContent += '.chat-log{display:flex;flex-direction:column;gap:12px;max-height:60vh;overflow:auto;padding:8px 0;margin:16px 0}.chat-msg{max-width:min(760px,92%);padding:14px 18px;border-radius:18px}.chat-msg p{margin:4px 0}.chat-msg.user{align-self:flex-end;background:#16302b;color:#fff}.chat-msg.bot{align-self:flex-start;background:#f3f1ea}.chat-agent{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;background:#16302b;color:#fff;border-radius:999px;padding:3px 10px;margin-bottom:4px}.chat-form{display:flex;gap:8px}.chat-form input{flex:1;padding:12px 16px;border-radius:999px;border:1px solid #ccc;font:inherit}.chat-places{margin-top:10px}.chat-place h4{margin:4px 0}';
  style.textContent += '.tm-verdict{padding:10px 14px;border-radius:12px;font-weight:600}.tm-bar{position:relative;display:flex;height:18px;border-radius:9px;background:#eef0f4;overflow:visible;margin:16px 0}.tm-bar span{display:block;height:100%}.tm-bar span:first-child{border-radius:9px 0 0 9px}.tm-bar b{position:absolute;top:-5px;bottom:-5px;width:2px;background:#111}.tm-budget-table{width:100%;border-collapse:collapse;font-size:14px}.tm-budget-table td{padding:8px 6px;border-top:1px solid #eef0f4;vertical-align:top}.tm-budget-table td:nth-child(2){white-space:nowrap;font-weight:600}.tm-budget-table i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px}';
  document.head.append(style);
  const banner = document.createElement('div');
  banner.className = 'api-banner';
  banner.innerHTML = '<span id="api-health" role="status"></span><details><summary>Cấu hình kết nối</summary><label>Token truy cập backend (nếu được yêu cầu) <input type="password" id="api-token" autocomplete="off"></label><button id="token-save" type="button">Áp dụng</button><small> Token được lưu trên trình duyệt này (mọi tab). Dán đúng giá trị TRAVELMATE_API_TOKEN, không nhập API key Gemini tại đây.</small></details>';
  banner.hidden = true;
  document.querySelector('header').after(banner);
  banner.querySelector('details').hidden = !dev;
  // Accept a pasted .env line or a quoted value; keep the token for every tab on this browser.
  const cleanToken = value => value.trim().replace(/^TRAVELMATE_API_TOKEN\s*=\s*/i,'').replace(/^["']+|["']+$/g,'').trim();
  const readToken = () => {try {return JSON.parse(localStorage.getItem('tm-token')) || read('tm-token','')} catch {return read('tm-token','')}};
  const tokenInput = document.querySelector('#api-token');
  tokenInput.value = readToken();
  const applyToken = () => {
    const token = cleanToken(tokenInput.value);
    tokenInput.value = token;
    try {localStorage.setItem('tm-token', JSON.stringify(token))} catch {}
    save('tm-token', token);
    document.querySelector('#api-health').textContent = token ? `Đã lưu token (${token.length} ký tự). Bạn có thể thử lại yêu cầu.` : 'Đã xoá token.';
  };
  document.querySelector('#token-save').onclick = applyToken;
  tokenInput.addEventListener('change', applyToken);
  tokenInput.addEventListener('keydown', e => {if(e.key==='Enter'){e.preventDefault();applyToken()}});
  const credit = document.querySelector('#tm-credit');
  const health = fetch('/health').then(r => {if (!r.ok) throw Error(); return r.json()}).then(h => {
    banner.hidden = h.mode !== 'demo' && !dev;
    document.querySelector('#api-health').textContent = h.mode === 'demo' ? 'Chế độ demo: dữ liệu giả lập, không phải địa điểm thật.'
      : `Backend đã kết nối · ${h.place_provider === 'open_data' ? 'OpenStreetMap + Open-Meteo' : 'Google Places'} · ${(h.agent_engine || 'adk').toUpperCase()}${h.token_required ? ' · yêu cầu đăng nhập hoặc token' : ''}`;
    if (credit && h.mode === 'demo') credit.textContent = 'Chế độ demo: địa điểm và thời tiết là dữ liệu giả lập.';
    else if (credit && h.place_provider !== 'open_data') credit.textContent = 'Dữ liệu địa điểm: Google Places.';
    return h;
  }).catch(() => {banner.hidden = false; document.querySelector('#api-health').textContent = 'Không kết nối được máy chủ TravelMate. Hãy thử tải lại trang sau ít phút.'; return null});
  // True when the server only answers signed-in users and this visitor is not signed in.
  const needsLogin = async () => {const h = await health; return !!(h && h.token_required && !session()?.user && !readToken())};

  // The session token lives in an HttpOnly cookie the page cannot read; only the profile is kept here.
  const session = () => {try {const s=JSON.parse(localStorage.getItem('tm-session'));if(s?.token){delete s.token;localStorage.setItem('tm-session',JSON.stringify(s))}return s?.user?s:null} catch {return null}};
  async function api(path, data, signal, method='POST') {
    const headers = {'Content-Type':'application/json','X-Requested-With':'travelmate'};
    // A signed-in user's session unlocks the API; otherwise the operator token, if any.
    const token = readToken();  // operator token, if any; the signed-in session rides on the cookie
    if(token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path,{method,headers,body:method==='GET'||method==='DELETE'?undefined:JSON.stringify(data??{}),signal});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) {
      if(response.status===401){
        if(path.startsWith('/api/v1/auth/'))throw Error(body.detail||'Email hoặc mật khẩu không đúng.');
        const expired=!!session()?.user;
        if(expired)localStorage.removeItem('tm-session');
        if(dev){banner.hidden=false;banner.querySelector('details').open=true}
        throw Object.assign(Error(expired?'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.':'Bạn cần đăng nhập để dùng chức năng này.'),{auth:true});
      }
      if(response.status===422) throw Error('Thông tin chưa hợp lệ: '+(Array.isArray(body.detail)?body.detail.map(e=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; '):'Kiểm tra lại biểu mẫu.'));
      throw Error(response.status===504?'Quá thời gian xử lý. Vui lòng thử lại.':body.detail || `Máy chủ báo lỗi ${response.status}. Vui lòng thử lại.`);
    }
    return body;
  }
  function render(content) {
    document.querySelectorAll('main.view').forEach(e=>e.classList.remove('visible'));
    let main=document.querySelector('#connected-view');
    if(!main){main=document.createElement('main');main.id='connected-view';const footer=document.querySelector('.tm-footer');footer?footer.before(main):document.body.append(main)}
    main.className='view visible expanded-view';main.innerHTML=`<div class="page-shell">${content}</div>`;
    const title=window.travelmateRoutes?.[route];if(title)document.title=`${title} — TravelMate`;
    return main;
  }
  const records = () => read('tm-plans',[]);
  const current = () => records().find(p=>p.result.request_id===(params.get('id')||read('tm-current','')));
  window.tm = {api, render, esc, money, time, wmo, kind, photo, price, stars, hours, placeLinks, ticketSource, mapLink, link, read, save, records, session, route, params, fmtDate, dateRange, emptyState, head, loginGate, needsLogin, health, dialog, notify};
  const warnings = items => items.length?`<div class="api-warning"><strong>Thông tin cần lưu ý</strong><ul>${[...new Set(items)].map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:'';
  const budgetLegacy = b => `<div class="api-card"><h3>Chi phí đã có dữ liệu: ${money(b.known_subtotal)}</h3><p>${b.status==='incomplete'?'Chưa đủ dữ liệu để kết luận tổng chi phí.':b.status==='over_budget'?'Chi phí đã biết vượt ngân sách.':'Các khoản đã tính nằm trong ngân sách.'}</p>${b.estimated_low_vnd!=null?`<p><strong>Ước tính theo khoảng giá nguồn: ${money(b.estimated_low_vnd)} – ${money(b.estimated_high_vnd)}</strong> (chưa gồm các khoản bên dưới)</p><details${(b.estimate_basis||[]).some(x=>x.includes('do bạn nhập'))?' open':''}><summary>Cách tính</summary><ul>${b.estimate_basis.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:(b.estimate_basis||[]).length?`<details${b.estimate_basis.some(x=>x.includes('do bạn nhập'))?' open':''}><summary>Đã tính gồm</summary><ul>${b.estimate_basis.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:''}${b.unknown_items.length?`<p>Chưa tính được: ${b.unknown_items.map(esc).join(', ')}. Không coi các khoản này là 0.</p>`:''}</div>`;
  // Whole-trip estimate from the budget agent: a stacked bar per category against the budget.
  const styles = {budget: 'Tiết kiệm', mid: 'Vừa phải', high: 'Cao cấp'};
  const colors = {tickets: '#16302b', places: '#7a8f6a', lodging: '#c0703a', food: '#d9a441', transport: '#5b7fa6', other: '#8c6bb1'};
  const costKinds = {sourced: 'có nguồn', reference: 'giá tham khảo', user: 'do bạn nhập'};
  const span = (lo, hi) => Number(lo) === Number(hi) ? money(lo) : `${money(lo)} – ${money(hi)}`;
  const budget = b => {
    if (!b.lines || !b.lines.length || b.verdict === 'unknown' || b.total_high_vnd == null) return budgetLegacy(b);
    const cap = Number(b.budget_vnd), top = Math.max(cap, Number(b.total_high_vnd)) || 1;
    const verdict = {fits: ['#e3f3e6', '#1f6b35', `Đủ ngân sách: còn dư ít nhất ${money(cap - b.total_high_vnd)}`],
      tight: ['#fff5dc', '#8a5a00', `Sát ngân sách: chi mức cao có thể thiếu tới ${money(b.total_high_vnd - cap)}`],
      over: ['#fde8e8', '#a32424', `Vượt ngân sách: thiếu ít nhất ${money(b.total_low_vnd - cap)}`]}[b.verdict];
    const bar = b.lines.map(l => `<span title="${esc(l.label)}: ${esc(span(l.low_vnd, l.high_vnd))}" style="width:${(Number(l.high_vnd) / top * 100).toFixed(2)}%;background:${colors[l.category] || '#999'}"></span>`).join('');
    const rows = b.lines.map(l => `<tr><td><i style="background:${colors[l.category] || '#999'}"></i>${esc(l.label)}</td><td>${esc(span(l.low_vnd, l.high_vnd))}</td><td class="api-meta">${esc(l.detail)} · ${costKinds[l.kind]}${(l.sources || []).length ? ` · ${l.sources.map((u, k) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">nguồn ${k + 1}</a>`).join(' ')}` : ''}</td></tr>`).join('');
    const tips = (b.savings || []).length ? `<h4>Gợi ý tiết kiệm</h4><ul>${b.savings.map(t => `<li><strong>${esc(t.label)}</strong>: bớt tới ${money(t.saving_vnd)}. ${esc(t.detail)}</li>`).join('')}</ul><p class="api-meta">Chưa áp dụng gợi ý nào. Đổi mức chi tiêu hoặc bỏ điểm trong mục “Sửa lịch trình”.</p>` : '';
    const left = (b.unknown_items || []).filter(x => !x.startsWith('Chi phí tại'));
    return `<div class="api-card tm-budget" id="tm-budget"><h3>Chi phí ước tính: ${esc(span(b.total_low_vnd, b.total_high_vnd))}</h3>
      <p class="tm-verdict" style="background:${verdict[0]};color:${verdict[1]}">${esc(verdict[2])}</p>
      <p class="api-meta">Ngân sách ${money(cap)} · mức ${esc(styles[b.travel_style] || '')} · tối đa khoảng ${money(b.per_person_high_vnd)}/người</p>
      <div class="tm-bar" role="img" aria-label="Chi phí theo khoản so với ngân sách">${bar}<b style="left:${(cap / top * 100).toFixed(2)}%" title="Ngân sách"></b></div>
      <table class="tm-budget-table"><tbody>${rows}</tbody></table>${tips}
      ${left.length ? `<p>Chưa tính được: ${left.map(esc).join(', ')}. Không coi các khoản này là 0.</p>` : ''}
      <p class="api-meta">Lưu trú, ăn uống, đi lại là giá tham khảo từ các nguồn ghi bên trên${b.reference_checked ? ` (kiểm tra ${esc(b.reference_checked)})` : ''}, không phải báo giá. Hỏi Trợ lý AI “nếu ở khách sạn 500k/đêm thì sao” để tính thử.</p></div>`;
  };
  const empty = () => render(emptyState('🗺️', 'Chưa có lịch trình để hiển thị.', 'Tạo một chuyến đi mới, hoặc mở lại chuyến đã lưu trong tài khoản.', link('create', 'Tạo chuyến đi', 'button dark') + link('saved', 'Chuyến đi của tôi')));

  if(route==='create'){
    const form=document.querySelector('[data-form=create]'), el=form.elements, status=form.querySelector('.form-status');
    const previous=read('tm-request',null);
    const iso=d=>{const x=new Date(d);x.setMinutes(x.getMinutes()-x.getTimezoneOffset());return x.toISOString().slice(0,10)};
    const plus=n=>{const x=new Date();x.setDate(x.getDate()+n);return iso(x)};
    const today=plus(0);
    el.start.min=el.end.min=today;el.start.value=plus(1);el.end.value=plus(2);
    if(previous){for(const [name,key] of Object.entries({destination:'destination',start:'start_date',end:'end_date',people:'travelers',budget:'budget_vnd',notes:'notes'}))el[name].value=previous[key]??''}
    if(previous?.travel_style)el.travel_style.value=previous.travel_style;
    if(previous&&Array.isArray(previous.interests))form.querySelectorAll('[name=interests]').forEach(box=>box.checked=previous.interests.includes(box.value));
    // A past date left over from an earlier visit would be rejected: move it forward.
    if(el.start.value<today){el.start.value=plus(1);el.end.value=plus(2)}
    const wanted=(params.get('destination')||'').trim().slice(0,200);
    if(wanted)el.destination.value=wanted;
    const hint=form.querySelector('#tm-budget-hint');
    const showBudget=()=>{const v=Number(el.budget.value),n=Number(el.people.value);if(hint)hint.textContent=v>0?`${money(v)}${n>1?` · khoảng ${money(Math.round(v/n))}/người`:''}`:''};
    el.budget.addEventListener('input',showBudget);el.people.addEventListener('input',showBudget);showBudget();
    el.start.addEventListener('change',()=>{if(el.start.value){el.end.min=el.start.value;if(el.end.value<el.start.value)el.end.value=el.start.value}});
    needsLogin().then(need=>{if(need){const note=document.createElement('p');note.className='tm-note';note.innerHTML=`Bạn cần ${link('login&next=%3Fview%3Dcreate','đăng nhập','')} để lập lịch trình. Cứ điền trước, thông tin sẽ được giữ lại.`;status.before(note)}});
    form.addEventListener('submit',async e=>{
      e.preventDefault();e.stopImmediatePropagation();
      const f=new FormData(form);
      const days=(new Date(f.get('end'))-new Date(f.get('start')))/86400000;
      if(days<0){status.textContent='Ngày kết thúc phải bằng hoặc sau ngày khởi hành.';return}
      if(days>13){status.textContent='Chuyến đi dài tối đa 14 ngày.';return}
      const request={destination:f.get('destination').trim(),start_date:f.get('start'),end_date:f.get('end'),travelers:Number(f.get('people')),budget_vnd:f.get('budget'),interests:f.getAll('interests'),notes:f.get('notes').trim(),travel_style:f.get('travel_style')||'mid'};
      try{save('tm-request',request)}catch{status.textContent='Trình duyệt đang chặn lưu dữ liệu tạm. Hãy tắt chế độ chặn rồi thử lại.';return}
      location.href=await needsLogin()?'?view=login&next='+encodeURIComponent('?view=loading'):'?view=loading';
    },true);
  }
  if(route==='loading'){
    const request=read('tm-request',null);
    if(!request){empty();return}
    const main=render(`<div class="tm-loading"><div class="tm-spinner" aria-hidden="true"></div><span class="tm-pill">${esc(request.destination)} · ${request.travelers} người</span><h1>Đang chuẩn bị<br>chuyến đi của bạn.</h1><ol class="tm-steps" id="tm-steps"><li>Tìm địa danh và địa điểm thật quanh điểm đến</li><li>Lấy dự báo thời tiết, xếp hạng địa điểm</li><li>Sắp xếp lịch từng ngày</li><li>Tự kiểm tra lịch và tính chi phí</li></ol><p role="status" id="planning-status" class="api-meta">Đang bắt đầu…</p><button class="button outline" id="cancel-plan">Hủy chờ kết quả</button></div>`);
    const controller=new AbortController();
    let cancelled=false;
    main.querySelector('#cancel-plan').onclick=()=>{cancelled=true;controller.abort();location.href='?view=create'};
    // Up to three Gemini rounds (draft, then fixes the self-check asks for) can take a few minutes.
    const timer=setTimeout(()=>controller.abort(),300000);
    // No per-agent progress is streamed yet: show elapsed time and what usually happens when.
    const started=Date.now(), statusLine=main.querySelector('#planning-status');
    const stages=[[0,'Đang tìm địa danh và địa điểm thật quanh điểm đến…'],[8,'Đang lấy dự báo thời tiết và xếp hạng địa điểm…'],[15,'Gemini đang sắp xếp lịch từng ngày (thường mất 30–90 giây)…'],[100,'Vẫn đang xử lý; chuyến nhiều ngày có thể lâu hơn…']];
    const steps=[...main.querySelectorAll('#tm-steps li')];
    const tick=setInterval(()=>{const s=Math.round((Date.now()-started)/1000);statusLine.textContent=`${stages.filter(([t])=>s>=t).pop()[1]} · ${s} giây`;const k=s<8?0:s<15?1:s<60?2:3;steps.forEach((li,i)=>{li.className=i<k?'done':i===k?'active':''})},1000);
    steps[0].className='active';
    controller.signal.addEventListener('abort',()=>clearInterval(tick));
    api('/api/v1/plans/preview',request,controller.signal).then(result=>{
      if(cancelled)return;
      const record={request,result};
      const finish=()=>{save('tm-plans',[record,...records()].slice(0,20));save('tm-current',result.request_id);location.replace('?view=plan')};
      if(session()?.user)api('/api/v1/me/trips',{request,result}).then(t=>{record.trip_id=t.id}).catch(()=>{}).finally(finish);else finish();
    }).catch(error=>{
      if(cancelled)return;
      if(error.auth){render(loginGate('Đăng nhập để TravelMate lập lịch trình. Thông tin bạn vừa nhập vẫn được giữ.','?view=loading'));return}
      render(emptyState('⚠️','Chưa tạo được lịch trình.',`<span class="api-error" role="alert">${esc(error.name==='AbortError'?'Đã hết thời gian chờ. Bạn có thể thử lại.':error.message)}</span>`,link('loading','Thử lại','button dark')+link('create','Sửa thông tin')));
    }).finally(()=>{clearTimeout(timer);clearInterval(tick)});
  }
  if(route==='plan'||route==='day'){
    const record=current();if(!record){empty();return}
    const {request,result}=record;
    const places=new Map(result.places.map(p=>[p.id,p]));
    const dayIndex=Number(params.get('day')||0);
    const day=result.draft.days[dayIndex];
    const fmt=d=>new Date(d+'T00:00:00').toLocaleDateString('vi-VN',{weekday:'short',day:'2-digit',month:'2-digit'});
    const cover=result.places.find(p=>p.photo);
    const firstPhoto=d=>d.activities.map(a=>places.get(a.place_id)).find(p=>p?.photo);
    const heading=`<section class="tm-plan-hero">${photo(cover,'tm-plan-cover')}<div class="tm-plan-hero-text"><span class="tm-pill">${result.mode==='demo'?'DEMO · DỮ LIỆU GIẢ LẬP':'BẢN PHÁC THẢO · CHƯA XÁC MINH'}</span><h1>${esc(request.destination)}</h1><div class="tm-chips"><span>📅 ${esc(fmt(request.start_date))} → ${esc(fmt(request.end_date))}</span><span>👥 ${request.travelers} người</span><span>💰 Ngân sách ${money(request.budget_vnd)}</span>${request.travel_style?`<span>Mức ${esc((styles[request.travel_style]||'').toLowerCase())}</span>`:''}<span>🗓️ ${result.draft.days.length} ngày · ${result.draft.days.reduce((n,d)=>n+d.activities.length,0)} điểm</span></div></div></section>`;
    const requestId=`<p class="api-meta tm-request-id">Mã yêu cầu: ${esc(result.request_id)}</p>`;
    if(route==='plan'){
      render(heading+'<div id="tm-plan-account"></div>'+selfCheck(result.self_check)+planningTrace(result.planning)+warnings([...result.warnings,...result.weather.warnings])+budget(result.budget)+`<h2 class="tm-section-title">Lịch trình từng ngày</h2><div class="tm-days">${result.draft.days.map((d,i)=>{const w=result.weather.days.find(x=>x.date===d.date);return `<article class="tm-day-card">${photo(firstPhoto(d),'tm-day-photo')}<div class="tm-day-body"><div class="tm-day-top"><span class="eyebrow">NGÀY ${i+1} · ${esc(fmt(d.date))}</span>${w?`<span class="tm-weather">${wmo(w.weather_code)}</span>`:''}</div><ol class="tm-mini-timeline">${d.activities.map(a=>`<li><time>${time(a.start_minute)}</time><span>${esc(places.get(a.place_id)?.name||a.place_id)}</span></li>`).join('')}</ol>${link(`day&id=${encodeURIComponent(result.request_id)}&day=${i}`,'Xem chi tiết ngày →')}</div></article>`}).join('')}</div>${stays(result.stays, request)}<div class="api-actions tm-plan-actions"><button type="button" class="button outline" id="tm-print">🖨️ In / lưu PDF</button>${link('create','Tạo chuyến đi mới')}${link('saved','Chuyến đi của tôi')}</div>${requestId}`).querySelector('#tm-print').onclick=()=>window.print();
    } else if(day){
      const weather=result.weather.days.find(w=>w.date===day.date);
      render(heading+`<div class="api-actions">${link(`plan&id=${encodeURIComponent(result.request_id)}`,'← Tổng quan')}${result.draft.days.map((d,i)=>`<a class="button ${i===dayIndex?'dark':'outline'}" href="?view=day&id=${encodeURIComponent(result.request_id)}&day=${i}"${i===dayIndex?' aria-current="page"':''}>Ngày ${i+1}</a>`).join('')}</div><div class="tm-day-head"><h2>Ngày ${dayIndex+1} · ${esc(fmt(day.date))}</h2><span class="tm-weather">${weather?wmo(weather.weather_code):'Chưa có dự báo thời tiết'}</span></div>`+'<ol class="tm-timeline">'+day.activities.map(a=>{
        const p=places.get(a.place_id);
        return `<li class="tm-stop"><div class="tm-stop-time"><strong>${time(a.start_minute)}</strong><span>${time(a.end_minute)}</span></div><article class="api-card tm-stop-card">${photo(p,'tm-stop-photo')}<div class="tm-stop-body"><h3>${p?`<a href="?view=place&id=${encodeURIComponent(p.id)}">${esc(p.name)}</a>`:esc(a.place_id)}</h3>${kind(p)?`<p class="api-meta">${esc(kind(p))}</p>`:''}${stars(p)}<p>${esc(p?.address||'Chưa có địa chỉ')}</p><p>${esc(price(p))}</p>${ticketSource(p)}${hours(p)}<p>${placeLinks(p)}</p><p class="api-meta">Nguồn: ${esc(p?.attribution||p?.source||'Chưa xác định')}</p></div></article></li>`;
      }).join('')+'</ol>'+warnings(result.warnings));
    }else empty();
  }
  if(route==='saved'&&!session()?.user){
    const list=records();
    render(head('CHUYẾN ĐI CỦA TÔI','Chuyến đi của bạn.','Đây là các lịch trình tạo trong lần truy cập này. Đăng nhập để lưu lâu dài, chỉnh sửa và mở lại trên thiết bị khác.',link('create','Tạo chuyến đi','button dark')+link('login&next=%3Fview%3Dsaved','Đăng nhập'))
      +(list.length?`<div class="tm-trip-grid">${list.map(({request,result})=>`<article class="tm-trip-card"><div class="eyebrow">${esc(dateRange(request.start_date,request.end_date))}</div><h3>${esc(request.destination)}</h3><p>${result.draft.days.length} ngày · ${request.travelers} người · ngân sách ${money(request.budget_vnd)}</p><div class="tm-row">${link(`plan&id=${encodeURIComponent(result.request_id)}`,'Mở lịch trình','button dark')}</div></article>`).join('')}</div>`
        :emptyState('🧳','Chưa có chuyến đi nào.','Nhập điểm đến, ngày đi và ngân sách để có bản lịch trình đầu tiên.',link('create','Tạo chuyến đi','button dark')+link('chat','Hỏi Trợ lý AI'))));
  }
  if(route==='explore'){
    const last=read('tm-explore',null);
    const q={destination:(params.get('destination')||last?.query.destination||'').slice(0,200),category:params.get('category')||last?.query.category||'attraction',keyword:(params.get('keyword')||(params.has('destination')?'':last?.query.keyword)||'').slice(0,120)};
    const cats={attraction:'Tham quan',restaurant:'Ăn uống',hotel:'Lưu trú'};
    const main=render(head('KHÁM PHÁ','Tìm nơi bạn muốn đến.','Điểm tham quan, quán ăn và nơi ở quanh một thành phố, kèm vị trí và giá tham khảo khi có.')
      +`<form id="api-search" class="tm-search"><label class="field">Thành phố / khu vực<input name="destination" required minlength="2" maxlength="200" value="${esc(q.destination)}" placeholder="Ví dụ: Đà Nẵng" autocomplete="off"></label><label class="field">Loại địa điểm<select name="category">${Object.entries(cats).map(([k,t])=>`<option value="${k}"${k===q.category?' selected':''}>${t}</option>`).join('')}</select></label><label class="field">Từ khóa (không bắt buộc)<input name="keyword" maxlength="120" value="${esc(q.keyword)}" placeholder="chay, cà phê, bảo tàng…"></label><button class="button dark">Tìm địa điểm</button></form>
      <div class="tm-quick-chips"><span>Thử nhanh:</span>${['Hà Nội','Huế','Đà Nẵng','Hội An','Đà Lạt','Nha Trang','Phú Quốc'].map(c=>`<button type="button" data-dest="${c}">${c}</button>`).join('')}</div>
      <div id="search-status" role="status" class="api-meta"></div><div id="search-warnings"></div><div id="api-results" class="api-grid"></div>`);
    const form=main.querySelector('form'),button=form.querySelector('button'),status=main.querySelector('#search-status'),results=main.querySelector('#api-results'),notes=main.querySelector('#search-warnings');
    const card=p=>`<article class="api-card">${photo(p)}<h3><a href="?view=place&id=${encodeURIComponent(p.id)}">${esc(p.name)}</a></h3>${stars(p)}${kind(p)?`<p class="api-meta">${esc(kind(p))}</p>`:''}<p>${esc(p.address||'')}</p><p>${esc(price(p))}</p><p>${mapLink(p)}</p><p class="api-meta">Nguồn: ${esc(p.attribution||p.source)}</p></article>`;
    const draw=(query,data)=>{
      status.textContent=data.places.length?`Tìm thấy ${data.places.length} địa điểm ở ${query.destination}.`:'Tìm thấy 0 địa điểm.';
      notes.innerHTML=warnings(data.warnings||[]);
      results.innerHTML=data.places.map(card).join('');
      if(!data.places.length)notes.innerHTML+=emptyState('🔎','Chưa thấy địa điểm phù hợp.','Thử bỏ từ khóa, đổi loại địa điểm hoặc viết tên thành phố đầy đủ.');
      else notes.innerHTML+=`<p class="tm-next">Thấy ưng ý? ${link('create&destination='+encodeURIComponent(query.destination),`Lên lịch đi ${esc(query.destination)} →`,'')}</p>`;
    };
    const search=async()=>{
      const f=new FormData(form),query={destination:String(f.get('destination')).trim(),category:f.get('category'),keyword:String(f.get('keyword')).trim()};
      if(query.destination.length<2){form.elements.destination.focus();return}
      button.disabled=true;status.textContent='Đang tìm địa điểm…';results.replaceChildren();notes.replaceChildren();
      try{const data=await api('/api/v1/places/search',{...query,limit:12});draw(query,data);try{save('tm-explore',{query,data})}catch{}}
      catch(error){status.textContent='';notes.innerHTML=error.auth?loginGate('Đăng nhập để tìm địa điểm.'):`<p class="api-error" role="alert">${esc(error.message)}</p>`}
      finally{button.disabled=false}
    };
    form.onsubmit=e=>{e.preventDefault();search()};
    main.querySelectorAll('[data-dest]').forEach(b=>b.onclick=()=>{form.elements.destination.value=b.dataset.dest;search()});
    // Coming back from a place page shows the last results again; a link with ?destination= searches at once.
    if(last&&last.query.destination===q.destination&&last.query.category===q.category&&last.query.keyword===q.keyword)draw(last.query,last.data);
    else if(params.has('destination')&&q.destination)search();
    else status.textContent='Nhập một thành phố rồi bấm “Tìm địa điểm”.';
  }
  if(route==='chat'){
    // Multi-agent chat: the concierge hands each message to one specialist; the badge shows who answered and why.
    const badges={concierge:'Trợ lý điều phối',place_finder:'Chuyên gia địa điểm',trip_planner:'Chuyên gia lịch trình',budget_advisor:'Chuyên gia chi phí',weather_advisor:'Chuyên gia thời tiết',guide_advisor:'Hướng dẫn viên'};
    const state=read('tm-chat',{session_id:null,messages:[]});
    const icons={concierge:'🧭',place_finder:'📍',trip_planner:'🗓️',budget_advisor:'💰',weather_advisor:'🌤️',guide_advisor:'📖'};
    const ideas=[['📍','Tìm quán chay ở Huế'],['📖','Lăng Tự Đức có gì đặc biệt, giá vé bao nhiêu?'],['🗓️','Lên lịch đi Huế 2 ngày, 2 người, 5 triệu'],['🌤️','Thời tiết Huế thế nào và chi phí bao nhiêu?'],['💰','Nếu ở khách sạn 500k/đêm thì sao?']];
    const chip=([i,t])=>`<button type="button" class="tm-chip chat-suggest" data-q="${esc(t)}">${i} ${esc(t)}</button>`;
    const main=render(`<div class="tm-chat"><aside class="tm-chat-side"><button type="button" class="button dark tm-new-chat" id="tm-chat-reset">＋ Cuộc trò chuyện mới</button></aside><section class="tm-chat-main"><div class="tm-chat-head"><h1>Trợ lý AI</h1><p class="api-meta">Trợ lý điều phối chuyển câu hỏi cho đúng chuyên gia: địa điểm, lịch trình, chi phí, thời tiết, hướng dẫn viên.</p></div><div id="tm-chat-log" class="chat-log" aria-live="polite"></div><div class="tm-chip-row">${ideas.map(chip).join('')}</div><form id="tm-chat-form" class="chat-form tm-chat-input"><input name="message" required maxlength="1000" autocomplete="off" placeholder="Hỏi gì cũng được, ví dụ: tìm quán chay ở Huế" aria-label="Tin nhắn"><button class="button dark" aria-label="Gửi">Gửi ↑</button></form></section></div>`);
    const log=main.querySelector('#tm-chat-log'),form=main.querySelector('#tm-chat-form'),input=form.querySelector('input'),button=form.querySelector('button');
    const placeCard=p=>`<article class="api-card chat-place">${photo(p,'api-thumb')}<h4><a href="?view=place&id=${encodeURIComponent(p.id)}">${esc(p.name)}</a></h4>${kind(p)?`<p class="api-meta">${esc(kind(p))}</p>`:''}<p>${esc(p.address||'')}</p><p>${esc(price(p))}</p><p>${placeLinks(p)}</p></article>`;
    const bubble=m=>m.role==='user'?`<div class="chat-msg user"><p>${esc(m.text)}</p></div>`:`<div class="tm-msg-row"><span class="tm-agent-ico" aria-hidden="true">${icons[m.agent]||'✦'}</span><div class="chat-msg bot"><div class="chat-agent">${esc(badges[m.agent]||m.agent||'Trợ lý')}</div>${m.reason?`<p class="api-meta">Vì sao chọn: ${esc(m.reason)}</p>`:''}<p>${esc(m.text)}</p>${m.citations?.length?`<p class="api-meta">Nguồn: ${m.citations.filter(c=>/^https:\/\//.test(c.url)).map(c=>`<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">[${esc(c.id)}] ${esc(c.title)}</a>`).join(' · ')}</p>`:''}${m.places?.length?`<div class="api-grid chat-places">${m.places.slice(0,6).map(placeCard).join('')}</div>`:''}${m.login?`<p>${link('login&next=%3Fview%3Dchat','Đăng nhập','button dark')} ${link('signup&next=%3Fview%3Dchat','Tạo tài khoản')}</p>`:''}${m.plan_id?`<p>${m.trip_id?link(`trip&id=${encodeURIComponent(m.trip_id)}`,'Mở lịch trình (đã lưu vào Chuyến đi của tôi) →'):link(`plan&id=${encodeURIComponent(m.plan_id)}`,'Mở lịch trình đầy đủ →')}</p>`:''}</div></div>`;
    const draw=()=>{log.innerHTML=state.messages.map(bubble).join('')||`<div class="tm-chat-empty"><span class="tm-chat-logo">✦</span><h2>Bạn muốn đi đâu?</h2><p class="api-meta">Hỏi về địa điểm, lịch trình, chi phí hay thời tiết. Có thể hỏi nhiều việc trong một câu.</p><div class="tm-idea-grid">${ideas.slice(0,4).map(chip).join('')}</div></div>`;main.querySelector('.tm-chip-row').hidden=!state.messages.length;log.scrollTop=log.scrollHeight};
    const send=async text=>{
      state.messages.push({role:'user',text});draw();button.disabled=true;input.value='';
      const waiting=document.createElement('div');waiting.className='tm-typing';waiting.setAttribute('role','status');waiting.innerHTML='<i></i><i></i><i></i><small>Đang chuyển cho chuyên gia phù hợp… lập lịch có thể mất 1–2 phút</small>';log.append(waiting);log.scrollTop=log.scrollHeight;
      try{
        const r=await api('/api/v1/chat',{session_id:state.session_id,message:text});
        state.session_id=r.session_id;
        for(const reply of (r.replies?.length?r.replies:[r.reply])){
          const m={role:'assistant',agent:reply.agent,reason:reply.reason,text:reply.text,places:reply.places,citations:reply.citations};
          if(reply.plan&&reply.trip){save('tm-plans',[{request:reply.trip,result:reply.plan,trip_id:r.trip_id||undefined},...records()].slice(0,20));save('tm-current',reply.plan.request_id);m.plan_id=reply.plan.request_id;if(r.trip_id)m.trip_id=r.trip_id}
          state.messages.push(m);
        }
        loadHistory();
      }catch(error){state.messages.push({role:'assistant',agent:'concierge',text:error.message,login:!!error.auth})}
      finally{save('tm-chat',{...state,messages:state.messages.slice(-40)});button.disabled=false;draw();input.focus()}
    };
    form.onsubmit=e=>{e.preventDefault();const t=input.value.trim();if(t)send(t)};
    main.addEventListener('click',e=>{const b=e.target.closest('.chat-suggest');if(b&&!button.disabled)send(b.dataset.q||b.textContent.trim())});
    main.querySelector('#tm-chat-reset').onclick=()=>{state.session_id=null;state.messages=[];save('tm-chat',state);draw();loadHistory()};
    // Signed-in users: earlier conversations are kept in their account.
    const history=document.createElement('section');history.className='tm-chat-history';history.id='tm-chat-history';main.querySelector('.tm-chat-side').append(history);
    function loadHistory(){
      if(!session()?.user){history.innerHTML=`<p class="api-meta">Đăng nhập để lưu các cuộc trò chuyện và tự lưu lịch trình vào tài khoản.</p>${link('login&next=%3Fview%3Dchat','Đăng nhập')}`;return}
      api('/api/v1/me/chats',null,undefined,'GET').then(list=>{
        history.innerHTML=`<div class="side-label">GẦN ĐÂY</div>${list.map(c=>`<div class="tm-history-row${c.id===state.session_id?' active':''}"><button type="button" class="tm-history-open" data-open-chat="${esc(c.id)}"><span>${esc(c.title)}</span><small>${(d=>`${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')} · ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`)(new Date(c.updated_at*1000))}</small></button><button type="button" class="tm-history-del" data-del-chat="${esc(c.id)}" aria-label="Xoá cuộc trò chuyện" title="Xoá">×</button></div>`).join('')||'<p>Chưa có cuộc trò chuyện nào được lưu.</p>'}`;
      }).catch(()=>{history.textContent=''});
    }
    history.onclick=async e=>{
      const open=e.target.dataset.openChat, del=e.target.dataset.delChat;
      try{
        if(open){const c=await api(`/api/v1/me/chats/${encodeURIComponent(open)}`,null,undefined,'GET');state.session_id=c.id;state.messages=c.messages.map(m=>({role:m.role,agent:m.agent,reason:m.reason,text:m.text,places:m.places,citations:m.citations}));save('tm-chat',state);draw()}
        if(del&&await dialog({title:'Xoá cuộc trò chuyện này?',text:'Nội dung cuộc trò chuyện sẽ bị xoá khỏi tài khoản.',ok:'Xoá',danger:true})){await api(`/api/v1/me/chats/${encodeURIComponent(del)}`,null,undefined,'DELETE');if(state.session_id===del){state.session_id=null;state.messages=[];save('tm-chat',state);draw()}loadHistory()}
      }catch(err){notify(err.message)}
    };
    loadHistory();
    draw();
    const asked=(params.get('q')||'').trim().slice(0,1000);
    if(asked){input.value=asked;input.focus()}
  }
})();
