/* Four tilted rows follow horizontal pointer position in alternating directions. */
(()=>{
 const rows=[...document.querySelectorAll('.lumora-wall-row')];if(!rows.length)return;
 const reduced=matchMedia('(prefers-reduced-motion:reduce)');
 const fine=matchMedia('(hover:hover) and (pointer:fine) and (min-width:768px)');
 let frame=0,x=0;
 function reset(){cancelAnimationFrame(frame);frame=0;x=0;rows.forEach(row=>row.style.transform='translate3d(0,0,0)');}
 function enabled(){return !reduced.matches&&fine.matches&&!document.hidden;}
 document.addEventListener('pointermove',event=>{
  if(!enabled()||event.pointerType==='touch')return;
  x=Math.max(-1,Math.min(1,event.clientX/innerWidth*2-1))*150;
  if(!frame)frame=requestAnimationFrame(()=>{frame=0;rows.forEach(row=>row.style.transform=`translate3d(${(x*Number(row.dataset.direction)).toFixed(2)}px,0,0)`);});
 },{passive:true});
 document.documentElement.addEventListener('pointerleave',reset);
 document.addEventListener('visibilitychange',reset);
 window.addEventListener('blur',reset);window.addEventListener('resize',reset);
 reduced.addEventListener('change',reset);fine.addEventListener('change',reset);
 document.querySelectorAll('.lumora-wall-tile img').forEach(img=>{
  const hide=()=>{img.style.visibility='hidden';};img.addEventListener('error',hide,{once:true});
  if(img.complete&&!img.naturalWidth)hide();
 });
})();
