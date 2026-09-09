// Capture actual composited backgrounds where axe cannot resolve SVG/gradient/pseudo layers.
const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
(async()=>{const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const evidence=[];
 await page.route('**/*',r=>new URL(r.request().url()).origin==='http://127.0.0.1:8100'?r.continue():r.abort());
 for(const theme of ['light','dark'])for(const route of ['/login','/app','/admin','/app/library/page']){
  await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);await page.goto('http://127.0.0.1:8100'+route);
  const roots=route==='/login'?'.wb-auth-scene':route.includes('library')?'.plaza-poster':'.wb-sidebar';
  const samples=await page.evaluate(roots=>{const items=[];for(const root of document.querySelectorAll(roots)){const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode()){const parent=node.parentElement;if(!node.textContent.trim()||parent.closest('[aria-hidden=true],[inert],script,style'))continue;const style=getComputedStyle(parent);if(style.visibility!=='visible')continue;const range=document.createRange();range.selectNodeContents(node);let opacity=1;for(let el=parent;el;el=el.parentElement)opacity*=Number(getComputedStyle(el).opacity);for(const r of range.getClientRects()){if(r.width<1||r.height<1||r.top<0||r.bottom>innerHeight||r.left<0||r.right>innerWidth)continue;items.push({text:node.textContent.trim(),selector:parent.tagName+'.'+parent.className,color:style.color,opacity,size:parseFloat(style.fontSize),weight:Number(style.fontWeight)||400,rect:{x:r.x,y:r.y,width:r.width,height:r.height}});}}}return items;},roots);
  const stem=theme+route.replaceAll('/','_');await page.screenshot({path:'runtime/guidelines_review/'+stem+'-visible.png'});
  await page.addStyleTag({content:roots+','+roots.split(',').map(s=>s+' *').join(',')+'{color:transparent!important;text-shadow:none!important}'});
  const file=stem+'-background.png';await page.screenshot({path:'runtime/guidelines_review/'+file});evidence.push({theme,route,file,samples});
 }fs.writeFileSync('runtime/guidelines_review/contrast-samples.json',JSON.stringify(evidence,null,2));await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
