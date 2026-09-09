// A short, locally generated abstract clip for UI review; no upstream generation.
const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
(async()=>{const browser=await chromium.launch({headless:true});const page=await browser.newPage();
const bytes=await page.evaluate(async()=>{
 const canvas=document.createElement('canvas');canvas.width=720;canvas.height=1280;const ctx=canvas.getContext('2d');
 const stream=canvas.captureStream(24),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8',videoBitsPerSecond:1200000}),chunks=[];
 recorder.ondataavailable=e=>chunks.push(e.data);const stopped=new Promise(resolve=>recorder.onstop=resolve);recorder.start();
 const start=performance.now();await new Promise(resolve=>{function paint(now){const t=Math.min((now-start)/2400,1),g=ctx.createLinearGradient(0,0,720,1280);g.addColorStop(0,'#c9d9b0');g.addColorStop(.5,'#6d987e');g.addColorStop(1,'#163d30');ctx.fillStyle=g;ctx.fillRect(0,0,720,1280);ctx.fillStyle='#e7e8c4';ctx.beginPath();ctx.arc(490-30*t,340+15*t,130,0,Math.PI*2);ctx.fill();for(let i=0;i<3;i++){ctx.fillStyle=['#537c63','#345d49','#163b30'][i];ctx.beginPath();ctx.moveTo(-100,880+i*120);ctx.bezierCurveTo(200,460+i*150+20*t,430,1120+i*70,850,730+i*120);ctx.lineTo(850,1400);ctx.lineTo(-100,1400);ctx.fill();}if(t<1)requestAnimationFrame(paint);else resolve();}requestAnimationFrame(paint);});
 recorder.stop();await stopped;stream.getTracks().forEach(t=>t.stop());return Array.from(new Uint8Array(await new Blob(chunks,{type:'video/webm'}).arrayBuffer()));
});fs.mkdirSync('runtime/studio_preview',{recursive:true});fs.writeFileSync('runtime/studio_preview/sample.webm',Buffer.from(bytes));await browser.close();console.log('Local mock clip:',bytes.length,'bytes');})().catch(e=>{console.error(e);process.exit(1)});
