const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
const base='http://127.0.0.1:8100',out=path.resolve(process.env.MOBILE_OUT||'runtime/mobile_review');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true}),results=[],errors=[],network=[];
 const routes=process.env.MOBILE_ROUTES?process.env.MOBILE_ROUTES.split(','):Object.keys(JSON.parse(fs.readFileSync('runtime/studio_preview/routes.json','utf8')));
 const sizes=process.env.MOBILE_WIDTHS?process.env.MOBILE_WIDTHS.split(',').map(w=>[Number(w),Number(w)===844?390:844]):[[320,740],[375,812],[390,844],[430,932],[768,1024],[844,390]];
 for(const theme of ['light','dark'])for(const [width,height] of sizes){
  const context=await browser.newContext({viewport:{width,height},hasTouch:true,isMobile:true,reducedMotion:'reduce'});await context.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();const cdp=await context.newCDPSession(page);page.on('dialog',d=>d.dismiss());page.on('pageerror',e=>errors.push({url:page.url(),theme,width,error:e.message}));page.on('response',r=>{if(r.status()>=400)network.push({url:r.url(),status:r.status()});});
  async function scan(route,state){
   // Full-page capture may reset Chromium touch emulation; restore the tested input mode.
   await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});await page.waitForFunction(()=>matchMedia('(pointer:coarse)').matches);
   const metrics=await page.evaluate(()=>{
    const visible=e=>e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})&&!e.closest('[inert]');
    const label=e=>({tag:e.tagName,cls:e.className,text:(e.getAttribute('aria-label')||e.textContent||e.name||'').trim().slice(0,65)});
    const small=[],inputs=[],clipped=[];
    for(const e of document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary')){
     if(!visible(e)||e.disabled)continue;let target=e;if(e.matches('input[type=checkbox],input[type=radio]'))target=e.labels?.[0]||e;
     const r=target.getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;if(cx<0||cy<0||cx>=innerWidth||cy>=innerHeight)continue;
     const hit=document.elementFromPoint(cx,cy);if(!hit||!(target===hit||target.contains(hit)))continue;
     if((r.width<43.5||r.height<43.5)&&!e.matches('.wb-skip')&&!e.closest('p'))small.push({...label(e),w:r.width,h:r.height});
     if(e.matches('input:not([type=checkbox]):not([type=radio]),select,textarea')&&parseFloat(getComputedStyle(e).fontSize)<16)inputs.push({...label(e),font:getComputedStyle(e).fontSize});
    }
    for(const e of document.querySelectorAll('button,label,h1,h2,dd')){if(!visible(e))continue;const s=getComputedStyle(e);if(e.clientWidth&&e.scrollWidth>e.clientWidth+2&&s.overflowX==='hidden'&&s.textOverflow!=='ellipsis'&&s.webkitLineClamp==='none')clipped.push(label(e));}
    const dialogs=[...document.querySelectorAll('dialog[open],.modal:not(.hidden) .modal-card')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,overflow:e.scrollWidth>e.clientWidth+2};});
    return {overflow:document.documentElement.scrollWidth>innerWidth+2,viewport:innerWidth,actualTheme:document.documentElement.dataset.theme,coarse:matchMedia('(pointer:coarse)').matches,small,inputs,clipped,dialogs};
   });
   const record={route,state,theme,width,height,...metrics};
   if(width===375&&state==='page'){await page.addScriptTag({path:'runtime/axe.min.js'});record.axe=await page.evaluate(async()=>(await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})));}
   results.push(record);
   if(state==='page'&&[375,844].includes(width)||metrics.overflow||metrics.clipped.length)await page.screenshot({path:path.join(out,`${route.replaceAll('/','_')}-${theme}-${width}-${state.replaceAll(':','_')}.png`),fullPage:true});
  }
  for(const route of routes){const response=await page.goto(base+route);if(response.status()!==200||new URL(page.url()).pathname!==route)throw Error('Unexpected route '+route);await scan(route,'page');await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));await scan(route,'bottom');await page.evaluate(()=>scrollTo(0,0));
   if([375,844].includes(width)){
    for(const selector of ['[data-open-nav]','[data-account-toggle]','[data-open-drawer]','[data-open-materials]','.wb-row-trigger','.plaza-open-btn','.usage-edit-btn','[data-show-register]']){
     const trigger=page.locator(selector).first();if(!await trigger.isVisible())continue;await trigger.click();await scan(route,selector.replace(/[^a-z-]/g,''));await page.keyboard.press('Escape');
    }
    for(const tab of await page.locator('.tab-button').all()){if(await tab.isVisible()){await tab.click();await scan(route,'tab-'+await tab.getAttribute('data-tab-target'));}}
   }
  }
  await context.close();console.log(`${theme} ${width}x${height}: ${routes.length} routes`);
 }
 const failures=results.filter(r=>r.small.length||r.inputs.length||r.overflow||r.viewport!==r.width||r.actualTheme!==r.theme||r.clipped.length||r.axe?.length||r.dialogs.some(d=>d.x< -1||d.x+d.w>r.width+1||d.overflow));
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({session:{base,mock:true,touch:true,browser:'Chromium',reducedMotion:true},routes,results,failures,errors,network},null,2));
 console.log(JSON.stringify({views:results.length,failures:failures.length,errors,network,small:results.filter(r=>r.small.length).length,smallInputs:results.filter(r=>r.inputs.length).length}));await browser.close();if(failures.length||errors.length||network.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
