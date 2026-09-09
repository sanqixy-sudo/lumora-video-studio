const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8100',out=path.resolve('runtime/studio_review');fs.mkdirSync(out,{recursive:true});
(async()=>{
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const page=await context.newPage();page.on('dialog',dialog=>dialog.accept());const errors=[],failures=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin!==base)return route.abort();return route.continue();});
const routes=['/login','/app','/app/jobs/101/page','/admin/users/page','/admin/jobs/101/page'];
const layouts=[];
for(const theme of ['light','dark'])for(const width of [375,390,768,1024,1440,1920]){
 await page.setViewportSize({width,height:1000});
 for(const route of routes){
  await page.goto(base+route);await page.evaluate(t=>{localStorage.setItem('sora.theme',t);document.querySelectorAll('[data-theme-select]').forEach(s=>{s.value=t;s.dispatchEvent(new Event('change'));});},theme);
  if(route==='/app')await page.selectOption('#job-model-select','key:2:10');
  const result=await page.evaluate(()=>{
   const fields=[...document.querySelectorAll('.wb-detail-fields dd')].map(e=>({text:e.textContent.trim(),width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}));
   const doc=document.documentElement;return {overflow:doc.scrollWidth>innerWidth+2,fields,bodyHeight:doc.scrollHeight};
  });
  layouts.push({route,theme,width,...result});if(result.overflow)failures.push({route,theme,width,error:'document overflow'});
  if(result.fields.some(f=>f.width<140||f.height>150))failures.push({route,theme,width,error:'compressed detail field',fields:result.fields});
  if([390,1440].includes(width))await page.screenshot({path:path.join(out,`${route.replaceAll('/','_')}-${theme}-${width}.png`),fullPage:true});
 }
}
fs.writeFileSync(path.join(out,'layout.json'),JSON.stringify(layouts,null,2));
await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/app?scenario=error');
await page.selectOption('#job-model-select','key:2:10');
await page.click('[data-open-materials]');await page.locator('[data-preset-choice]').first().check();await page.click('#wb-material-drawer [data-close-drawer]');
assert.equal(await page.locator('[name=omni_reference_preset_ids]:checked').count(),0);
assert.equal(await page.evaluate(()=>document.activeElement.matches('[data-open-materials]')),true);
await page.click('[data-open-materials]');await page.locator('[data-preset-choice]').first().check();await page.click('#wb-apply-materials');
assert.equal(await page.locator('[name=omni_reference_preset_ids]:checked').count(),1);assert.equal(await page.locator('.wb-selected-item').count(),1);
await page.fill('[name=product_name]','测试 APP');await page.fill('[name=region_name]','美国');await page.fill('[name=prompts]','第一条提示词');
await page.click('#batch-import-toggle');await page.fill('#batch-import-textarea','第二条\n\n第三条');assert.match(await page.textContent('#wb-import-count'),/2/);await page.click('#batch-import-apply');assert.equal(await page.locator('[name=prompts]').count(),3);
await page.click('#batch-import-toggle');await page.fill('#batch-import-textarea',Array(101).fill('内容').join('\n\n'));await page.click('#batch-import-apply');assert.equal(await page.locator('[name=prompts]').count(),3);await page.click('.toast-dismiss');
await page.fill('#batch-import-textarea','替换内容');await page.selectOption('#batch-import-mode','replace');await page.click('#batch-import-apply');await page.locator('.confirm-dialog .ghost-btn').click();assert.equal(await page.locator('[name=prompts]').count(),3);
await page.click('#batch-import-apply');await page.locator('.confirm-dialog[open] .primary-btn').click();assert.equal(await page.locator('[name=prompts]').count(),1);
await page.locator('#create-job-form button[type=submit]').click();await page.locator('.confirm-dialog[open] .primary-btn').click();await page.locator('#studio-form-error:not(.hidden)').waitFor();assert.equal(await page.inputValue('[name=prompts]'),'替换内容');
await page.selectOption('#job-model-select','key:3:10');assert.equal(await page.locator('#omni-video-block').isVisible(),true);assert.equal(await page.locator('[name=omni_reference_preset_ids]:checked').count(),0);
await page.selectOption('#job-model-select','key:2:10');assert.equal(await page.locator('#omni-video-block').isVisible(),false);
await page.goto(base+'/admin/users/page?scenario=error');await page.click('[data-open-drawer]');await page.fill('#wb-create-user-form [name=username]','new-user');await page.fill('#wb-create-user-form [name=password]','example-password');await page.click('#wb-create-user-form button[type=submit]');await page.locator('#wb-create-user-form [data-form-error]').waitFor();assert.equal(await page.inputValue('#wb-create-user-form [name=username]'),'new-user');await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.matches('[data-open-drawer]')),true);
await page.locator('.wb-row-trigger').first().click();assert.equal(await page.locator('body>.wb-menu-open').count(),1);await page.keyboard.press('Escape');
await page.goto(base+'/login?scenario=error');await page.fill('[data-login-form] [name=username]','sample-user');await page.fill('[data-login-form] [name=password]','example-password');await page.click('[data-login-form] button[type=submit]');await page.locator('[data-login-form] [data-form-error]').waitFor();assert.equal(await page.inputValue('[data-login-form] [name=username]'),'sample-user');
await page.click('[data-show-register]');assert.equal(await page.locator('[data-register-form]').isVisible(),true);await page.fill('[data-register-form] [name=display_name]','示例姓名');await page.fill('[data-register-form] [name=username]','sample-user');await page.fill('[data-register-form] [name=password]','example-password');await page.click('[data-register-form] button[type=submit]');await page.locator('[data-register-form] [data-form-error]').waitFor();assert.equal(await page.inputValue('[data-register-form] [name=display_name]'),'示例姓名');
await page.goto(base+'/login');await page.fill('[data-login-form] [name=username]','sample-user');await page.fill('[data-login-form] [name=password]','example-password');await page.click('[data-login-form] button[type=submit]');await page.waitForURL(base+'/app');
await page.setViewportSize({width:390,height:844});await page.click('[data-open-nav]');assert.equal(await page.locator('.wb-mobile-nav-dialog[open]').count(),1);await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.matches('[data-open-nav]')),true);
await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/app/jobs/101/page');const origin=await page.evaluate(()=>performance.timeOrigin);await page.evaluate(()=>scrollTo(0,500));const scroll=await page.evaluate(()=>scrollY);await page.waitForTimeout(9000);assert.equal(await page.evaluate(()=>performance.timeOrigin),origin);assert.equal(await page.evaluate(()=>scrollY),scroll);
// Normal motion has its own context; screenshot pass above intentionally disables it.
const motionContext=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference',recordVideo:{dir:path.join(out,'motion'),size:{width:1440,height:1000}}});
const motion=await motionContext.newPage();await motion.goto(base+'/login');await motion.waitForTimeout(750);await motion.click('[data-show-register]');await motion.waitForTimeout(200);await motion.click('[data-show-login]');await motion.goto(base+'/app');
for(let i=0;i<3;i++){await motion.click('[data-open-materials]');await motion.keyboard.press('Escape');}
assert.equal(await motion.locator('dialog[open]').count(),0);await motion.click('[data-open-materials]');await motion.waitForTimeout(280);assert.equal(await motion.locator('#wb-material-drawer').evaluate(e=>getComputedStyle(e).opacity),'1');await motion.keyboard.press('Escape');
await motionContext.close();
const report={surfaces:4,routes:routes.length,views:layouts.length,failures,errors,interactions:'passed',motion:'passed',limits:['Mock backend only','No real touch device','No production performance measurement']};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();if(failures.length||errors.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1)});
