#!/usr/bin/env python3
"""Fix check-in location: fresh high-accuracy GPS, best-reading, accuracy gate,
and a 'use my current location' button on the Director's branch locations page."""
import os, sys, shutil
ROOT = os.getcwd()
W = os.path.join(ROOT, "templates/partials/attendance_widget.html")
L = os.path.join(ROOT, "templates/director/manage_locations.html")
for p in (W, L):
    if not os.path.exists(p):
        sys.exit("Run this from the project root. Missing: " + p)

NEW_JS = r'''// GEO_V2: fresh high-accuracy GPS, keeps the best reading
var _geoWatch = null, _geoTimer = null, _geoBest = null;

function _geoStop() {
  if (_geoWatch !== null && navigator.geolocation) { navigator.geolocation.clearWatch(_geoWatch); }
  _geoWatch = null;
  if (_geoTimer) { clearTimeout(_geoTimer); _geoTimer = null; }
}

function _geoShow(locStatus, submitBtn, final) {
  var b = _geoBest;
  if (!b) { return; }
  var acc = Math.round(b.coords.accuracy);
  document.getElementById('att-lat').value = b.coords.latitude;
  document.getElementById('att-lon').value = b.coords.longitude;
  var good = acc <= 60;
  var ok = acc <= 150;
  if (good) {
    locStatus.style.background = '#d1fae5'; locStatus.style.color = '#065f46';
    locStatus.textContent = '✅ Location locked — accuracy ' + acc + 'm';
  } else if (final && !ok) {
    locStatus.style.background = '#fef3c7'; locStatus.style.color = '#92400e';
    locStatus.innerHTML = '⚠️ Weak GPS (accuracy ' + acc + 'm). Step outside or near a window, turn ON Precise/High-accuracy location, then ' +
      '<button type="button" onclick="_retryLocation()" style="padding:.22rem .65rem;background:#004F9F;color:#fff;border:none;border-radius:5px;font-size:.73rem;cursor:pointer;">🔄 Refresh location</button>';
  } else {
    locStatus.style.background = '#fef3c7'; locStatus.style.color = '#92400e';
    locStatus.textContent = '📡 Improving GPS… accuracy ' + acc + 'm';
  }
  submitBtn.disabled = !ok && !final ? true : false;
  if (final && !ok) { submitBtn.disabled = false; }
}

function _tryGetLocation(_ignored, locStatus, submitBtn) {
  _geoStop();
  _geoBest = null;
  if (!navigator.geolocation) {
    locStatus.innerHTML = '❌ Geolocation is not supported on this browser.';
    locStatus.style.background = '#fee2e2'; locStatus.style.color = '#991b1b';
    return;
  }
  submitBtn.disabled = true;
  _geoWatch = navigator.geolocation.watchPosition(
    function(pos) {
      if (!_geoBest || pos.coords.accuracy < _geoBest.coords.accuracy) { _geoBest = pos; }
      var good = _geoBest.coords.accuracy <= 30;
      _geoShow(locStatus, submitBtn, false);
      if (good) { _geoStop(); }
    },
    function(err) {
      _geoStop();
      if (_geoBest) { _geoShow(locStatus, submitBtn, true); return; }
      var msg = '❌ ';
      if (err.code === 1) {
        msg += 'Permission denied. Open browser settings → Site Settings → Location → Allow for this site.';
      } else if (err.code === 2) {
        msg += 'GPS signal not available. Move to an open area and make sure Location is ON in phone settings.';
      } else {
        msg += 'Location timed out. Make sure GPS is ON and try again.';
      }
      locStatus.style.background = '#fee2e2'; locStatus.style.color = '#991b1b';
      locStatus.innerHTML = msg + ' <button type="button" onclick="_retryLocation()" style="margin-top:.4rem;display:inline-block;padding:.22rem .65rem;background:#004F9F;color:#fff;border:none;border-radius:5px;font-size:.73rem;cursor:pointer;">🔄 Try Again</button>';
    },
    { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 }
  );
  _geoTimer = setTimeout(function() {
    _geoStop();
    if (_geoBest) { _geoShow(locStatus, submitBtn, true); }
    else {
      locStatus.style.background = '#fee2e2'; locStatus.style.color = '#991b1b';
      locStatus.innerHTML = '❌ No GPS fix yet. Turn ON location, step outside, then <button type="button" onclick="_retryLocation()" style="padding:.22rem .65rem;background:#004F9F;color:#fff;border:none;border-radius:5px;font-size:.73rem;cursor:pointer;">🔄 Try Again</button>';
    }
  }, 20000);
}

function _retryLocation() {
  var locStatus = document.getElementById('att-location-status');
  var submitBtn = document.getElementById('att-submit-btn');
  locStatus.style.background = '#eff6ff'; locStatus.style.color = '#1e40af';
  locStatus.textContent = '📡 Refreshing location…';
  _tryGetLocation(true, locStatus, submitBtn);
}

'''

