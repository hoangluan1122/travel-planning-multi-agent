/* Company pages of the public site: about, pricing, contact, terms, privacy; the contact inbox
   for admins; today's AI quota on the account page. Uses the helpers integration.js exports. */
(() => {
  'use strict';
  const tm = window.tm;
  if (!tm) return;
  const {api, render, esc, head, link, route, session, notify, dialog} = tm;
  const get = path => api(path, null, undefined, 'GET');
  const user = () => session()?.user || null;
  const EFFECTIVE = '12/11/2026';
  // Who runs the site and how to reach them come from the server (TRAVELMATE_OPERATOR_NAME, ..._CONTACT_EMAIL).
  const site = get('/api/v1/site').catch(() => ({daily_plans: 10, daily_chats: 60, operator_name: '', contact_email: '', signup_open: true}));
  const operator = s => esc(s.operator_name || 'Đơn vị vận hành TravelMate');
  const reach = s => s.contact_email
    ? `email <a href="mailto:${esc(s.contact_email)}">${esc(s.contact_email)}</a> hoặc <a href="?view=contact">biểu mẫu liên hệ</a>`
    : '<a href="?view=contact">biểu mẫu liên hệ</a>';
  const limitText = n => n ? `${n} mỗi ngày` : 'không giới hạn';
  const doc = (eyebrow, title, intro, sections) => render(`<article class="tm-doc">${head(eyebrow, title, intro)}
    ${sections.map(([h, body]) => `<section><h2>${h}</h2>${body}</section>`).join('')}</article>`);
  const list = items => `<ul>${items.map(i => `<li>${i}</li>`).join('')}</ul>`;

  // --- about -------------------------------------------------------------------------------
  if (route === 'about') {
    render(`<article class="tm-doc">${head('GIỚI THIỆU', 'Du lịch Việt Nam, lên kế hoạch trong vài phút.',
      'TravelMate là trợ lý lập kế hoạch du lịch bằng AI: bạn nói đi đâu, đi mấy ngày, bao nhiêu người và bao nhiêu tiền, TravelMate trả về lịch trình từng ngày có địa điểm thật, thời tiết và chi phí ước tính.',
      link('create', 'Tạo chuyến đi', 'button dark') + link('chat', 'Hỏi Trợ lý AI'))}
      <div class="tm-feature-grid tm-about-grid">
        <div class="tm-feature"><span class="tm-feature-ico">🗓️</span><h3>Lịch trình từng ngày</h3><p>Điểm tham quan, bữa ăn và quán cà phê được xếp theo giờ, ưu tiên các điểm nổi tiếng và tránh hoạt động ngoài trời vào ngày mưa.</p></div>
        <div class="tm-feature"><span class="tm-feature-ico">💰</span><h3>Chi phí so với ngân sách</h3><p>Vé tham quan theo bảng giá có ghi nguồn; lưu trú, ăn uống, đi lại theo giá tham khảo; cho biết ngân sách đủ hay thiếu.</p></div>
        <div class="tm-feature"><span class="tm-feature-ico">✅</span><h3>Tự kiểm tra trước khi trả lời</h3><p>Lịch được kiểm tra bằng quy tắc: có bữa trưa, bữa ăn không quá dày, không lặp địa điểm, có điểm nổi tiếng. Chưa đạt thì AI tự sửa.</p></div>
        <div class="tm-feature"><span class="tm-feature-ico">💬</span><h3>Trợ lý AI tiếng Việt</h3><p>Mỗi câu hỏi được chuyển cho đúng chuyên gia: tìm địa điểm, hướng dẫn viên, thời tiết, chi phí hoặc lập lịch.</p></div>
      </div>
      <section><h2>Dữ liệu đến từ đâu</h2>${list([
        'Địa điểm: <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> (qua Photon và Overpass), dữ liệu cộng đồng theo giấy phép ODbL.',
        'Thời tiết: dự báo của <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a>.',
        'Ảnh: Wikipedia và Wikimedia Commons, ghi tác giả và giấy phép dưới mỗi ảnh.',
        'Giá vé: bảng giá TravelMate tự tổng hợp từ trang chính thức và báo chí, ghi nguồn và ngày kiểm tra.',
        'AI: mô hình Gemini của Google sắp xếp lịch và trả lời trò chuyện.'])}</section>
      <section><h2>Điều TravelMate chưa làm</h2>${list([
        'Lịch trình là bản phác thảo: giờ mở cửa, giá và tình trạng hoạt động của địa điểm có thể đã thay đổi. Hãy kiểm tra lại trước khi đi.',
        'TravelMate không bán vé, không đặt phòng và không nhận thanh toán.',
        'Thời gian di chuyển giữa các điểm chưa được tính theo tuyến đường thật.'])}</section>
      <section class="tm-cta tm-doc-cta"><h2>Thử ngay, miễn phí.</h2><p>Tạo tài khoản để lưu lịch trình, chỉnh sửa và giữ lại những nơi bạn thích.</p><div class="tm-cta-actions">${link('create', 'Tạo chuyến đi <span>↗</span>', 'button light')}${user() ? '' : link('signup', 'Tạo tài khoản', 'button ghost')}</div></section>
    </article>`);
  }

  // --- pricing -----------------------------------------------------------------------------
  if (route === 'pricing') {
    const main = render('<p class="tm-loading-line">Đang tải…</p>');
    site.then(s => {
      main.querySelector('.page-shell').innerHTML = `${head('BẢNG GIÁ', 'Miễn phí cho người đi du lịch.', 'Không cần thẻ, không quảng cáo. Hạn mức AI mỗi ngày giúp dịch vụ chạy ổn định cho mọi người.')}
      <div class="tm-plans">
        <section class="tm-plan-card featured"><div class="eyebrow">CÁ NHÂN</div><h2>Miễn phí</h2><p class="tm-price">0 ₫ <span>/ tháng</span></p>
          ${list([`Lập lịch trình bằng AI: ${limitText(s.daily_plans)}`, `Tin nhắn với Trợ lý AI: ${limitText(s.daily_chats)}`, 'Lưu, chỉnh sửa, đổi ngày và in lịch trình', 'Địa điểm yêu thích và đánh giá', 'Chi phí ước tính theo ngân sách'])}
          ${user() ? link('create', 'Tạo chuyến đi', 'button dark') : link('signup', 'Tạo tài khoản miễn phí', 'button dark')}</section>
        <section class="tm-plan-card"><div class="eyebrow">ĐỐI TÁC & DOANH NGHIỆP</div><h2>Liên hệ</h2><p class="tm-price">Theo thoả thuận</p>
          ${list(['Hạn mức riêng cho công ty du lịch, khách sạn, trường học', 'Kết nối qua API, A2A hoặc MCP', 'Bổ sung giá vé, địa điểm cho điểm đến của bạn'])}
          ${link('contact&topic=partner', 'Gửi đề nghị hợp tác', 'button outline')}</section>
      </div>
      <section class="tm-faq"><h2>Câu hỏi thường gặp</h2>
        <details><summary>TravelMate có thu phí không?</summary><p>Không. Mọi tính năng hiện có đều miễn phí. Nếu sau này có gói trả phí, gói miễn phí vẫn được giữ và bạn sẽ được báo trước.</p></details>
        <details><summary>Vì sao có giới hạn mỗi ngày?</summary><p>Mỗi lần lập lịch hoặc trả lời cần gọi mô hình AI, và tài nguyên AI có hạn. Giới hạn theo tài khoản giữ cho dịch vụ không bị một người dùng hết. Hạn mức được làm mới lúc 0 giờ (giờ Việt Nam); bạn xem số lượt còn lại trong <a href="?view=profile">Tài khoản</a>.</p></details>
        <details><summary>Thông tin trong lịch trình có chính xác không?</summary><p>Địa điểm là địa điểm thật trên bản đồ mở, nhưng giờ mở cửa và giá có thể đã đổi. Giá vé có ghi nguồn và ngày kiểm tra; các khoản khác là giá tham khảo. Hãy kiểm tra lại trước chuyến đi.</p></details>
        <details><summary>TravelMate có đặt phòng hay bán vé không?</summary><p>Không. Nút “Xem giá phòng” mở trang đặt phòng bên ngoài để bạn tự xem giá và đặt.</p></details>
        <details><summary>Làm sao xoá dữ liệu của tôi?</summary><p>Vào <a href="?view=profile">Tài khoản</a> → Xoá tài khoản. Chuyến đi, yêu thích, đánh giá và lịch sử trò chuyện được xoá cùng tài khoản. Xem thêm <a href="?view=privacy">Chính sách bảo mật</a>.</p></details>
      </section>`;
    });
  }

  // --- contact -----------------------------------------------------------------------------
  if (route === 'contact') {
    const topics = [['support', 'Hỗ trợ sử dụng'], ['feedback', 'Góp ý, báo lỗi'], ['partner', 'Hợp tác'], ['privacy', 'Quyền riêng tư, dữ liệu cá nhân'], ['other', 'Khác']];
    const chosen = new URLSearchParams(location.search).get('topic');
    const u = user();
    const main = render(`<div class="tm-contact">${head('LIÊN HỆ', 'Chúng tôi đọc mọi tin nhắn.', 'Hỏi cách dùng, báo lỗi, góp ý hoặc đề nghị hợp tác. Thường trả lời trong 1–3 ngày làm việc.')}
      <div class="tm-contact-grid">
        <form class="api-card" id="tm-contact" novalidate>
          <label class="field">Họ và tên<input name="name" required maxlength="80" autocomplete="name" value="${esc(u?.name || '')}"></label>
          <label class="field">Email để chúng tôi trả lời<input name="email" type="email" required maxlength="254" autocomplete="email" value="${esc(u?.email || '')}"></label>
          <label class="field">Chủ đề<select name="topic">${topics.map(([v, t]) => `<option value="${v}"${v === chosen ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
          <label class="field">Nội dung<textarea name="message" required minlength="10" maxlength="4000" rows="6" placeholder="Bạn cần chúng tôi giúp gì?"></textarea></label>
          <label class="tm-hp" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
          <p class="api-meta">Khi gửi, bạn đồng ý để chúng tôi dùng tên và email này để trả lời, theo <a href="?view=privacy">Chính sách bảo mật</a>.</p>
          <button class="button dark">Gửi tin nhắn</button><p class="api-meta" id="tm-contact-status" role="status"></p>
        </form>
        <aside class="api-card tm-contact-aside" id="tm-contact-aside"><h3>Cách khác</h3><p>Đang tải…</p></aside>
      </div></div>`);
    site.then(s => {
      main.querySelector('#tm-contact-aside').innerHTML = `<h3>Cách khác</h3>${s.contact_email ? `<p>Email: <a href="mailto:${esc(s.contact_email)}">${esc(s.contact_email)}</a></p>` : ''}
        <p>Câu hỏi thường gặp: <a href="?view=pricing">Bảng giá & FAQ</a>.</p><p>Muốn xoá dữ liệu? Bạn tự xoá được trong <a href="?view=profile">Tài khoản</a>.</p><p class="api-meta">${operator(s)}</p>`;
    });
    const form = main.querySelector('#tm-contact'), out = main.querySelector('#tm-contact-status');
    form.onsubmit = async e => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const data = Object.fromEntries(new FormData(form));
      const button = form.querySelector('button');
      button.disabled = true; out.textContent = 'Đang gửi…';
      try {
        await api('/api/v1/contact', data);
        form.outerHTML = `<div class="api-card tm-sent"><span class="tm-empty-ico" aria-hidden="true">✉️</span><h2>Đã gửi tin nhắn.</h2><p>Cảm ơn bạn. Chúng tôi sẽ trả lời qua ${esc(data.email)}.</p>${link('home', 'Về trang chủ')}</div>`;
      } catch (err) { out.textContent = err.message; button.disabled = false; }
    };
  }

  // --- terms -------------------------------------------------------------------------------
  if (route === 'terms') {
    site.then(s => doc('ĐIỀU KHOẢN', 'Điều khoản sử dụng.', `Có hiệu lực từ ${EFFECTIVE}. Khi dùng TravelMate, bạn đồng ý với các điều khoản dưới đây.`, [
      ['1. Dịch vụ', `<p>TravelMate (“chúng tôi”, do ${operator(s)} vận hành) là công cụ gợi ý lịch trình du lịch bằng AI. Lịch trình, chi phí và câu trả lời là <b>bản phác thảo tham khảo</b>, được tạo tự động từ dữ liệu mở và mô hình AI, có thể thiếu, cũ hoặc sai. Bạn tự kiểm tra giờ mở cửa, giá, thời tiết và quy định địa phương trước khi đi.</p><p>TravelMate không bán vé, không đặt phòng, không nhận thanh toán và không phải đại lý du lịch.</p>`],
      ['2. Tài khoản', list(['Bạn cung cấp tên và email đúng, giữ bí mật mật khẩu và chịu trách nhiệm về hoạt động trên tài khoản của mình.', 'Mỗi người dùng một tài khoản. Không chia sẻ, bán hoặc tạo tài khoản hàng loạt.', 'Bạn có thể xoá tài khoản bất cứ lúc nào trong mục Tài khoản.'])],
      ['3. Sử dụng hợp lệ', `<p>Bạn không được:</p>${list(['dùng công cụ tự động để gửi yêu cầu, vượt hoặc lách hạn mức sử dụng;', 'tấn công, dò quét, làm quá tải hoặc tìm cách truy cập trái phép hệ thống;', 'đăng nội dung vi phạm pháp luật, xúc phạm, quảng cáo, thư rác hoặc thông tin cá nhân của người khác trong đánh giá và tin nhắn;', 'dùng câu trả lời của AI để lừa đảo hoặc gây hại cho người khác.'])}<p>Hạn mức hiện tại: lập lịch ${limitText(s.daily_plans)}, Trợ lý AI ${limitText(s.daily_chats)} tin nhắn, làm mới lúc 0 giờ (giờ Việt Nam).</p>`],
      ['4. Nội dung bạn đăng', '<p>Bạn giữ quyền đối với đánh giá của mình và cho phép TravelMate hiển thị chúng trên trang địa điểm. Đánh giá được kiểm duyệt; chúng tôi có thể ẩn hoặc từ chối nội dung vi phạm mục 3.</p>'],
      ['5. Dữ liệu và ghi nguồn', '<p>Dữ liệu địa điểm © người đóng góp OpenStreetMap (giấy phép ODbL), thời tiết từ Open-Meteo, ảnh từ Wikimedia Commons theo giấy phép ghi dưới ảnh. Nhãn hiệu và tên địa điểm thuộc về chủ sở hữu tương ứng.</p>'],
      ['6. Giới hạn trách nhiệm', '<p>Dịch vụ được cung cấp “nguyên trạng”, miễn phí và có thể tạm gián đoạn. Trong phạm vi pháp luật cho phép, chúng tôi không chịu trách nhiệm về thiệt hại phát sinh từ việc dựa vào lịch trình, chi phí ước tính, dự báo thời tiết hay câu trả lời của AI.</p>'],
      ['7. Tạm khoá và chấm dứt', '<p>Chúng tôi có thể tạm khoá tài khoản vi phạm các điều khoản này. Bạn có thể ngừng dùng và xoá tài khoản bất cứ lúc nào.</p>'],
      ['8. Thay đổi điều khoản', '<p>Khi điều khoản thay đổi, ngày hiệu lực ở đầu trang được cập nhật. Thay đổi quan trọng sẽ được thông báo trên trang web.</p>'],
      ['9. Liên hệ', `<p>Câu hỏi về điều khoản: ${reach(s)}. Điều khoản này được hiểu theo pháp luật Việt Nam.</p>`],
    ]));
  }

  // --- privacy -----------------------------------------------------------------------------
  if (route === 'privacy') {
    site.then(s => doc('BẢO MẬT', 'Chính sách bảo mật.', `Có hiệu lực từ ${EFFECTIVE}. Trang này nói TravelMate thu thập dữ liệu gì, dùng để làm gì, chia sẻ với ai và quyền của bạn, theo Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.`, [
      ['1. Bên kiểm soát dữ liệu', `<p>${operator(s)}. Liên hệ về dữ liệu cá nhân: ${reach(s)} (chọn chủ đề “Quyền riêng tư”).</p>`],
      ['2. Dữ liệu chúng tôi thu thập', list([
        '<b>Tài khoản:</b> tên, email, mật khẩu (chỉ lưu dạng băm scrypt, không ai đọc được mật khẩu gốc), vai trò, ngày tạo, lần đăng nhập gần nhất, sở thích du lịch bạn tự nhập.',
        '<b>Nội dung bạn tạo:</b> yêu cầu lập lịch (điểm đến, ngày, số người, ngân sách, ghi chú), chuyến đi đã lưu, địa điểm yêu thích, đánh giá, lịch sử trò chuyện với Trợ lý AI.',
        '<b>Sử dụng:</b> số lượt lập lịch và tin nhắn AI mỗi ngày (để áp hạn mức); nhật ký thao tác quản trị.',
        '<b>Liên hệ:</b> tên, email và nội dung khi bạn gửi biểu mẫu liên hệ.',
        '<b>Kỹ thuật:</b> địa chỉ IP được dùng tạm thời trong bộ nhớ để chống dò mật khẩu và thư rác; máy chủ có thể ghi nhật ký truy cập.'])
        + '<p>Chúng tôi <b>không</b> thu thập vị trí GPS, thông tin thanh toán, và không dùng cookie quảng cáo hay công cụ theo dõi của bên thứ ba.</p>'],
      ['3. Cookie và lưu trữ trên trình duyệt', list([
        '<b>Cookie phiên</b> (HttpOnly, bắt buộc): giữ bạn đăng nhập, hết hạn sau 30 ngày hoặc khi đăng xuất.',
        '<b>localStorage:</b> tên, email và vai trò của tài khoản đang đăng nhập, để trang hiện đúng khi mở lại; bị xoá khi bạn đăng xuất.',
        '<b>sessionStorage:</b> thông tin chuyến đi bạn đang nhập, lịch trình đang xem, kết quả tìm kiếm và cuộc trò chuyện hiện tại; mất khi đóng thẻ.'])
        + '<p>Vì chỉ dùng lưu trữ cần thiết cho dịch vụ, TravelMate không hiện hộp chấp nhận cookie.</p>'],
      ['4. Mục đích sử dụng', list(['Tạo lịch trình, trả lời câu hỏi và lưu chuyến đi theo yêu cầu của bạn.', 'Đăng nhập, khôi phục mật khẩu và bảo vệ tài khoản.', 'Áp hạn mức, chống lạm dụng, kiểm duyệt đánh giá.', 'Trả lời tin nhắn liên hệ và cải thiện dịch vụ.'])
        + '<p>Chúng tôi không bán dữ liệu cá nhân và không dùng nó cho quảng cáo.</p>'],
      ['5. Bên thứ ba xử lý dữ liệu', list([
        '<b>Google (Gemini API):</b> nội dung yêu cầu lập lịch và tin nhắn trò chuyện được gửi tới Google để mô hình AI xử lý. Tên, email và mật khẩu của bạn không được gửi. Đừng ghi thông tin nhạy cảm vào ghi chú hay tin nhắn.',
        '<b>Photon, Overpass (OpenStreetMap) và Open-Meteo:</b> nhận tên điểm đến, từ khoá tìm kiếm và toạ độ để trả về địa điểm, thời tiết.',
        '<b>Wikimedia:</b> trình duyệt của bạn tải ảnh trực tiếp từ máy chủ Wikimedia.',
        '<b>Nhà cung cấp máy chủ và cơ sở dữ liệu</b> lưu trữ dữ liệu thay chúng tôi; <b>dịch vụ email</b> gửi thư đặt lại mật khẩu khi bạn yêu cầu.'])
        + '<p>Một số nhà cung cấp đặt máy chủ ngoài Việt Nam, nên dữ liệu có thể được chuyển ra nước ngoài để xử lý.</p>'],
      ['6. Thời gian lưu', list(['Dữ liệu tài khoản và nội dung bạn tạo: đến khi bạn xoá hoặc xoá tài khoản.', 'Phiên đăng nhập: 30 ngày. Liên kết đặt lại mật khẩu: 30 phút.', 'Tin nhắn liên hệ: đến khi được xử lý và xoá, hoặc khi bạn xoá tài khoản.'])],
      ['7. Quyền của bạn', list(['Xem và sửa tên, sở thích, mật khẩu trong <a href="?view=profile">Tài khoản</a>.', 'Xoá từng chuyến đi, cuộc trò chuyện, đánh giá; hoặc xoá toàn bộ tài khoản — chuyến đi, yêu thích, đánh giá, trò chuyện, hạn mức và tin nhắn liên hệ của bạn bị xoá theo.', 'Yêu cầu bản sao dữ liệu, rút lại đồng ý hoặc khiếu nại qua biểu mẫu liên hệ; chúng tôi trả lời trong thời hạn pháp luật quy định.'])],
      ['8. Bảo mật', '<p>Kết nối dùng HTTPS; mật khẩu băm bằng scrypt có muối riêng; mã phiên và mã đặt lại mật khẩu chỉ lưu dạng băm SHA-256; đăng nhập có giới hạn số lần thử. Không hệ thống nào an toàn tuyệt đối; nếu có sự cố lộ dữ liệu, chúng tôi sẽ thông báo theo quy định.</p>'],
      ['9. Trẻ em', '<p>TravelMate dành cho người từ 16 tuổi. Người dưới 16 tuổi cần cha mẹ hoặc người giám hộ đồng ý khi tạo tài khoản.</p>'],
      ['10. Thay đổi chính sách', '<p>Khi chính sách thay đổi, ngày hiệu lực ở đầu trang được cập nhật; thay đổi quan trọng sẽ được thông báo trên trang web.</p>'],
    ]));
  }

  // --- admin: contact inbox ------------------------------------------------------------------
  if (route === 'admin-messages') {
    const u = user();
    if (!u) { render(tm.loginGate('Đăng nhập bằng tài khoản quản trị để xem tin nhắn.', '?view=admin-messages')); return; }
    if (u.role !== 'admin') { render(tm.emptyState('🔒', 'Chỉ quản trị viên mới xem được trang này.', '', link('home', 'Về trang chủ', 'button dark'))); return; }
    const topicLabel = {support: 'Hỗ trợ', feedback: 'Góp ý', partner: 'Hợp tác', privacy: 'Quyền riêng tư', other: 'Khác'};
    const tabs = [['admin', 'Tổng quan'], ['admin-users', 'Người dùng'], ['admin-places', 'Địa điểm'], ['moderation', 'Kiểm duyệt'], ['admin-messages', 'Liên hệ']];
    const main = render(`<div class="tm-head tm-admin-head"><div class="eyebrow">KHÔNG GIAN QUẢN TRỊ</div><h1>Tin nhắn liên hệ.</h1></div>
      <div class="tm-tabs">${tabs.map(([v, t]) => `<a class="button outline ${v === 'admin-messages' ? 'active' : ''}" href="?view=${v}">${t}</a>`).join('')}</div>
      <div class="tm-row tm-filter"><label>Hiện <select id="tm-msg-filter"><option value="new">Chưa xử lý</option><option value="done">Đã xử lý</option><option value="">Tất cả</option></select></label></div>
      <div id="tm-messages"><p class="tm-loading-line">Đang tải…</p></div>`);
    const box = main.querySelector('#tm-messages'), filter = main.querySelector('#tm-msg-filter');
    const when = t => new Date(t * 1000).toLocaleString('vi-VN', {dateStyle: 'short', timeStyle: 'short'});
    const load = () => get('/api/v1/admin/messages' + (filter.value ? `?status=${filter.value}` : '')).then(items => {
      box.innerHTML = items.length ? items.map(m => `<article class="api-card tm-message"><div class="tm-row"><span class="tm-badge ${m.status === 'new' ? 'pending' : 'approved'}">${m.status === 'new' ? 'Chưa xử lý' : 'Đã xử lý'}</span><span class="eyebrow">${esc(topicLabel[m.topic] || m.topic)} · ${when(m.created_at)}</span></div>
        <h3>${esc(m.name)} · <a href="mailto:${esc(m.email)}">${esc(m.email)}</a>${m.user_id ? ' <span class="api-meta">(có tài khoản)</span>' : ''}</h3><p class="tm-message-text">${esc(m.text)}</p>
        <div class="tm-row"><a class="button dark tm-small" href="mailto:${esc(m.email)}?subject=${encodeURIComponent('TravelMate: trả lời tin nhắn của bạn')}">Trả lời qua email</a>
        <button type="button" class="button outline tm-small" data-status="${m.status === 'new' ? 'done' : 'new'}" data-id="${esc(m.id)}">${m.status === 'new' ? 'Đánh dấu đã xử lý' : 'Đánh dấu chưa xử lý'}</button>
        <button type="button" class="button outline tm-small tm-danger-text" data-remove="${esc(m.id)}">Xoá</button></div></article>`).join('')
        : tm.emptyState('📭', 'Không có tin nhắn nào.', filter.value === 'new' ? 'Mọi tin nhắn đã được xử lý.' : '');
    }).catch(err => { box.innerHTML = `<p class="api-error">${esc(err.message)}</p>`; });
    filter.onchange = load;
    box.onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      try {
        if (b.dataset.status) { await api(`/api/v1/admin/messages/${encodeURIComponent(b.dataset.id)}`, {status: b.dataset.status}, undefined, 'PATCH'); notify('Đã cập nhật.'); }
        if (b.dataset.remove && await dialog({title: 'Xoá tin nhắn này?', text: 'Tin nhắn sẽ bị xoá vĩnh viễn.', ok: 'Xoá', danger: true})) { await api(`/api/v1/admin/messages/${encodeURIComponent(b.dataset.remove)}`, null, undefined, 'DELETE'); notify('Đã xoá tin nhắn.'); }
        load();
      } catch (err) { notify(err.message); }
    };
    load();
  }

  // --- account page: today's AI quota ----------------------------------------------------------
  const grid = document.querySelector('.tm-profile-grid');
  if (route === 'profile' && grid && user()) {
    const card = document.createElement('section');
    card.className = 'api-card tm-usage';
    card.innerHTML = '<h3>Hạn mức AI hôm nay</h3><p>Đang tải…</p>';
    grid.prepend(card);
    const bar = (label, u) => u.limit === null
      ? `<div class="tm-usage-row"><span>${label}</span><b>${u.used} · không giới hạn</b></div>`
      : `<div class="tm-usage-row"><span>${label}</span><b>${u.used}/${u.limit}</b></div><div class="tm-usage-bar" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="${u.limit}" aria-valuenow="${u.used}"><i style="width:${Math.min(100, Math.round(u.used / u.limit * 100))}%"></i></div>`;
    get('/api/v1/me/usage').then(u => {
      card.innerHTML = `<h3>Hạn mức AI hôm nay</h3>${bar('Lập lịch trình', u.plan)}${bar('Tin nhắn Trợ lý AI', u.chat)}<p class="api-meta">Làm mới lúc 0 giờ (giờ Việt Nam). <a href="?view=pricing">Vì sao có hạn mức?</a></p>`;
    }).catch(() => card.remove());
  }
})();
