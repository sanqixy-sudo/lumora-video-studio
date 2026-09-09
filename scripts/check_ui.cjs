/* Offline browser acceptance: every application request stays on localhost or is mocked. */
const { chromium } = require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs'); const path = require('node:path'); const assert = require('node:assert/strict');
const out = path.resolve('runtime/ui_review'); fs.mkdirSync(out,{recursive:true});
const base = 'http://127.0.0.1:8099';
(async () => {
 const browser = await chromium.launch({headless:true});
 const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const request=route.request(), url=new URL(request.url());
  if(url.origin!==base) return route.abort();
  if(/^\/(app|admin)\/jobs\/\d+$/.test(url.pathname)) return route.fulfill({json:{job:{id:101,status:'polling',status_label:'查询中',progress:62,queue_text:'运行中',remote_task_id:'mock-task',download_attempts:0,output_file:null},events:[],api_calls:[],can_redownload:false,can_resume:false,can_pause:true}});
  return route.continue();
 });
 await page.goto(base); const paths=await page.locator('li a').evaluateAll(nodes=>nodes.map(n=>new URL(n.href).pathname));
 const report=[];
 for(const theme of ['light','dark']) {
  for(const width of [1920,1440,1024,390]) {
   await page.setViewportSize({width,height:1000});
   for(const route of paths) {
    await page.goto(base+route); await page.evaluate(t=>{localStorage.setItem('sora.theme',t);const select=document.querySelector('[data-theme-select]');if(select){select.value=t;select.dispatchEvent(new Event('change'));}else{document.documentElement.dataset.theme=t;}},theme);
    const overflow=await page.evaluate(()=>({document:document.documentElement.scrollWidth>innerWidth+2, main:(()=>{const m=document.querySelector('.main-area');return m?m.scrollWidth>m.clientWidth+2:false})()}));
    report.push({route,theme,width,...overflow});
    if(['/app','/login','/admin/users/page','/admin/provider-keys/page','/admin/settings/page','/app/job-batches/12/result','/app/library/page'].includes(route)) {
     if(route==='/app') await page.selectOption('#job-model-select','key:2:10');
     await page.screenshot({path:path.join(out,`${route.replaceAll('/','_')}-${theme}-${width}.png`),fullPage:true});
    }
   }
  }
 }
 fs.writeFileSync(path.join(out,'layout-report.json'),JSON.stringify(report,null,2));
 await page.setViewportSize({width:1440,height:1000}); await page.goto(base+'/app');
 await page.selectOption('#job-model-select','key:2:10');
 assert.equal(await page.locator('#omni-video-block').isVisible(),false);
 assert.equal(await page.locator('[value="video_edit"]').count(),0);
 await page.locator('[name=omni_reference_preset_ids]').first().check();
 await page.locator('[name=prompts]').fill('第一条提示词');
 await page.click('#batch-import-toggle'); await page.fill('#batch-import-textarea','第二条\n\n第三条'); await page.click('#batch-import-apply');
 assert.equal(await page.locator('[name=prompts]').count(),3);
 assert.match(await page.locator('#quota-cost-text').textContent(),/3/);
 await page.click('#batch-import-toggle'); await page.fill('#batch-import-textarea',Array(101).fill('输入').join('\n\n')); await page.click('#batch-import-apply');
 assert.equal(await page.locator('[name=prompts]').count(),3);
 await page.click('.toast-dismiss'); await page.selectOption('#batch-import-mode','replace'); await page.fill('#batch-import-textarea','替换内容'); await page.click('#batch-import-apply'); await page.getByRole('button',{name:'取消',exact:true}).last().click();
 assert.equal(await page.locator('[name=prompts]').count(),3);
 await page.click('#batch-import-apply'); await page.locator('.confirm-dialog .primary-btn').click(); assert.equal(await page.locator('[name=prompts]').count(),1);
 await page.selectOption('#job-model-select','key:3:10'); assert.equal(await page.locator('#omni-video-block').isVisible(),true); assert.match(await page.locator('#omni-material-count').textContent(),/0 \/ 1/);
 await page.selectOption('#job-model-select','key:1:12'); await page.fill('#reference-image-url','https://invalid.example/image.png');
 await page.selectOption('#job-model-select','key:2:10'); await page.locator('[name=omni_reference_preset_ids]').first().check();
 await page.fill('[name=product_name]','Test'); await page.fill('[name=region_name]','Test');
 let submitted=0;
 await page.route('**/app/jobs/batch',route=>{submitted++; assert(!route.request().postData().includes('invalid.example')); return route.fulfill({status:400,json:{detail:'模拟保存失败'}});});
 await page.locator('#create-job-form button[type=submit]').click(); await page.locator('.confirm-dialog .primary-btn').click();
 await page.locator('#studio-form-error').filter({hasText:'模拟保存失败'}).waitFor(); assert.equal(submitted,1); assert.equal(await page.inputValue('[name=prompts]'),'替换内容');
 await page.goto(base+'/admin/settings/page'); await page.fill('[name=max_running_jobs]','7');
 await page.route('**/admin/settings/update/form',route=>route.fulfill({status:400,json:{detail:'模拟设置错误'}}));
 await page.getByRole('button',{name:'保存全部设置'}).click(); await page.locator('[data-form-error]').waitFor(); assert.equal(await page.inputValue('[name=max_running_jobs]'),'7');
 await page.goto(base+'/app/job-batches/12/result'); await page.locator('[data-batch-job="101"] details').evaluate(el=>el.open=true);
 const before=await page.evaluate(()=>performance.timeOrigin); await page.waitForTimeout(9000); assert.equal(await page.evaluate(()=>performance.timeOrigin),before); assert.equal(await page.locator('[data-batch-job="101"] details').getAttribute('open'),'');
 await page.setViewportSize({width:390,height:844}); await page.goto(base+'/app'); await page.click('.mobile-menu-toggle'); assert.equal(await page.locator('.sidebar').isVisible(),true); await page.keyboard.press('Escape'); assert.equal(await page.locator('.sidebar').isVisible(),false);
 const failures=report.filter(row=>row.document||row.main);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({pages:paths.length,views:report.length,overflows:failures,errors,interactions:'passed'},null,2));
 console.log(JSON.stringify({pages:paths.length,views:report.length,overflows:failures,errors,interactions:'passed'},null,2));
 await browser.close();
 if(errors.length||failures.length) process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1)});
