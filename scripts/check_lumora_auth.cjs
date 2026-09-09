// Local mock transport uses the production 303 logout contract; no real accounts.
const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();const results=[];
 for(const width of [390,1440]){
  const context=await browser.newContext({viewport:{width,height:900}});const page=await context.newPage();const base='http://127.0.0.1:8100';const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  await page.goto(base+'/login?expired=1');
  await page.evaluate(()=>{const el=document.createElement('div');el.className='login-alert wb-login-notice';el.textContent='登录已过期，请重新登录。';document.querySelector('[data-login-form]').before(el);});
  await page.fill('[name=username]','mock-user');await page.fill('[name=password]',' mock-password ');
  let reply={status:401,contentType:'application/json',body:JSON.stringify({detail:'用户名或密码错误'})},count=0;
  await page.route(base+'/auth/login-browser',r=>{count++;assert.equal(r.request().postDataJSON().password,' mock-password ');return r.fulfill(reply);});
  for(const scenario of [
   {status:401,detail:'用户名或密码错误'},
   {status:403,detail:'账号已被禁用'},
   {status:403,detail:'登录请求被拒绝（HTTP 403），请联系管理员检查账号状态或访问限制。',html:true},
   {status:503,detail:'服务暂不可用，请稍后重试。'}
  ]){
   reply={status:scenario.status,contentType:scenario.html?'text/html':'application/json',body:scenario.html?'<h1>Forbidden</h1>':JSON.stringify({detail:scenario.detail})};
   await page.click('[data-login-form] button[type=submit]');
   await page.waitForFunction(text=>document.querySelector('[data-form-error]')?.textContent===text,scenario.detail);
   assert.equal(page.url(),base+'/login?expired=1');assert.equal(await page.inputValue('[name=username]'),'mock-user');
   assert.equal(await page.locator('.wb-login-notice').isVisible(),false);
   assert.equal(await page.locator('[data-login-form] button[type=submit]').isEnabled(),true);
   results.push({width,status:scenario.status,html:!!scenario.html,passed:true});
  }
  assert.equal(count,4);
  reply={status:200,contentType:'application/json',body:JSON.stringify({ok:true,target:'/app'})};
  await page.click('[data-login-form] button[type=submit]');await page.waitForURL(base+'/app');
  let logoutType;
  await page.route(base+'/auth/logout',r=>{logoutType=r.request().resourceType();return r.fulfill({status:303,headers:{location:'/login'}});});
  await page.click('[data-account-toggle]');await page.click('form[action="/auth/logout"] button');await page.waitForURL(base+'/login');
  assert.equal(logoutType,'document');assert.equal(await page.evaluate(()=>sessionStorage.getItem('app.toast.message')),null);
  results.push({width,nativeLogout:true,passed:true});
  await page.goto(base+'/preview/access-denied');await page.click('form[action="/auth/logout"] button');await page.waitForURL(base+'/login');assert.equal(logoutType,'document');
  results.push({width,deniedPageLogout:true,passed:true});assert.deepEqual(errors,[]);await context.close();
 }
 fs.mkdirSync('runtime/auth_review',{recursive:true});fs.writeFileSync('runtime/auth_review/browser.json',JSON.stringify({passed:true,results},null,2));console.log(JSON.stringify({passed:true,checks:results.length}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
