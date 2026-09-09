const {chromium} = require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const base = process.env.LUMORA_LAYOUT_URL || 'http://127.0.0.1:8112';
const out = 'runtime/fixed-workspace';
const measure = page => page.evaluate(() => {
  const rect = selector => {const r = document.querySelector(selector).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height}};
  return {viewport:innerHeight,width:innerWidth,documentHeight:document.documentElement.scrollHeight,documentWidth:document.documentElement.scrollWidth,sidebar:rect('.wb-shell>.wb-sidebar'),footer:rect('.wb-submit'),editor:rect('.wb-editor'),surface:rect('.glass-workbench'),settings:rect('.wb-settings'),quota:getComputedStyle(document.querySelector('.wb-available')).display};
});
function check(m) {
  assert.ok(m.documentHeight <= m.viewport + 1, `page scrolls: ${JSON.stringify(m)}`);
  assert.ok(m.documentWidth <= m.width + 1, 'horizontal page overflow');
  assert.ok(m.viewport - m.footer.bottom <= 13 && m.footer.bottom <= m.viewport, 'footer not at viewport bottom');
  assert.ok(m.surface.bottom <= m.footer.top, 'surface overlaps footer');
  assert.notEqual(m.quota,'none');
  if(m.width >= 768) {assert.equal(m.sidebar.top,12);assert.ok(m.editor.height >= 60,'editor collapsed');}
}
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({ignoreDefaultArgs:['--hide-scrollbars']}); const results=[];
  try {
    for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[1024,768],[768,1024],[844,390],[375,812],[390,844],[720,450]]) {
      for(const theme of ['light','dark']) {
        const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
        const errors=[];page.on('pageerror',e=>errors.push(e.message));
        await page.route('**/app/jobs/batch**',route=>route.abort());
        await page.goto(base+'/app');
        await page.evaluate(t=>document.documentElement.setAttribute('data-theme',t),theme);
        assert.equal(await page.locator('.mature-create-heading').count(),0);
        const initial=await measure(page);check(initial);
        await page.screenshot({path:`${out}/${width}x${height}-${theme}-initial.png`});
        await page.locator('#batch-import-toggle').click();
        await page.locator('#batch-import-textarea').fill(Array.from({length:100},(_,i)=>`Layout regression prompt ${i+1}`).join('\n\n'));
        await page.locator('#batch-import-mode').selectOption('replace');
        await page.locator('#batch-import-apply').click();
        const confirm=page.locator('.confirm-dialog[open] button').last();
        if(await confirm.isVisible()) await confirm.click();
        await page.waitForFunction(()=>document.querySelectorAll('[data-prompt-card]').length===100);
        await page.locator('[name=prompts]').last().focus();
        const after=await measure(page);check(after);
        assert.equal(after.footer.top,initial.footer.top,'import moved footer');
        if(width>=768) {assert.equal(after.sidebar.top,initial.sidebar.top);assert.equal(after.settings.top,initial.settings.top);}
        const visible=await page.locator('[name=prompts]').last().evaluate(el=>{const r=el.getBoundingClientRect(),foot=document.querySelector('.wb-submit').getBoundingClientRect();return r.top<foot.top&&r.bottom>0});
        assert.ok(visible,'last prompt unreachable');
        if(width>=1200){await page.locator('[data-collapse-nav]').click();check(await measure(page));await page.locator('[data-collapse-nav]').click();}
        if(width<768){await page.locator('[data-open-nav]').click();await page.locator('.wb-mobile-nav-dialog[open]').waitFor();await page.keyboard.press('Escape');}
        await page.screenshot({path:`${out}/${width}x${height}-${theme}.png`});
        results.push({width,height,theme,initial,after,errors});
        assert.deepEqual(errors,[]);
        console.log(`${width}x${height} ${theme}: PASS`);
        await page.close();
      }
    }
    // Shared sidebar must stay put on long ordinary pages, including admin navigation.
    for(const route of ['/app/jobs/page','/admin/users/page','/admin/settings/page']) {
      const page=await browser.newPage({viewport:{width:1440,height:768}});
      await page.goto(base+route);
      const before=await page.locator('.wb-shell>.wb-sidebar').boundingBox();
      await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
      const after=await page.locator('.wb-shell>.wb-sidebar').boundingBox();
      assert.deepEqual(after,before,`sidebar moved on ${route}`);
      await page.locator('.wb-nav a').last().focus();
      const bottom=await page.locator('.wb-sidebar-bottom').boundingBox();
      assert.ok(bottom.y+bottom.height<=768,'collapse button outside viewport');
      results.push({route,sidebarStable:true});
      console.log(`${route}: sidebar PASS`);
      await page.close();
    }
  } finally {fs.writeFileSync(`${out}/measurements.json`,JSON.stringify(results,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
