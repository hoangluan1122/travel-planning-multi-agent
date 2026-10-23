'use strict';
const $ = id => document.getElementById(id);
let lastResult = null;
let offset = 0;
let lastQuery = null;
let regions = [];
function node(tag, text, cls) { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; }
function stamp(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Chưa có thời điểm' : d.toLocaleString('vi-VN'); }
function status(text, error = false) { $('status').textContent = text; $('status').dataset.error = String(error); }
function render(data) {
  lastResult = data; $('cards').replaceChildren();
  for (const place of data.places || []) {
    const card = node('article', '', 'place');
    card.append(node('h3', place.name), node('p', place.address || 'Nguồn chưa cung cấp địa chỉ.'));
    card.append(node('p', `Tọa độ: ${place.latitude}, ${place.longitude}`, 'coords'));
    card.append(node('p', `Lấy từ nguồn: ${stamp(place.fetched_at)}`, 'small'));
    const info = data.place_metadata?.[place.id];
    if (info) card.append(node('p', `${info.spatial_filter === 'reference_polygon' ? 'Trong ranh giới tham chiếu · ' : ''}${(info.distance_m / 1000).toFixed(2)} km từ điểm tham chiếu (đường chim bay) · ${info.address_precision === 'street' ? 'Có tên đường từ nguồn' : info.address_precision === 'missing' ? 'Thiếu địa chỉ' : 'Địa chỉ mới có mức khu vực'} · ${info.cache_hit ? 'Bộ nhớ đệm ≤ 5 phút' : 'Vừa truy vấn nguồn'}`, 'small'));
    if (info?.phone) card.append(node('p', `Điện thoại từ nguồn: ${info.phone}`));
    if (place.opening_hours_raw) card.append(node('p', `Giờ hoạt động từ nguồn: ${place.opening_hours_raw}`));
    const source = node('a', 'Xem bản ghi nguồn ↗');
    try { const url = new URL(place.source_url); if (url.protocol === 'https:') source.href = url.href; } catch (_) {}
    source.target = '_blank'; source.rel = 'noopener noreferrer'; card.append(source);
    if (place.attribution) card.append(node('p', place.attribution, 'small'));
    card.append(node('p', 'Chưa xác minh giá, ảnh, tình trạng hoạt động/phòng trống. Tọa độ không bảo đảm là cửa vào.', 'notice'));
    $('cards').append(card);
  }
  if (!(data.places || []).length) $('cards').append(node('div', data.status === 'needs_location' ? 'Chọn địa danh ở bên trái rồi bấm chạy lại.' : data.status === 'no_results' ? 'Chưa có địa điểm khớp trong chỉ mục và phạm vi này. Thử tăng bán kính hoặc bỏ từ khóa; không có nghĩa khu vực không có địa điểm.' : 'Nguồn dữ liệu chưa truy cập được. Xem chi tiết xử lý bên dưới.', 'empty'));
  if (data.status === 'no_results' && data.suggested_radius_m && lastQuery) {
    const expand = node('button', `Tìm lại trong ${data.suggested_radius_m / 1000} km (đường chim bay)`);
    expand.type = 'button';
    expand.addEventListener('click', () => {
      $('radius').value = String(data.suggested_radius_m);
      runSearch({...lastQuery, radius_m:data.suggested_radius_m, location_id:data.resolved_location.id, offset:0});
    });
    $('cards').append(expand);
  }
  if (data.status === 'needs_location') {
    $('location-field').hidden = false;
    $('location-choice').replaceChildren(node('option', 'Chọn địa danh…'));
    $('location-choice').firstChild.value = '';
    for (const p of data.location_options || []) { const option = node('option', p.scope !== 'nearby' ? `${p.name} · Ranh giới ${p.boundary_version} · ${p.historical ? 'Khu vực cũ' : 'Danh mục 34 tỉnh/thành'}` : `${p.name} · ${localityType(p.feature_code)} · ${p.admin2} · ${p.admin1} (${p.latitude}, ${p.longitude})${p.coordinate_kind === 'geometry_center' ? ' · Tâm khu vực, không phải cửa vào' : ''}`); option.value = p.id; $('location-choice').append(option); }
  }
  if (data.status === 'needs_location') delete $('location-choice').dataset.resolved;
  if (data.resolved_location) { $('location-choice').dataset.resolved = data.resolved_location.id; $('radius').disabled = data.resolved_location.scope !== 'nearby'; }
  if (data.status === 'needs_location' && data.location_options?.length) $('radius').disabled = data.location_options.every(p => p.scope !== 'nearby');
  $('pagination').hidden = !(data.has_more || data.offset > 0);
  $('previous').disabled = data.offset === 0; $('next').disabled = !data.has_more;
  $('run-info').textContent = `Mã yêu cầu: ${data.request_id} · ${stamp(data.completed_at)} · ${data.execution_mode === 'adk_llm' ? 'ADK + LLM' : 'Workflow công cụ, không gọi LLM'}`;
  $('trace').replaceChildren(...(data.trace || []).map(event => node('li', `${event.message} (${event.record_count} bản ghi)`)));
  $('warnings').replaceChildren(...(data.warnings || []).map(warning => node('li', warning)));
  $('json').textContent = JSON.stringify(data, null, 2);
  for (const id of ['download','trace-panel','json-panel','warnings-panel']) $(id).hidden = false;
  const count = (data.places || []).length;
  const area = data.resolved_location;
  if (area?.scope !== 'nearby' && area?.attribution) $('warnings').prepend(node('li', `Nguồn ranh giới: ${area.attribution}. Phiên bản: ${area.boundary_version}.`));
  status(count ? `${area ? `${area.name}, ${area.admin1} · ` : ''}Hiển thị ${data.offset + 1}–${data.offset + count} / ${data.candidate_count} ứng viên đã lấy (không phải toàn bộ khu vực). Trạng thái: ${data.status}.` : data.status === 'needs_location' ? 'Cần xác nhận địa danh trước khi tìm kiếm.' : `Chưa có kết quả. Trạng thái: ${data.status}.`, !count && data.status !== 'needs_location');
}
async function connect() {
  try {
    const r = await fetch('/health'); if (!r.ok) throw new Error('health'); const data = await r.json();
    $('engine').textContent = data.mode === 'adk_llm' ? 'Dữ liệu thật · ADK + LLM' : 'Dữ liệu thật · Workflow công cụ';
    $('token-field').hidden = !data.token_required;
    const regionResponse = await fetch('/api/v1/places/regions');
    if (regionResponse.ok) {
      regions = (await regionResponse.json()).regions;
      for (const historical of [false, true]) {
        const group = document.createElement('optgroup'); group.label = historical ? '63 khu vực cũ · Ranh giới tham chiếu 2020' : '34 tỉnh/thành · Bộ tham chiếu 2026';
        for (const region of regions.filter(r => r.historical === historical).sort((a,b) => a.name.localeCompare(b.name, 'vi'))) { const option = node('option', region.name); option.value = region.id; group.append(option); }
        $('region-browser').append(group);
      }
    }
  } catch (_) { $('engine').textContent = 'Chưa kết nối máy chủ'; status('Không kết nối được máy chủ Place Agent.', true); }
}
async function runSearch(query) {
  if ($('submit').disabled) return;
  lastQuery = query;
  $('submit').disabled = true; lastResult = null; $('download').hidden = true;
  $('cards').replaceChildren(node('div', 'Đang tìm nguồn và đọc website…', 'empty'));
  for (const id of ['trace-panel','json-panel','warnings-panel']) $(id).hidden = true;
  $('run-info').textContent = ''; status('Agent đang tìm kiếm và kiểm tra dữ liệu nguồn…');
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 145000);
  try {
    const headers = {'Content-Type':'application/json'};
    if ($('token').value) headers.Authorization = `Bearer ${$('token').value}`;
    const r = await fetch('/api/v1/places/live', {method:'POST', headers, signal:controller.signal,
      body:JSON.stringify(query)});
    const data = await r.json();
    if (data.request_id && Array.isArray(data.places)) { render(data); return; }
    const detail = typeof data.detail === 'string' ? data.detail : 'Kiểm tra địa danh và dữ liệu đầu vào.';
    throw new Error(`${r.status}: ${detail}`);
  } catch (error) {
    $('cards').replaceChildren(node('div', 'Lượt chạy chưa có kết quả để xuất.', 'empty'));
    status(error.name === 'AbortError' ? 'Đã hết thời gian chờ máy chủ. Không có dữ liệu thay thế.' : `Không hoàn tất: ${error.message}`, true);
  } finally { clearTimeout(timer); $('submit').disabled = false; }
}
$('search-form').addEventListener('submit', event => {
  event.preventDefault(); offset = 0;
  runSearch({destination:$('destination').value.trim(), keyword:$('keyword').value.trim(), limit:Number($('limit').value), category:$('category').value, radius_m:Number($('radius').value), search_scope:$('scope').value, location_id:$('location-choice').value || $('location-choice').dataset.resolved || null, offset});
});
function clearLocation() { $('location-field').hidden = true; $('location-choice').replaceChildren(); delete $('location-choice').dataset.resolved; $('radius').disabled = ['area','country'].includes($('scope').value); }
$('destination').addEventListener('input', () => { clearLocation(); $('region-browser').value = ''; });
$('scope').addEventListener('change', () => {
  clearLocation(); $('region-browser').value = '';
  $('region-browser-field').hidden = $('scope').value !== 'area';
  $('radius').disabled = ['area', 'country'].includes($('scope').value);
  if ($('scope').value === 'country') $('destination').value = 'Việt Nam';
  $('destination').readOnly = $('scope').value === 'country';
});
$('region-browser').addEventListener('change', () => {
  clearLocation(); const region = regions.find(r => r.id === $('region-browser').value);
  if (!region) return;
  // Submit the exact catalog name, not the explanatory historical suffix.
  $('destination').value = region.name.replace(/ \(khu vực cũ, ranh giới 2020\)$/, '').replace(/^(Tỉnh|Thành phố) /, '');
  $('location-choice').dataset.resolved = region.id;
});
for (const [id, direction] of [['previous', -1], ['next', 1]]) $(id).addEventListener('click', () => { if (!lastQuery || $('submit').disabled) return; offset = Math.max(0, lastQuery.offset + direction * lastQuery.limit); runSearch({...lastQuery, location_id:lastResult?.resolved_location?.id || lastQuery.location_id, offset}); });
$('download').addEventListener('click', () => {
  if (!lastResult) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastResult,null,2)],{type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `place-agent-${lastResult.request_id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
connect();

function localityType(code) {
  const labels = {city:'Thành phố',town:'Thị trấn',village:'Làng/xã',hamlet:'Thôn',quarter:'Khu dân cư',suburb:'Khu dân cư',peak:'Đỉnh núi',station:'Trạm cáp treo',national_park:'Vườn quốc gia',nature_reserve:'Khu bảo tồn',theme_park:'Khu vui chơi',attraction:'Điểm tham quan',island:'Đảo',park:'Công viên',PPLA2:'Điểm hành chính cấp huyện',PPLA:'Điểm hành chính',PPL:'Khu dân cư'};
  return labels[code?.replace('OSM:', '')] || 'Địa danh';
}
