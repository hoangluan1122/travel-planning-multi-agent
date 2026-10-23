// UI-only regression with recorded real responses; never reported as a live source test.
const {chromium} = require('C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const read = p => JSON.parse(fs.readFileSync(p, 'utf8'));
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const empty = read('evaluation/fix-verification-20261022T182826Z/api/13.json');
    const expanded = read('evaluation/fix-verification-20261022T183050Z/api/01.json');
    empty.applied_radius_m=5000; empty.suggested_radius_m=10000;
    let calls=0;
    await page.route('**/api/v1/places/live', async route => {
      calls++;
      const query = route.request().postDataJSON();
      assert.equal(query.radius_m, calls===1 ? 5000 : 10000);
      if (calls===2) assert.equal(query.location_id, 'photon:node/3989371457');
      await route.fulfill({json:calls===1 ? empty : expanded});
    });
    await page.goto('http://127.0.0.1:8001/');
    await page.locator('#destination').fill('Fansipan');
    await page.locator('#radius').selectOption('5000');
    await page.locator('#submit').click();
    const button = page.getByRole('button',{name:'Tìm lại trong 10 km (đường chim bay)'});
    await button.waitFor();
    assert.equal(calls,1,'No automatic expansion');
    await button.click();
    await page.locator('#cards .place').first().waitFor();
    assert.equal(await page.locator('#cards .place').count(),5);
    assert.equal(await page.locator('#radius').inputValue(),'10000');
    const response = {...empty,status:'needs_location', resolved_location:null, suggested_radius_m:null,
      location_options:read('evaluation/locality-fixes-20261022T182507Z/results.json').Fansipan.choices};
    await page.unroute('**/api/v1/places/live');
    await page.route('**/api/v1/places/live', route=>route.fulfill({json:response}));
    await page.locator('#submit').click();
    await page.locator('#location-field').waitFor();
    assert.match(await page.locator('#location-choice').innerText(), /Trạm cáp treo/);
    assert.match(await page.locator('#location-choice').innerText(), /Đỉnh núi/);
    assert.equal(await page.locator('#location-choice').getAttribute('data-resolved'),null);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No mobile overflow');
    assert.deepEqual(errors,[]);
    await page.screenshot({path:'evaluation/locality-fix-ui-mobile.png',fullPage:true});
    console.log('PASS: explicit radius expansion, preserved identity, role labels, stale selection cleared, mobile layout, no JS errors');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
