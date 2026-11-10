/* App shell: navigation, page titles, the trip form, the not-found screen and small shared helpers.
   Screens that show data are rendered by integration.js and features.js. */
(() => {
  'use strict';
  const params = new URLSearchParams(location.search);
  const route = params.get('view') || 'home';
  const routes = {
    home: 'Lên kế hoạch du lịch cùng AI', explore: 'Khám phá', chat: 'Trợ lý AI', login: 'Đăng nhập', signup: 'Đăng ký',
    forgot: 'Quên mật khẩu', create: 'Tạo chuyến đi', loading: 'Đang lập kế hoạch', saved: 'Chuyến đi của tôi', trip: 'Chuyến đi',
    plan: 'Lịch trình', day: 'Chi tiết ngày', place: 'Địa điểm', edit: 'Chỉnh sửa lịch trình', favorites: 'Yêu thích',
    profile: 'Tài khoản', review: 'Viết đánh giá', admin: 'Quản trị · Tổng quan', 'admin-places': 'Quản trị · Địa điểm',
    'admin-users': 'Quản trị · Người dùng', moderation: 'Quản trị · Kiểm duyệt',
  };
  window.travelmateRoutes = routes;
  const header = document.querySelector('header');

  // Top navigation; the entry for the section you are in is marked as current.
  const section = {plan: 'saved', day: 'saved', trip: 'saved', edit: 'saved', loading: 'create', place: 'explore', review: 'explore'}[route] || route;
  const nav = header.querySelector('nav');
  nav.innerHTML = [['explore', 'Khám phá'], ['chat', 'Trợ lý AI'], ['create', 'Tạo chuyến đi'], ['saved', 'Chuyến đi của tôi']]
    .map(([v, t]) => `<a href="?view=${v}"${v === section ? ' aria-current="page"' : ''}>${t}</a>`).join('');
  const toggle = header.querySelector('.menu-toggle');
  const setMenu = open => { header.classList.toggle('menu-open', open); toggle.setAttribute('aria-expanded', String(open)); toggle.setAttribute('aria-label', open ? 'Đóng menu' : 'Mở menu'); };
  toggle.addEventListener('click', () => setMenu(!header.classList.contains('menu-open')));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') setMenu(false); });

  // A short message at the bottom of the screen ("Đã lưu", "Đã sao chép").
  const toast = document.createElement('div');
  toast.id = 'toast';
  toast.setAttribute('role', 'status');
  document.body.append(toast);
  let timer;
  window.tmToast = text => { toast.textContent = text; toast.classList.add('show'); clearTimeout(timer); timer = setTimeout(() => toast.classList.remove('show'), 4000); };

  const show = html => {
    const main = document.createElement('main');
    main.className = 'view visible expanded-view';
    main.id = 'expanded';
    main.innerHTML = html;
    header.after(main);
  };
  const field = (label, name, type, value, extra = '') => `<label class="field">${label}<input name="${name}" type="${type}" value="${value}" required ${extra}></label>`;

  if (route === 'home') document.getElementById('home').classList.add('visible');
  else if (route === 'create') {
    const interests = ['Biển & thiên nhiên', 'Ẩm thực', 'Văn hóa', 'Lịch sử & di tích', 'Nghỉ dưỡng', 'Cà phê & dạo phố'];
    show(`<div class="page-shell"><div class="page-intro"><div><div class="eyebrow">LÊN KẾ HOẠCH</div><h1>Chuyến đi sắp tới.<br><span>Theo cách bạn muốn.</span></h1><p>Vài thông tin cơ bản là đủ. Bạn có thể chỉnh lịch sau khi xem bản phác thảo.</p></div></div>
      <div class="form-layout"><form class="surface large-form" data-form="create"><div class="section-label"><h2>Thông tin chuyến đi</h2></div>
        ${field('Bạn muốn đi đâu?', 'destination', 'text', '', 'minlength="2" maxlength="200" placeholder="Ví dụ: Huế, Đà Nẵng, Đà Lạt" autocomplete="off"')}
        <div class="form-grid">${field('Ngày khởi hành', 'start', 'date', '')}${field('Ngày kết thúc', 'end', 'date', '')}${field('Số người', 'people', 'number', '2', 'min="1" max="50"')}
          <label class="field">Ngân sách toàn chuyến (VND)<input name="budget" type="number" value="5000000" required min="1000" step="1000" inputmode="numeric"><small class="tm-field-hint" id="tm-budget-hint"></small></label></div>
        <label class="field">Mức chi tiêu<select name="travel_style"><option value="budget">Tiết kiệm</option><option value="mid" selected>Vừa phải</option><option value="high">Cao cấp</option></select></label>
        <fieldset><legend>Điều bạn muốn trải nghiệm</legend><div class="choice-grid">${interests.map((t, i) => `<label class="choice"><input type="checkbox" name="interests" value="${t}" ${i < 2 ? 'checked' : ''}>${t}</label>`).join('')}</div></fieldset>
        <label class="field">Lưu ý khác<textarea name="notes" maxlength="1500" placeholder="Ví dụ: muốn đi chậm, có trẻ nhỏ, ăn chay, hạn chế di chuyển xa…" rows="3"></textarea></label>
        <div class="form-status" role="status"></div><button class="button dark full">Lập lịch trình <span>✧</span></button></form>
      <aside class="form-aside"><span class="orb">✧</span><h2>Chưa cần biết<br>mọi chi tiết.</h2><p>TravelMate tìm địa điểm, xem dự báo thời tiết rồi xếp lịch từng ngày. Thường mất khoảng một phút.</p>
        <div class="mini-step"><b>01</b> Tìm điểm tham quan, quán ăn, nơi ở quanh điểm đến</div><div class="mini-step"><b>02</b> Xếp lịch theo giờ và tự kiểm tra lại</div><div class="mini-step"><b>03</b> Ước tính chi phí so với ngân sách của bạn</div>
        <a class="text-link" href="?view=chat">Hoặc bắt đầu bằng trò chuyện →</a>
        <div class="prototype-note">✧ <span>Chi phí là ước tính tham khảo. TravelMate không đặt dịch vụ thay bạn.</span></div></aside></div></div>`);
  } else if (!routes[route]) {
    show(`<div class="page-shell tm-notfound"><div class="eyebrow">LỖI 404</div><h1>Không tìm thấy trang.</h1><p>Đường dẫn này không tồn tại hoặc đã được đổi.</p><div class="api-actions"><a class="button dark" href="?view=home">Về trang chủ</a><a class="button outline" href="?view=create">Tạo chuyến đi</a></div></div>`);
    document.title = 'Không tìm thấy trang — TravelMate';
  }
  if (routes[route] && route !== 'home') document.title = `${routes[route]} — TravelMate`;
})();
