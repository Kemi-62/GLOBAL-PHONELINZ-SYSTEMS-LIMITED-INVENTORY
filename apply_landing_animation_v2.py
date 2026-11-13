#!/usr/bin/env python3
"""Landing page animation upgrade v2 (LANDING_ANIM_V2).
Run AFTER apply_landing_animation.py, from the project root:  python apply_landing_animation_v2.py
Adds: curved divider under the hero, curved edges around the blue "Why choose us"
section, animated title underline, popping icons, glowing cards and soft moving glows.
Backs up the current page first. Safe to run twice.  Undo: copy the .bak file back.
"""
import os, sys, shutil
P = os.path.join(os.getcwd(), "templates", "landing.html")
if not os.path.exists(P):
    sys.exit("Run this from the project root (templates/landing.html not found).")
s = open(P, encoding="utf-8", newline="").read()
if "LANDING_ANIM_V1" not in s:
    sys.exit("Run apply_landing_animation.py first, then this one.")
if "LANDING_ANIM_V2" in s:
    print("Already upgraded. Nothing to do."); sys.exit(0)

CSS = r"""    /* LANDING_ANIM_V2 — curved section dividers + animated "Why choose us" */
    @keyframes gIconPop{from{opacity:0;transform:scale(.3) rotate(-25deg)}}

    /* curve under the hero (fills with the next section's colour) */
    .hero::after{content:'';position:absolute;left:0;right:0;bottom:-1px;height:56px;z-index:3;pointer-events:none;background:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 60' preserveAspectRatio='none'%3E%3Cpath d='M0,0 Q720,80 1440,0 L1440,61 L0,61 Z' fill='%23f8fafc'/%3E%3C/svg%3E") center bottom/100% 100% no-repeat}
    .slide-dots{bottom:2.1rem}

    /* curves in and out of the blue "Why" section */
    .why{position:relative;overflow:hidden;padding-top:5.5rem;padding-bottom:5.5rem}
    .why::before,.why::after{content:'';position:absolute;left:0;right:0;height:44px;z-index:2;pointer-events:none;background-repeat:no-repeat;background-size:100% 100%}
    .why::before{top:-1px;background-image:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 44' preserveAspectRatio='none'%3E%3Cpath d='M0,0 L1440,0 L1440,10 Q720,56 0,10 Z' fill='%23ffffff'/%3E%3C/svg%3E")}
    .why::after{bottom:-1px;background-image:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 44' preserveAspectRatio='none'%3E%3Cpath d='M0,44 L1440,44 L1440,34 Q720,-12 0,34 Z' fill='%23ffffff'/%3E%3C/svg%3E")}
    .why .container{position:relative;z-index:1}

    /* title underline draws itself, icons pop, cards glow */
    .why .sec-title span{position:relative;display:inline-block}
    .why .sec-title span::after{content:'';position:absolute;left:0;right:0;bottom:-3px;height:3px;border-radius:3px;background:var(--yellow);transform:scaleX(0);transform-origin:left;transition:transform .7s cubic-bezier(.2,.7,.2,1) .35s}
    .why .sec-title.in span::after{transform:scaleX(1)}
    .why-icon{display:inline-flex!important;width:46px;height:46px;border-radius:50%;background:rgba(255,203,5,.15);align-items:center;justify-content:center;font-size:1.3rem;transition:transform .3s cubic-bezier(.3,1.6,.5,1),background .3s}
    .why-card.in .why-icon{animation:gIconPop .6s cubic-bezier(.3,1.6,.5,1) backwards;animation-delay:calc(var(--d,0ms) + .25s)}
    .why-card:hover .why-icon{transform:scale(1.12) rotate(-6deg);background:rgba(255,203,5,.28)}
    .why-card{transition:border-color .25s,background .25s,transform .18s ease-out}
    .why-card:hover{border-color:rgba(255,203,5,.55);background:rgba(255,255,255,.11)}
"""
JS = r"""<script>
/* LANDING_ANIM_V2: glow background inside the Why section (same cheap glows as the hero) */
(function(){
  var why=document.querySelector('.why');
  if(!why)return;
  var a=document.createElement('div');a.className='atmo';a.setAttribute('aria-hidden','true');
  a.innerHTML='<i></i><i></i><i></i>';why.insertBefore(a,why.firstChild);
  if('IntersectionObserver' in window){
    new IntersectionObserver(function(es){a.classList.toggle('paused',!es[0].isIntersecting);}).observe(why);
  }
})();
</script>
"""
PATCHES = [
 ("css", "  </style>\n</head>", CSS + "  </style>\n</head>"),
 ("js", "</script>\n\n</body>\n</html>", "</script>\n\n" + JS + "\n</body>\n</html>"),
]
for label, old, new in PATCHES:
    n = s.count(old)
    if n != 1:
        sys.exit("Anchor '%s' found %d times (expected 1). Nothing was changed." % (label, n))
bk = P + ".v2.bak"
if not os.path.exists(bk):
    shutil.copy(P, bk); print("Backup created: templates/landing.html.v2.bak")
for label, old, new in PATCHES:
    s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("v2 applied. Commit, push, then hard-refresh the site.")