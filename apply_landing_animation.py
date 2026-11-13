#!/usr/bin/env python3
"""Landing page animation upgrade (LANDING_ANIM_V1).
Run from the project root:  python apply_landing_animation.py
- Backs up templates/landing.html to templates/landing_backup_2026-11-13.html (not routed, safe)
- Adds: intro, staggered hero, hero glow background, scroll reveals, count-up stats,
  card tilt (desktop), glowing buttons, nav progress line, floating WhatsApp button.
- No migration, no new libraries, no CDN. Safe to run twice.
To undo: copy the backup file over templates/landing.html.
"""
import os, sys, shutil

ROOT = os.getcwd()
P = os.path.join(ROOT, "templates", "landing.html")
BK = os.path.join(ROOT, "templates", "landing_backup_2026-11-13.html")
if not os.path.exists(P):
    sys.exit("Run this from the project root (templates/landing.html not found).")

s = open(P, encoding="utf-8", newline="").read()
if "LANDING_ANIM_V1" in s:
    print("Already upgraded. Nothing to do.")
    sys.exit(0)

CSS = r"""    /* LANDING_ANIM_V1 — animation layer (GPU-only: transform + opacity) */
    @keyframes gRise{from{opacity:0;transform:translateY(22px)}}
    @keyframes gPopIn{from{opacity:0;transform:scale(.96)}}
    @keyframes gFade{from{opacity:0}}
    @keyframes gDrift1{0%,100%{transform:translate3d(0,0,0)}50%{transform:translate3d(6vw,-4vh,0)}}
    @keyframes gDrift2{0%,100%{transform:translate3d(0,0,0)}50%{transform:translate3d(-7vw,5vh,0)}}
    @keyframes gShine{from{transform:translateX(-120%) skewX(-20deg)}to{transform:translateX(320%) skewX(-20deg)}}
    @keyframes gPulse{0%{transform:scale(1);opacity:.5}100%{transform:scale(1.8);opacity:0}}
    @keyframes gBar{from{transform:scaleX(0)}to{transform:scaleX(1)}}
    @keyframes gLogo{from{opacity:0;transform:scale(.8)}}

    /* intro: only on first visit of a session, ~0.7s */
    #intro{display:none}
    html.intro #intro{display:flex;position:fixed;inset:0;z-index:2000;background:var(--blue);align-items:center;justify-content:center;flex-direction:column;gap:1rem;transition:opacity .35s ease,visibility .35s}
    html.intro.ready #intro{opacity:0;visibility:hidden}
    #intro .i-logo{width:84px;height:84px;background:#fff;border-radius:50%;padding:8px;display:flex;align-items:center;justify-content:center;animation:gLogo .5s cubic-bezier(.2,.8,.2,1) both}
    #intro .i-logo img{width:100%;height:100%;object-fit:contain}
    #intro .i-line{width:120px;height:3px;background:rgba(255,255,255,.22);border-radius:3px;overflow:hidden}
    #intro .i-line i{display:block;height:100%;background:var(--yellow);transform-origin:left;animation:gBar .7s ease-out forwards}

    /* scroll reveal (class added by JS, so no-JS visitors see everything) */
    html.js .reveal:not(.in){opacity:0}
    html.js .reveal.in{animation:gRise .65s cubic-bezier(.2,.7,.2,1) backwards;animation-delay:var(--d,0ms)}
    html.js .prod-card.pop{animation:gPopIn .35s ease backwards}

    /* hero: staggered entrance, re-runs on every slide */
    .slide.active{animation:gFade .6s ease both}
    html.js .slide.active .hero-logo,html.js .slide.active .slide-badge,html.js .slide.active .slide-title,
    html.js .slide.active .slide-sub,html.js .slide.active .slide-prices,html.js .slide.active .slide-btns{animation:gRise .7s cubic-bezier(.2,.7,.2,1) backwards}
    html.js .slide.active .hero-logo{animation-delay:0s}
    html.js .slide.active .slide-badge{animation-delay:.05s}
    html.js .slide.active .slide-title{animation-delay:.15s}
    html.js .slide.active .slide-sub{animation-delay:.28s}
    html.js .slide.active .slide-prices{animation-delay:.38s}
    html.js .slide.active .slide-btns{animation-delay:.48s}
    html.js .hero-pills .pill{animation:gRise .6s cubic-bezier(.2,.7,.2,1) backwards}
    html.js .hero-pills .pill:nth-child(1){animation-delay:.6s}
    html.js .hero-pills .pill:nth-child(2){animation-delay:.68s}
    html.js .hero-pills .pill:nth-child(3){animation-delay:.76s}
    html.js .hero-pills .pill:nth-child(4){animation-delay:.84s}
    html.js.intro:not(.ready) .slide.active *{animation-play-state:paused}

    /* hero atmosphere: three soft glows drifting slowly (no blur filter, cheap) */
    .atmo{position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:0}
    .atmo i{position:absolute;border-radius:50%;will-change:transform}
    .atmo i:nth-child(1){width:60vmax;height:60vmax;left:-22vmax;bottom:-34vmax;background:radial-gradient(circle,rgba(255,203,5,.20),transparent 62%);animation:gDrift1 18s ease-in-out infinite}
    .atmo i:nth-child(2){width:52vmax;height:52vmax;right:-20vmax;top:-28vmax;background:radial-gradient(circle,rgba(80,160,255,.38),transparent 62%);animation:gDrift2 22s ease-in-out infinite}
    .atmo i:nth-child(3){width:34vmax;height:34vmax;left:38%;top:20%;background:radial-gradient(circle,rgba(255,255,255,.08),transparent 62%);animation:gDrift1 27s ease-in-out infinite reverse}
    .atmo.paused i{animation-play-state:paused}
    @media(max-width:768px){.atmo i:nth-child(3){display:none}}

    /* nav: scroll progress line + shadow, link underline */
    nav{transition:box-shadow .3s}
    nav.scrolled{box-shadow:0 4px 22px rgba(0,0,0,.28)}
    nav::after{content:'';position:absolute;left:0;bottom:0;height:3px;width:100%;background:var(--yellow);transform:scaleX(var(--p,0));transform-origin:left}
    .nav-links a:not(.nav-cta){position:relative}
    .nav-links a:not(.nav-cta)::after{content:'';position:absolute;left:0;right:0;bottom:-4px;height:2px;background:var(--yellow);transform:scaleX(0);transform-origin:left;transition:transform .25s ease}
    .nav-links a:not(.nav-cta):hover::after{transform:scaleX(1)}

    /* buttons: glow, shine sweep, press */
    .btn-yellow,.btn-wa,.btn-blue{position:relative;overflow:hidden}
    .btn-yellow::after,.btn-wa::after{content:'';position:absolute;top:0;bottom:0;left:0;width:35%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent);transform:translateX(-120%) skewX(-20deg);pointer-events:none}
    .btn-yellow:hover::after,.btn-wa:hover::after{animation:gShine .7s ease}
    .btn-yellow:hover{box-shadow:0 8px 26px rgba(255,203,5,.45)}
    .btn-wa:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(37,211,102,.35)}
    .btn-ghost:hover{box-shadow:0 0 0 3px rgba(255,255,255,.12)}
    .btn-yellow:active,.btn-wa:active,.btn-blue:active,.btn-ghost:active{transform:scale(.97)}

    /* cards: mouse tilt + light spot (desktop only, class added by JS) */
    .tilt{position:relative;transition:transform .18s ease-out,box-shadow .2s,border-color .2s}
    .tilt::before{content:'';position:absolute;inset:0;background:radial-gradient(220px circle at var(--mx,50%) var(--my,50%),rgba(255,203,5,.16),transparent 62%);opacity:0;transition:opacity .2s;pointer-events:none;z-index:3}
    .tilt:hover::before{opacity:1}
    .svc-card:active,.prod-card:active,.why-card:active{transform:scale(.985)}

    /* floating WhatsApp button */
    .wa-float{position:fixed;right:16px;bottom:16px;z-index:900;width:56px;height:56px;border-radius:50%;background:#25D366;display:flex;align-items:center;justify-content:center;font-size:1.6rem;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.28);opacity:0;transform:translateY(20px) scale(.8);pointer-events:none;transition:opacity .3s,transform .3s}
    .wa-float.show{opacity:1;transform:none;pointer-events:auto}
    .wa-float::before{content:'';position:absolute;inset:0;border-radius:50%;background:#25D366;z-index:-1;animation:gPulse 2.2s ease-out infinite}

    /* respect reduced-motion / accessibility */
    @media (prefers-reduced-motion:reduce){
      html.js .reveal:not(.in){opacity:1}
      *,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
      html.intro #intro{display:none}
    }
"""
JS = r"""<script>
/* LANDING_ANIM_V1 */
(function(){
  var d=document,h=d.documentElement;
  var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
  var fine=window.matchMedia&&matchMedia('(hover:hover) and (pointer:fine)').matches;

  // 1) intro: show ~0.65s on first visit only, never block longer than 1.4s
  var t0=performance.now(),done=false;
  function finish(){
    if(done)return;done=true;h.classList.add('ready');
    try{sessionStorage.setItem('gpsl_intro','1')}catch(e){}
  }
  if(h.classList.contains('intro')){
    var wait=function(){setTimeout(finish,Math.max(0,650-(performance.now()-t0)))};
    if(d.readyState==='complete')wait();else addEventListener('load',wait);
    setTimeout(finish,1400);
  }else{finish();}

  // 2) scroll reveal with staggered delays
  var sel='.sec-label,.sec-title,.sec-sub,.about-img,.about-text p,.stat,.svc-card,.why-card,.br-card,.ci,.cform,.cat-filters,.feat-grid .prod-card,#catalog-grid .prod-card,.footer-top > *';
  var els=d.querySelectorAll(sel);
  Array.prototype.forEach.call(els,function(el){
    el.classList.add('reveal');
    var i=Array.prototype.indexOf.call(el.parentNode.children,el);
    el.style.setProperty('--d',((i%6)*70)+'ms');
  });
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){
      es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});
    },{threshold:.12,rootMargin:'0px 0px -6% 0px'});
    Array.prototype.forEach.call(els,function(el){io.observe(el)});
  }else{
    Array.prototype.forEach.call(els,function(el){el.classList.add('in')});
  }

  // 3) count-up stats
  function count(n,target,suf){
    var s=performance.now(),dur=900;
    (function step(t){
      var p=Math.min(1,(t-s)/dur),e=1-Math.pow(1-p,3);
      n.textContent=Math.round(target*e)+suf;
      if(p<1)requestAnimationFrame(step);
    })(s);
  }
  if(!reduce&&'IntersectionObserver' in window){
    var cio=new IntersectionObserver(function(es){
      es.forEach(function(e){
        if(!e.isIntersecting)return;
        var n=e.target,m=/^(\d+)(.*)$/.exec(n.getAttribute('data-final'));
        cio.unobserve(n);
        if(m)count(n,+m[1],m[2]);
      });
    },{threshold:.6});
    Array.prototype.forEach.call(d.querySelectorAll('.stat-n'),function(n){
      var txt=n.textContent.trim(),m=/^(\d+)(.*)$/.exec(txt);
      if(!m)return;
      n.setAttribute('data-final',txt);n.textContent='0'+m[2];cio.observe(n);
    });
  }

  // 4) card tilt + light spot (mouse devices only)
  if(fine&&!reduce){
    Array.prototype.forEach.call(d.querySelectorAll('.prod-card,.svc-card,.why-card,.br-card'),function(c){
      c.classList.add('tilt');
      var raf=0;
      c.addEventListener('pointermove',function(e){
        if(raf)return;var x=e.clientX,y=e.clientY;
        raf=requestAnimationFrame(function(){
          raf=0;var r=c.getBoundingClientRect(),px=(x-r.left)/r.width,py=(y-r.top)/r.height;
          c.style.setProperty('--mx',(px*100).toFixed(1)+'%');
          c.style.setProperty('--my',(py*100).toFixed(1)+'%');
          c.style.transform='perspective(800px) rotateX('+((.5-py)*7).toFixed(2)+'deg) rotateY('+((px-.5)*7).toFixed(2)+'deg) translateY(-3px)';
        });
      });
      c.addEventListener('pointerleave',function(){
        if(raf){cancelAnimationFrame(raf);raf=0;}
        c.style.transform='';
      });
    });
  }

  // 5) nav progress line + floating WhatsApp button
  var nav=d.querySelector('nav'),wa=d.getElementById('wa-float'),tick=false;
  function onScroll(){
    tick=false;
    var y=window.pageYOffset||0,max=h.scrollHeight-innerHeight;
    nav.classList.toggle('scrolled',y>10);
    nav.style.setProperty('--p',max>0?Math.min(1,y/max).toFixed(4):0);
    if(wa)wa.classList.toggle('show',y>400);
  }
  addEventListener('scroll',function(){if(!tick){tick=true;requestAnimationFrame(onScroll);}},{passive:true});
  onScroll();

  // 6) pause hero glows when hero is off-screen (saves battery)
  var atmo=d.querySelector('.atmo'),hero=d.getElementById('home');
  if(atmo&&hero&&'IntersectionObserver' in window){
    new IntersectionObserver(function(es){atmo.classList.toggle('paused',!es[0].isIntersecting);}).observe(hero);
  }

  // 7) catalog filter helper: pop cards back in
  window.gpslPop=function(c){c.classList.remove('pop');void c.offsetWidth;c.classList.add('pop');};
})();
</script>
"""

