const {chromium}=require('C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({reducedMotion:'reduce'});const errors=[],results=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!=='http://127.0.0.1:8100')return r.abort();if(u.pathname==='/admin/usage/monthly/page')return r.fulfill({contentType:'text/html',body:fs.readFileSync('runtime/usage-subadmin.html','utf8')});return r.continue();});
 for(const theme of ['light','dark'])for(const width of [390,1440,1920]){
  await page.setViewportSize({width,height:1000});await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);await page.goto('http://127.0.0.1:8100/admin/usage/monthly/page');
  assert.equal(await page.locator('thead [data-day]').count(),31);assert.equal(await page.locator('.usage-edit-btn,.usage-override,.usage-adjusted,#usage-modal,[data-real]').count(),0);
  assert.equal(await page.locator('.usage-total-cell[title*="真实"]').count(),0);assert.equal(await page.locator('.usage-table tbody tr').count(),25);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  if(width===390){await page.click('[data-usage-scroll="1"]');assert.ok(await page.locator('.usage-table-wrap').evaluate(el=>el.scrollLeft>0));}
  await page.addScriptTag({path:'runtime/axe.min.js'});const violations=await page.evaluate(async()=>(await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}})).violations.map(v=>v.id));assert.deepEqual(violations,[]);
  await page.screenshot({path:`runtime/guidelines_review/usage-subadmin-${theme}-${width}.png`,fullPage:true});results.push({theme,width,passed:true});
 }
 assert.deepEqual(errors,[]);fs.writeFileSync('runtime/guidelines_review/usage-subadmin.json',JSON.stringify({results,errors,passed:true},null,2));await browser.close();console.log(JSON.stringify({views:results.length,passed:true}));
})().catch(e=>{console.error(e);process.exit(1)});
