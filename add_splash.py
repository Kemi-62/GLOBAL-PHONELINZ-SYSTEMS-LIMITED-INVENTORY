"""
Add wake-up splash screen to base.html
Run: python /home/runner/workspace/add_splash.py
"""

WORKSPACE = '/home/runner/workspace'
BASE_HTML = f'{WORKSPACE}/templates/base.html'

code = open(BASE_HTML).read()

# The splash screen + bounce animation + smart timer
# Shows only if page takes more than 2 seconds (cold start)
# Disappears instantly on fast loads
SPLASH = '''<div id="wake-splash" style="display:none;position:fixed;inset:0;background:#004F9F;z-index:99999;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:Arial,sans-serif;">
  <div style="text-align:center;margin-bottom:2rem;">
    <div style="font-size:3rem;font-weight:700;color:#FFCB05;letter-spacing:2px;margin-bottom:.3rem;">GPSL</div>
    <div style="font-size:.85rem;opacity:.75;letter-spacing:1px;">GLOBAL PHONELINZ SYSTEMS LIMITED</div>
  </div>
  <div style="display:flex;gap:10px;margin-bottom:1.5rem;">
    <div style="width:12px;height:12px;border-radius:50%;background:#FFCB05;animation:gpsl-bounce 1s infinite 0s"></div>
    <div style="width:12px;height:12px;border-radius:50%;background:#FFCB05;animation:gpsl-bounce 1s infinite .2s"></div>
    <div style="width:12px;height:12px;border-radius:50%;background:#FFCB05;animation:gpsl-bounce 1s infinite .4s"></div>
  </div>
  <p style="font-size:.78rem;opacity:.55;margin:0;">Starting up, please wait&hellip;</p>
</div>
<style>
@keyframes gpsl-bounce {
  0%,100%{transform:translateY(0);opacity:1}
  50%{transform:translateY(-10px);opacity:.6}
}
</style>
<script>
(function() {
  var splash = document.getElementById('wake-splash');
  var timer = setTimeout(function() {
    if (splash) splash.style.display = 'flex';
  }, 2000);
  window.addEventListener('load', function() {
    clearTimeout(timer);
    if (splash) splash.style.display = 'none';
  });
})();
</script>

'''

OLD_BODY = '<body>\n\n<div id="overlay"'
NEW_BODY = '<body>\n\n' + SPLASH + '<div id="overlay"'

if 'wake-splash' in code:
    print("Splash screen already exists in base.html. Skipped.")
elif OLD_BODY in code:
    code = code.replace(OLD_BODY, NEW_BODY, 1)
    open(BASE_HTML, 'w').write(code)
    print("Splash screen added successfully to base.html")
else:
    # Fallback - just insert after <body>
    code = code.replace('<body>\n', '<body>\n\n' + SPLASH, 1)
    open(BASE_HTML, 'w').write(code)
    print("Splash screen added (fallback method). Verify base.html looks correct.")

print("\nDone. Now:")
print("1. python manage.py runserver 0.0.0.0:8000")
print("2. Open your app and check the splash appears on first load")
print("3. git add templates/base.html && git commit -m 'Add wake-up splash screen' && git push")
