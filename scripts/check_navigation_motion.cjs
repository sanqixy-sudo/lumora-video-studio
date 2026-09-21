/* Mock preview only. Native navigation is deliberately not replaced with fetch. */
const {chromium}=require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.SORA_PREVIEW_URL || 'http://127.0.0.1:8129';
(async()=>{
 const browser=await chromium.launch();
 try {
  fs.mkdirSync('runtime/navigation',{recursive:true});
  const p=await browser.newPage({viewport:{width:1329,height:912}});
  const errors=[];p.on('pageerror',e=>errors.push(e.message));
  await p.addInitScript(()=>{
   window.pageMotion=[];
   addEventListener('pagereveal',async event=>{
    const transition=event.viewTransition;if(!transition)return;
    window.firstFrameReady=!!document.querySelector('.theme-cycle-button') && ![...document.querySelectorAll('.wb-topbar select')].some(e=>e.getBoundingClientRect().width>1&&getComputedStyle(e).display!=='none');
    transition.finished.catch(()=>{});transition.updateCallbackDone?.catch(()=>{});
    await transition.ready.catch(()=>{});
    for(let i=0;i<16;i++){window.pageMotion.push(document.getAnimations().map(a=>a.animationName));await new Promise(requestAnimationFrame);}
   });
  });
  await p.goto(base+'/app');
  const sidebar=await p.locator('.wb-sidebar').boundingBox();
  await p.locator('.wb-nav a[href="/app/jobs/page"]').click();
  await p.waitForURL('**/app/jobs/page');await p.waitForTimeout(300);
  assert.ok(await p.evaluate(()=>pageMotion.flat().includes('wb-page-in')),'real cross-document transition');
  assert.equal(await p.evaluate(()=>window.firstFrameReady),true,'theme control must be ready before the first transition snapshot');
  assert.equal((await p.locator('.wb-sidebar').boundingBox()).x,sidebar.x);
  await p.route('**/app/jobs/101/page',async route=>{await new Promise(r=>setTimeout(r,1100));await route.continue();});
  const waiting=await p.evaluate(async()=>{
   document.querySelector('main a[href="/app/jobs/101/page"]').click();
   await new Promise(r=>setTimeout(r,650));
   return {pending:document.documentElement.dataset.navigationPending,slow:document.documentElement.dataset.navigationSlow};
  });
  assert.equal(waiting.pending,'true','detail link shows activity');assert.equal(waiting.slow,'true');
  await p.waitForURL('**/app/jobs/101/page');await p.waitForTimeout(300);
  assert.equal(await p.evaluate(()=>document.documentElement.dataset.navigationPending),undefined);
  await p.goBack();await p.waitForTimeout(300);
  assert.equal(new URL(p.url()).pathname,'/app/jobs/page');
  assert.equal(await p.locator('.is-navigating').count(),0);

  await p.goto(base+'/app/library/page');
  await p.route('**/app/library/page?**',async route=>{await new Promise(r=>setTimeout(r,700));await route.continue();});
  await p.locator('input[name=product_name]').fill('NiceReels');
  const filtering=await p.evaluate(async()=>{
   document.querySelector('.filter-bar button[type=submit]').click();
   await new Promise(r=>setTimeout(r,220));return document.documentElement.dataset.navigationPending;
  });
  assert.equal(filtering,'true','GET filter shows activity');
  await p.waitForURL(url=>url.searchParams.get('product_name')==='NiceReels');
  await p.waitForTimeout(300);assert.equal(await p.evaluate(()=>document.documentElement.dataset.navigationPending),undefined);

  await p.goto(base+'/app');await p.locator('input[name=product_name]').fill('保留的草稿');
  let cancelled=false;p.once('dialog',async dialog=>{assert.equal(dialog.type(),'beforeunload');cancelled=true;await dialog.dismiss();});
  await p.locator('.wb-nav a[href="/app/jobs/page"]').click({noWaitAfter:true});
  await p.waitForTimeout(350);
  assert.ok(cancelled);assert.equal(new URL(p.url()).pathname,'/app');
  assert.equal(await p.locator('input[name=product_name]').inputValue(),'保留的草稿');
  assert.equal(await p.evaluate(()=>document.documentElement.dataset.navigationPending),undefined,'cancelled navigation clears feedback');
  await p.evaluate(()=>document.dispatchEvent(new CustomEvent('lumora:saved')));

  // Cancelled application clicks and new-tab clicks must not mark the current page as loading.
  await p.evaluate(()=>{
   const link=document.querySelector('.wb-nav a[href="/app/jobs/page"]');
   link.addEventListener('click',e=>e.preventDefault(),{once:true});link.click();
  });
  await p.waitForTimeout(180);assert.equal(await p.locator('.is-navigating').count(),0);
  await p.locator('[data-collapse-nav]').click();
  await p.locator('.wb-nav a[href="/app/quota/page"]').click();await p.waitForURL('**/app/quota/page');await p.waitForTimeout(300);
  assert.equal(await p.locator('body').evaluate(e=>e.classList.contains('wb-nav-collapsed')),true);

  await p.setViewportSize({width:390,height:844});
  await p.locator('[data-open-nav]').click();
  await p.locator('.wb-mobile-nav-dialog .wb-nav a[href="/app/jobs/page"]').click();
  await p.waitForURL('**/app/jobs/page');await p.waitForTimeout(300);
  assert.equal(await p.locator('dialog[open]').count(),0);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:'runtime/navigation/mobile-arrival.png'});
  await p.emulateMedia({reducedMotion:'reduce'});
  await p.locator('main a[href="/app/jobs/101/page"]').first().click();
  await p.waitForURL('**/app/jobs/101/page');await p.waitForTimeout(200);
  assert.ok(!(await p.evaluate(()=>pageMotion.flat())).includes('wb-page-in'));
  assert.deepEqual(errors,[]);
  console.log('PASS: cross-document content transition, stable sidebar, delayed detail/GET filter loading, clear on arrival/history, unsaved navigation cancellation, prevented clicks, collapsed sidebar, mobile drawer, reduced motion.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