HEAD_JS = ("  <script>(function(){var h=document.documentElement;h.classList.add('js');"
           "try{if(!sessionStorage.getItem('gpsl_intro')&&!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)){h.classList.add('intro')}}catch(e){}})();</script>\n")
INTRO = ("""<div id="intro" aria-hidden="true"><div class="i-logo"><img src="{% static 'img/gpsl_logo.png' %}" alt=""></div><div class="i-line"><i></i></div></div>\n""")
ATMO = '<div class="atmo" aria-hidden="true"><i></i><i></i><i></i></div>\n  '
WA = ('<a href="https://wa.me/{{ whatsapp_number }}?text=Hello%20GPSL%2C%20I%20need%20help" target="_blank" rel="noopener" '
      'class="wa-float" id="wa-float" aria-label="Chat with us on WhatsApp">💬</a>\n\n')

PATCHES = [
 ("favicon", """  <link rel="icon" type="image/png" href="{% static 'img/favicon.ico' %}">\n""",
             """  <link rel="icon" type="image/png" href="{% static 'img/favicon.ico' %}">\n""" + HEAD_JS),
 ("css", "  </style>\n</head>", CSS + "  </style>\n</head>"),
 ("intro", '<body oncontextmenu="return false">\n', '<body oncontextmenu="return false">\n' + INTRO),
 ("atmo", '<section class="hero" id="home">\n  <!-- SLIDESHOW -->', '<section class="hero" id="home">\n  ' + ATMO + '<!-- SLIDESHOW -->'),
 ("wa", "<script>\nfunction toggleMob(){", WA + "<script>\nfunction toggleMob(){"),
 ("filter", "      card.style.display='';\n    } else {",
            "      var wasHid=card.style.display==='none';card.style.display='';\n      if(wasHid){card.classList.add('in');window.gpslPop&&gpslPop(card);}\n    } else {"),
 ("search", "    card.style.display=card.dataset.name.includes(q)?'':'none';",
            "    var show=card.dataset.name.includes(q),was=card.style.display==='none';\n    card.style.display=show?'':'none';\n    if(show&&was){card.classList.add('in');window.gpslPop&&gpslPop(card);}"),
 ("js", "</script>\n\n</body>\n</html>", "</script>\n\n" + JS + "\n</body>\n</html>"),
]

# phase 1: check every anchor exists exactly once
for label, old, new in PATCHES:
    n = s.count(old)
    if n != 1:
        sys.exit("Anchor '%s' found %d times (expected 1). Nothing was changed. Send me the landing.html." % (label, n))

# phase 2: backup then write
if not os.path.exists(BK):
    shutil.copy(P, BK)
    print("Backup created:", os.path.relpath(BK, ROOT))
for label, old, new in PATCHES:
    s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("Landing page upgraded. Now commit and push, then hard-refresh the site.")