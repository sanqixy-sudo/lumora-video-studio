/* Local motion helpers. Business state and focus never wait for an animation. */
(() => {
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Set();
  const moving = new WeakMap();
  function stop(element) {
    const animation = moving.get(element);
    if (animation) { animation.cancel(); running.delete(animation); moving.delete(element); }
  }
  function move(element, frames, duration = 220) {
    stop(element);
    if (media.matches) return;
    const animation = element.animate(frames, {duration, easing:'cubic-bezier(.25,1,.5,1)'});
    moving.set(element, animation); running.add(animation);
    animation.finished.then(() => {
      running.delete(animation);
      if (moving.get(element) === animation) moving.delete(element);
    }).catch(() => {});
  }
  function cancelAll() { for (const animation of running) {moving.delete(animation.effect.target);animation.cancel();} running.clear(); }
  media.addEventListener('change', () => { if (media.matches) cancelAll(); });
  addEventListener('resize', cancelAll);

  window.SoraWorkbenchMotion = {
    reveal(element,duration=140,distance=6) {
      if(!element)return;
      const previous=moving.get(element),painted=previous?getComputedStyle(element):null;
      const first=painted?{opacity:painted.opacity,transform:painted.transform}:{opacity:0,transform:`translateY(${distance}px)`};
      move(element,[first,{opacity:1,transform:'translateY(0)'}],duration);
    },
    navigation(change) {
      const stage = document.querySelector('.wb-stage');
      const sidebar = document.querySelector('.wb-sidebar');
      if (!stage || !sidebar || media.matches || innerWidth < 1200) { change(); return; }
      // Measure the currently painted positions, including an interrupted transition.
      const elements = [stage, ...sidebar.querySelectorAll('.wb-brand img,.wb-nav-link>.wb-icon')];
      const before = elements.map(element => element.getBoundingClientRect());
      elements.forEach(stop);
      document.body.classList.add('wb-nav-animate');
      change(); // Resolve content width once; tables are not resized every frame.
      const afterRects=elements.map(element=>element.getBoundingClientRect());
      elements.forEach((element, i) => {
        const after = afterRects[i];
        const x = before[i].left - after.left, y = before[i].top - after.top;
        if (Math.abs(x) + Math.abs(y) > .5) move(element, [
          {transform:`translate(${x}px,${y}px)`}, {transform:'translate(0,0)'}
        ]);
      });
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const box = document.getElementById('batch-import-box');
    const trigger = document.getElementById('batch-import-toggle');
    if (box && trigger) {
      const sync = () => {
        const closed = box.classList.contains('hidden');
        if (closed && box.contains(document.activeElement)) trigger.focus({preventScroll:true});
        box.inert = closed;
      };
      new MutationObserver(sync).observe(box, {attributes:true, attributeFilter:['class']});
      sync();
    }
  });
})();
