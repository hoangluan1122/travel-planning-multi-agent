/* Same-origin API integration. Provider credentials never enter the browser. */
(() => {
  'use strict';
  const params = new URLSearchParams(location.search);
  const route = params.get('view') || 'home';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => Number(value).toLocaleString('vi-VN') + ' ₫';
  const time = value => `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;
  const read = (key, fallback) => {try {return JSON.parse(sessionStorage.getItem(key)) ?? fallback} catch {return fallback}};
  const save = (key, value) => sessionStorage.setItem(key, JSON.stringify(value));
  const link = (view, text) => `<a class="button outline" href="?view=${view}">${text}</a>`;
  const style = document.createElement('style');
  style.textContent = '.api-banner{padding:12px 5%;background:#eef1ff;font-size:13px}.api-banner input{max-width:240px;padding:8px}.api-card{padding:24px;margin:16px 0;border:1px solid #e1e5ee;border-radius:20px;background:white;overflow-wrap:anywhere}.api-actions{display:flex;gap:12px;flex-wrap:wrap}.api-warning{padding:16px;background:#fff5dc;border-radius:12px;margin:12px 0}.api-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:16px}.api-error{color:#a32424}.api-card h3{margin:12px 0}.api-card p{margin:12px 0}.api-meta{color:#647084;font-size:13px}.api-banner summary{cursor:pointer}';
  document.head.append(style);
  const banner = document.createElement('div');
  banner.className = 'api-banner';
  banner.innerHTML = '<span id="api-health" role="status">Đang kiểm tra kết nối backend…</span><details><summary>Cấu hình kết nối</summary><label>Token truy cập backend (nếu được yêu cầu) <input type="password" id="api-token" autocomplete="off"></label><button id="token-save" type="button">Áp dụng</button><small> Token chỉ lưu trong phiên tab này. Không nhập API key Gemini tại đây.</small></details>';
  document.querySelector('header').after(banner);
  document.querySelector('#api-token').value = read('tm-token','');
  document.querySelector('#token-save').onclick = () => {save('tm-token',document.querySelector('#api-token').value.trim());document.querySelector('#api-health').textContent='Đã áp dụng token. Bạn có thể thử lại yêu cầu.'};
  fetch('/health').then(r=>{if(!r.ok)throw Error();return r.json()}).then(h=>{
    document.querySelector('#api-health').textContent = `Backend đã kết nối · ${h.mode==='demo'?'DEMO — dữ liệu giả lập, không phải địa điểm thật':'LIVE — sử dụng nhà cung cấp trực tiếp'}${h.token_required?' · Yêu cầu token truy cập':''}`;
  }).catch(()=>{document.querySelector('#api-health').textContent='Không kết nối được backend. Hãy chạy ứng dụng qua máy chủ FastAPI.'});

  async function api(path, data, signal) {
    const headers = {'Content-Type':'application/json'};
    const token = read('tm-token','');
    if(token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path,{method:'POST',headers,body:JSON.stringify(data),signal});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) {
      if(response.status===401) throw Error('Token truy cập không đúng hoặc còn thiếu. Mở Cấu hình kết nối để nhập lại.');
      if(response.status===422) throw Error('Thông tin chưa hợp lệ: '+(Array.isArray(body.detail)?body.detail.map(e=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; '):'Kiểm tra lại biểu mẫu.'));
      throw Error(response.status===504?'Quá thời gian xử lý. Vui lòng thử lại.':body.detail || `Backend trả lỗi ${response.status}`);
    }
    return body;
  }
  function render(content) {
    document.querySelectorAll('main.view').forEach(e=>e.classList.remove('visible'));
    let main=document.querySelector('#connected-view');
    if(!main){main=document.createElement('main');main.id='connected-view';document.body.append(main)}
    main.className='view visible expanded-view';main.innerHTML=`<div class="page-shell">${content}</div>`;
    return main;
  }
  const records = () => read('tm-plans',[]);
  const current = () => records().find(p=>p.result.request_id===(params.get('id')||read('tm-current','')));
  const warnings = items => items.length?`<div class="api-warning"><strong>Thông tin cần lưu ý</strong><ul>${[...new Set(items)].map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:'';
  const budget = b => `<div class="api-card"><h3>Chi phí đã có dữ liệu: ${money(b.known_subtotal)}</h3><p>${b.status==='incomplete'?'Chưa đủ dữ liệu để kết luận tổng chi phí.':b.status==='over_budget'?'Chi phí đã biết vượt ngân sách.':'Các khoản đã tính nằm trong ngân sách.'}</p>${b.unknown_items.length?`<p>Chưa tính được: ${b.unknown_items.map(esc).join(', ')}. Không coi các khoản này là 0.</p>`:''}</div>`;
  const empty = () => render(`<h1>Chưa có lịch trình.</h1><p>Hãy tạo chuyến đi để xem kết quả từ backend.</p>${link('create','Tạo chuyến đi')}`);

  if(route==='home'){
    document.querySelector('.hero-copy .button').href='?view=create';
  }
  if(route==='create'){
    const form=document.querySelector('[data-form=create]');
    const previous=read('tm-request',null);
    const localDate=new Date();localDate.setMinutes(localDate.getMinutes()-localDate.getTimezoneOffset());
    const today=localDate.toISOString().slice(0,10);
    ['start','end'].forEach(n=>{form.elements[n].min=today;form.elements[n].value=today});
    form.elements.people.max=50;form.elements.budget.min=1;form.elements.notes.maxLength=1500;
    if(previous){for(const [name,key] of Object.entries({destination:'destination',start:'start_date',end:'end_date',people:'travelers',budget:'budget_vnd',notes:'notes'}))form.elements[name].value=previous[key]??''}
    form.addEventListener('submit',e=>{
      e.preventDefault();e.stopImmediatePropagation();
      const f=new FormData(form);
      const days=(new Date(f.get('end'))-new Date(f.get('start')))/86400000;
      if(days<0||days>13){form.querySelector('.form-status').textContent='Chuyến đi cần dài từ 1 đến 14 ngày.';return}
      const request={destination:f.get('destination').trim(),start_date:f.get('start'),end_date:f.get('end'),travelers:Number(f.get('people')),budget_vnd:f.get('budget'),interests:f.getAll('interests'),notes:f.get('notes').trim()};
      try{save('tm-request',request);location.href='?view=loading'}catch{form.querySelector('.form-status').textContent='Không lưu được dữ liệu trong phiên trình duyệt. Hãy cho phép session storage.'}
    },true);
  }
  if(route==='loading'){
    const request=read('tm-request',null);
    if(!request){empty();return}
    const main=render('<h1>Đang chuẩn bị<br>chuyến đi của bạn.</h1><p role="status" id="planning-status">Backend đang xử lý địa điểm, thời tiết và lịch trình. Chưa có tiến độ riêng từng agent.</p><button class="button outline" id="cancel-plan">Hủy chờ kết quả</button>');
    const controller=new AbortController();
    let cancelled=false;
    main.querySelector('#cancel-plan').onclick=()=>{cancelled=true;controller.abort();location.href='?view=create'};
    const timer=setTimeout(()=>controller.abort(),120000);
    api('/api/v1/plans/preview',request,controller.signal).then(result=>{
      if(cancelled)return;
      save('tm-plans',[{request,result},...records()].slice(0,20));save('tm-current',result.request_id);location.replace('?view=plan');
    }).catch(error=>{
      if(cancelled)return;
      render(`<h1>Chưa tạo được lịch trình.</h1><p class="api-error" role="alert">${esc(error.name==='AbortError'?'Đã hết thời gian chờ. Bạn có thể thử lại.':error.message)}</p><div class="api-actions">${link('loading','Thử lại')}${link('create','Sửa thông tin')}</div>`);
    }).finally(()=>clearTimeout(timer));
  }
  if(route==='plan'||route==='day'){
    const record=current();if(!record){empty();return}
    const {request,result}=record;
    const places=new Map(result.places.map(p=>[p.id,p]));
    const dayIndex=Number(params.get('day')||0);
    const day=result.draft.days[dayIndex];
    const heading=`<div class="eyebrow">${result.mode==='demo'?'DEMO · DỮ LIỆU GIẢ LẬP':'BẢN PHÁC THẢO · CHƯA XÁC MINH'}</div><h1>${esc(request.destination)}</h1><p>${esc(request.start_date)} → ${esc(request.end_date)} · ${request.travelers} người · Ngân sách ${money(request.budget_vnd)}</p><p class="api-meta">Mã yêu cầu: ${esc(result.request_id)}</p>`;
    if(route==='plan'){
      render(heading+warnings([...result.warnings,...result.weather.warnings])+budget(result.budget)+`<div class="api-grid">${result.draft.days.map((d,i)=>`<article class="api-card"><div class="eyebrow">NGÀY ${i+1} · ${esc(d.date)}</div><h3>${d.activities.length} hoạt động</h3><p>${d.activities.map(a=>esc(places.get(a.place_id)?.name||a.place_id)).join(' → ')}</p>${link(`day&id=${encodeURIComponent(result.request_id)}&day=${i}`,'Xem chi tiết ngày →')}</article>`).join('')}</div><div class="api-actions">${link('create','Tạo kế hoạch mới')}${link('saved','Kế hoạch trong phiên')}</div>`);
    } else if(day){
      const weather=result.weather.days.find(w=>w.date===day.date);
      render(heading+`<div class="api-actions">${link(`plan&id=${encodeURIComponent(result.request_id)}`,'← Tổng quan')}${result.draft.days.map((d,i)=>link(`day&id=${encodeURIComponent(result.request_id)}&day=${i}`,`Ngày ${i+1}`)).join('')}</div><h2>Ngày ${dayIndex+1} · ${esc(day.date)}</h2><p>${weather?`Mã thời tiết WMO: ${weather.weather_code}`:'Chưa có dự báo thời tiết cho ngày này.'}</p>`+day.activities.map(a=>{
        const p=places.get(a.place_id);
        return `<article class="api-card"><div class="eyebrow">${time(a.start_minute)} — ${time(a.end_minute)}</div><h3>${esc(p?.name||a.place_id)}</h3><p>${esc(p?.address||'Chưa có địa chỉ')}</p><p>${p?.estimated_visit_cost_vnd==null?'Chưa có giá tham khảo':money(p.estimated_visit_cost_vnd)}</p><p class="api-meta">Nguồn: ${esc(p?.source||'Chưa xác định')} · Chưa có ảnh địa điểm từ API.</p></article>`;
      }).join('')+warnings(result.warnings));
    }else empty();
  }
  if(route==='saved')render(`<h1>Những chuyến đi<br>trong phiên này.</h1><p>Lưu tạm trong tab trình duyệt, chưa đồng bộ tài khoản hoặc database.</p>${link('create','Tạo chuyến đi')}<div class="api-grid">${records().map(({request,result})=>`<article class="api-card"><h3>${esc(request.destination)}</h3><p>${esc(request.start_date)} · ${result.draft.days.length} ngày · ${result.mode.toUpperCase()}</p>${link(`plan&id=${encodeURIComponent(result.request_id)}`,'Mở lịch trình')}</article>`).join('')||'<p>Chưa có chuyến đi nào.</p>'}</div>`);
  if(route==='explore'){
    const main=render('<h1>Tìm nơi bạn muốn đến.</h1><form id="api-search" class="api-card"><label class="field">Thành phố / khu vực<input name="destination" required minlength="2" maxlength="200" value="Đà Nẵng"></label><label class="field">Loại địa điểm<select name="category"><option value="attraction">Tham quan</option><option value="hotel">Khách sạn</option><option value="restaurant">Nhà hàng</option></select></label><label class="field">Từ khóa<input name="keyword" maxlength="120"></label><button class="button dark">Tìm địa điểm</button></form><div id="search-status" role="status"></div><div id="api-results" class="api-grid"></div>');
    main.querySelector('form').onsubmit=async e=>{
      e.preventDefault();const button=e.target.querySelector('button'),status=main.querySelector('#search-status'),results=main.querySelector('#api-results');
      button.disabled=true;status.textContent='Đang tìm địa điểm…';results.replaceChildren();
      try{const f=new FormData(e.target);const data=await api('/api/v1/places/search',{destination:f.get('destination'),category:f.get('category'),keyword:f.get('keyword'),limit:12});status.textContent=`Tìm thấy ${data.places.length} địa điểm.`;results.innerHTML=warnings(data.warnings)+data.places.map(p=>`<article class="api-card"><h3>${esc(p.name)}</h3><p>${esc(p.address)}</p><p class="api-meta">Nguồn: ${esc(p.source)}</p><p>${p.estimated_visit_cost_vnd==null?'Chưa có giá tham khảo':money(p.estimated_visit_cost_vnd)}</p></article>`).join('')}
      catch(error){status.textContent=error.message}finally{button.disabled=false}
    };
  }
  // Remaining designs are explicitly previews, not simulated authenticated features.
  if(['chat','login','signup','forgot','profile','review','edit','favorites','place','admin','admin-users','admin-places','moderation'].includes(route)){
    render(`<h1>Màn hình đang chờ<br>kết nối nghiệp vụ.</h1><p>Backend hiện cung cấp API tìm địa điểm và tạo lịch trình. Chức năng ${esc(window.travelmateRoutes?.[route]||route)} chưa có API tương ứng.</p><div class="api-actions">${link('create','Tạo chuyến đi')}${link('explore','Tìm địa điểm')}${link('saved','Xem kế hoạch')}</div>`);
  }
})();