def backup(p):
    if not os.path.exists(p + ".bak"):
        shutil.copy(p, p + ".bak")

# ---- widget ----
s = open(W, encoding="utf-8").read()
if "GEO_V2" in s:
    print("widget: already patched")
else:
    a = s.find("function _tryGetLocation")
    b = s.find("function closeAttModal")
    if a < 0 or b < 0 or b < a:
        sys.exit("widget: expected functions not found, nothing changed")
    s2 = s[:a] + NEW_JS + s[b:]
    s2 = s2.replace("function closeAttModal() {\n", "function closeAttModal() {\n  _geoStop();\n", 1)
    backup(W); open(W, "w", encoding="utf-8").write(s2)
    print("widget: patched")

# ---- locations page ----
t = open(L, encoding="utf-8").read()
if "GEO_V2" in t:
    print("locations: already patched")
else:
    old_btn = '<label style="margin-top:15px;">Latitude (e.g., 6.5244)</label>'
    new_btn = ('<!-- GEO_V2 -->\n<div style="margin-top:15px;padding:10px;background:#eff6ff;border-radius:6px;">'
               '<button type="button" id="use-here" onclick="useHere()" class="btn btn-primary">📍 Use my current location</button> '
               '<small id="use-here-msg" style="color:#1e40af;">Open this page on your phone while standing inside the branch, then tap.</small></div>\n'
               + old_btn)
    old_js = "function hideForm() {"
    new_js = '''function useHere() {
    var msg = document.getElementById('use-here-msg');
    if (!navigator.geolocation) { msg.textContent = 'Geolocation not supported.'; return; }
    msg.textContent = 'Getting the best GPS fix (up to 20s)...';
    var best = null, id = null, done = false;
    function finish() {
        if (done) return; done = true;
        navigator.geolocation.clearWatch(id);
        if (!best) { msg.textContent = 'No GPS fix. Turn on location and try again.'; return; }
        document.getElementById('latitude').value = best.coords.latitude.toFixed(6);
        document.getElementById('longitude').value = best.coords.longitude.toFixed(6);
        var acc = Math.round(best.coords.accuracy);
        msg.textContent = 'Filled. Accuracy ' + acc + 'm' + (acc > 50 ? ' - weak, go outside and tap again.' : ' - good. Now press Save Location.');
    }
    id = navigator.geolocation.watchPosition(function(p) {
        if (!best || p.coords.accuracy < best.coords.accuracy) best = p;
        msg.textContent = 'Accuracy so far: ' + Math.round(best.coords.accuracy) + 'm...';
        if (best.coords.accuracy <= 15) finish();
    }, function() { finish(); }, {enableHighAccuracy: true, timeout: 25000, maximumAge: 0});
    setTimeout(finish, 20000);
}

function hideForm() {'''
    if old_btn not in t or old_js not in t:
        sys.exit("locations: anchors not found, nothing changed")
    t = t.replace(old_btn, new_btn, 1).replace(old_js, new_js, 1)
    t = t.replace('step="0.0001"', 'step="0.000001"')
    backup(L); open(L, "w", encoding="utf-8").write(t)
    print("locations: patched")
print("Done. No migration needed.")