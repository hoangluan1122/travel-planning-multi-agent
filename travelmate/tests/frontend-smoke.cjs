// Run with the bundled Node runtime; target a running demo API using BASE_URL.
const {chromium}=require('C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{
    const page=await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const base=(process.env.BASE_URL||'http://127.0.0.1:8012')+'/ui/travelmate-v2/index.html';
    await page.goto(base+'?view=create');
    await page.locator('#api-health').filter({hasText:'Backend đã kết nối'}).waitFor();
    await page.locator('[name=notes]').fill('Đi chậm');
    const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/v1/plans/preview'));
    await page.locator('[data-form=create] button').click();
    const response=await responsePromise;
    assert.equal(response.status(),200);
    assert.equal(response.request().postDataJSON().notes,'Đi chậm');
    await page.waitForURL('**?view=plan');
    const result=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('tm-plans'))[0].result);
    await page.getByText('Mã yêu cầu: '+result.request_id,{exact:true}).waitFor();
    await page.getByRole('link',{name:'Xem chi tiết ngày →'}).first().click();
    await page.locator('#connected-view h3').filter({hasText:result.places[0].name}).waitFor();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Mobile overflow');
    await page.screenshot({path:'frontend-mobile-proof.png',fullPage:true});
    await page.goto(base+'?view=explore');
    await page.locator('#api-search').waitFor();
    await page.locator('#api-search button').click();
    await page.locator('#search-status').filter({hasText:'Tìm thấy'}).waitFor();
    await page.route('**/api/v1/plans/preview',r=>r.fulfill({status:401,contentType:'application/json',body:'{"detail":"Invalid API token"}'}));
    await page.goto(base+'?view=loading');
    await page.getByRole('alert').filter({hasText:'Token truy cập'}).waitFor();
    assert.deepEqual(errors,[]);
    console.log('PASS: form/API payload, actual response render, day navigation, mobile overflow, place search, 401 recovery, no JS errors');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
