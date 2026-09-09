const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8100',out=path.resolve('runtime/lumora_review');
(async()=>{
const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference',recordVideo:{dir:path.join(out,'motion'),size:{width:1440,height:1000}}});const page=await context.newPage();page.on('dialog',dialog=>dialog.accept());const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
for(const theme of ['light','dark'])for(const width of [390,1440]){
 await page.setViewportSize({width,height:1000});await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);
 for(const route of ['/admin/provider-keys/page','/admin/reference-images/page','/admin/risk-control/page','/admin/quota-plans/page','/app/reference-images/page']){
  await page.goto(base+route);await page.locator('.wb-create-launch').click();await page.waitForTimeout(260);const dialog=page.locator('dialog[open]');const b=await dialog.boundingBox();assert.ok(b.x>=-1&&b.x+b.width<=width+1);assert.equal(await dialog.evaluate(el=>el.scrollWidth>el.clientWidth+2),false);
  await page.screenshot({path:path.join(out,route.replaceAll('/','_')+'-drawer-'+theme+'-'+width+'.png')});await page.keyboard.press('Escape');await page.waitForTimeout(200);
  for(let i=0;i<3;i++){await page.locator('.wb-create-launch').click();await page.keyboard.press('Escape');}
  assert.equal(await page.locator('dialog[open]').count(),0);checks.push({route,theme,width,drawer:true});
 }
}
await page.setViewportSize({width:1440,height:1000});
for(const route of ['/admin/settings/page','/admin/users/2/page']){
 await page.goto(base+route);for(const tab of await page.locator('.tab-button').all()){await tab.click();await page.waitForTimeout(130);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);}checks.push({route,allPanels:true});
}
for(const theme of ['light','dark'])for(const width of [375,768,1440]){
 await page.setViewportSize({width,height:1000});await page.goto(base+'/app/jobs/101/page?state=failed');await page.evaluate(t=>{document.documentElement.dataset.theme=t;document.querySelector('#job-remote').textContent='remote-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.repeat(6);document.querySelector('.wb-detail-fields>div:nth-child(2) dd').textContent='模型名称-ABCDEFGHIJKLMNOPQRSTUVWXYZ'.repeat(5);document.querySelector('#job-error').textContent='示例长错误：图片下载失败，需要检查素材来源。'.repeat(16);},theme);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);assert.equal(await page.locator('.wb-detail-fields dd').evaluateAll(nodes=>nodes.some(el=>el.getBoundingClientRect().width<140)),false);await page.screenshot({path:path.join(out,`detail-long-${theme}-${width}.png`),fullPage:true});checks.push({theme,width,longFields:true});
}
for(const route of ['/admin/settings/page','/admin/provider-keys/page','/app/library/page','/admin/users/2/page']){await page.setViewportSize({width:720,height:500});await page.goto(base+route);await page.evaluate(()=>document.body.style.zoom='2');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);checks.push({route,cssZoom:2});}
await context.close();
// Fake clock and synthetic visibility isolate the polling state machine without paid upstream calls.
const polling=await browser.newContext({viewport:{width:1440,height:900}});const poll=await polling.newPage();await poll.clock.install();let calls=0,mode='active';
await poll.route('**/app/job-batches/12',route=>{calls++;if(mode==='error')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模拟网络异常'})});return route.fulfill({contentType:'application/json',body:JSON.stringify({batch:{state_label:mode==='done'?'已完成':'进行中',summary:'模拟批次',completed_count:mode==='done'?2:1,active_count:mode==='done'?0:1,failed_count:0,downloadable_count:mode==='done'?2:1},jobs:[101,102].map(id=>({id,status:mode==='done'?'completed':'polling',status_label:'处理中',progress:50,queue_text:'处理中',output_file:mode==='done'?{id:9}:null}))})});});
await poll.goto(base+'/app/job-batches/12/result');await poll.waitForFunction(()=>document.querySelector('#batch-refresh-state').textContent==='自动更新中');const origin=await poll.evaluate(()=>performance.timeOrigin);await poll.locator('.prompt-preview-cell summary').first().click();await poll.evaluate(()=>scrollTo(0,100));const scroll=await poll.evaluate(()=>scrollY);
await poll.clock.fastForward(8100);await poll.waitForFunction(()=>document.querySelector('#batch-refresh-state').textContent==='自动更新中');assert.equal(await poll.evaluate(()=>performance.timeOrigin),origin);assert.equal(await poll.evaluate(()=>scrollY),scroll);assert.equal(await poll.locator('.prompt-preview-cell details[open]').count(),1);
mode='error';await poll.clock.fastForward(8100);await poll.waitForFunction(()=>document.querySelector('#batch-refresh-state').textContent.includes('失败'));const failed=calls;await poll.clock.fastForward(8000);assert.equal(calls,failed);
await poll.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});await poll.clock.fastForward(60000);assert.equal(calls,failed);
mode='done';await poll.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});await poll.waitForFunction(()=>document.querySelector('#batch-refresh-state').textContent.includes('已结束'));const ended=calls;await poll.clock.fastForward(60000);assert.equal(calls,ended);assert.equal(await poll.locator('[data-job-download]:not(.hidden)').count(),2);checks.push({polling:'partial update, preserved disclosure/scroll, retry backoff, synthetic visibility pause, stop on completion',calls});
await polling.close();await browser.close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'stress.json'),JSON.stringify({checks,errors,passed:true,limits:['CSS zoom, not browser chrome zoom','Visibility and time simulated for polling','No physical device verification']},null,2));console.log(JSON.stringify({checks:checks.length,errors,passed:true}));
})().catch(error=>{console.error(error);process.exit(1)});
