(()=>{
 const key='lumora.sidebar.scrollTop';
 const nav=document.querySelector('.wb-nav');
 if(!nav)return;
 try{const saved=sessionStorage.getItem(key); if(saved!==null) nav.scrollTop=Number(saved)||0;}catch{}
 let timer=0;
 nav.addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(()=>{try{sessionStorage.setItem(key,String(nav.scrollTop))}catch{}},80)},{passive:true});
 document.querySelectorAll('.wb-nav-link').forEach(link=>link.addEventListener('click',()=>{try{sessionStorage.setItem(key,String(nav.scrollTop))}catch{}}));
})();
