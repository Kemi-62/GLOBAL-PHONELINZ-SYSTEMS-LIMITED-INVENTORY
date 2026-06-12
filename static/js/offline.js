/**
 * GPSL Offline Queue — IndexedDB-based offline form storage
 * Queues attendance, sales, and stock records when offline
 * Auto-syncs when connection returns via Background Sync API
 */

const DB_NAME = 'GPSL_Offline';
const DB_VERSION = 2;

const STORES = ['forms', 'attendance', 'stock'];

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      STORES.forEach(s => {
        if (!db.objectStoreNames.contains(s)) {
          db.createObjectStore(s, {keyPath: 'id', autoIncrement: true});
        }
      });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = e => reject(e.target.error);
  });
}

async function queueForm(store, data) {
  const db = await openDB();
  const tx = db.transaction(store, 'readwrite');
  const obj = tx.objectStore(store);
  const entry = { ...data, queuedAt: Date.now(), synced: false };
  return new Promise((resolve, reject) => {
    const req = obj.add(entry);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function getQueued(store) {
  const db = await openDB();
  const tx = db.transaction(store, 'readonly');
  const obj = tx.objectStore(store);
  return new Promise((resolve, reject) => {
    const req = obj.getAll();
    req.onsuccess = () => resolve(req.result.filter(r => !r.synced));
    req.onerror = () => reject(req.error);
  });
}

async function markSynced(store, id) {
  const db = await openDB();
  const tx = db.transaction(store, 'readwrite');
  const obj = tx.objectStore(store);
  const req = obj.get(id);
  return new Promise((resolve, reject) => {
    req.onsuccess = () => {
      const data = req.result;
      if (data) { data.synced = true; obj.put(data); }
      resolve(data);
    };
    req.onerror = () => reject(req.error);
  });
}

async function deleteSynced(store) {
  const db = await openDB();
  const tx = db.transaction(store, 'readwrite');
  const obj = tx.objectStore(store);
  const all = await new Promise((resolve, reject) => {
    const r = obj.getAll();
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
  for (const item of all) {
    if (item.synced) obj.delete(item.id);
  }
}

async function getPendingCount() {
  let count = 0;
  for (const store of STORES) {
    const queued = await getQueued(store);
    count += queued.length;
  }
  return count;
}

// Hook into attendance form submission
function setupOfflineForm(formId, store, endpoint, extraFields) {
  const form = document.getElementById(formId);
  if (!form) return;

  form.addEventListener('submit', async e => {
    if (!navigator.onLine) {
      e.preventDefault();
      const data = new FormData(form);
      const payload = {};
      data.forEach((v, k) => payload[k] = v);
      if (extraFields) Object.assign(payload, extraFields);
      await queueForm(store, { payload, endpoint, method: 'POST' });
      showOfflineToast('Attendance check saved. Will sync when online.');
      return false;
    }
  });
}

// Network status indicator
function showOfflineToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:9999;background:#004F9F;color:#fff;padding:1rem 1.2rem;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.15);font-size:.88rem;max-width:300px;animation:slideIn .3s ease;';
  toast.innerHTML = `<div style="display:flex;align-items:flex-start;gap:.6rem;"><span style="font-size:1.2rem;">📡</span><div><strong>Offline</strong><br>${msg}</div><button onclick="this.parentElement.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:#fff;font-size:1.1rem;margin-left:auto;">✕</button></div>`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

// Sync all queued items
async function syncAll() {
  if (!navigator.onLine) return;
  for (const store of STORES) {
    const queued = await getQueued(store);
    for (const item of queued) {
      try {
        const resp = await fetch(item.endpoint, {
          method: item.method || 'POST',
          headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams(item.payload)
        });
        if (resp.ok) await markSynced(store, item.id);
      } catch (err) {
        console.error('Sync failed for', item.id, err);
      }
    }
  }
  await deleteSynced('forms');
  await deleteSynced('attendance');
  await deleteSynced('stock');
}

function getCsrfToken() {
  const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return el ? el.value : '';
}

// Listen for online/offline
window.addEventListener('online', () => {
  showOfflineToast('Back online! Syncing queued data...');
  syncAll();
  // Register background sync
  if ('serviceWorker' in navigator && navigator.serviceWorker.ready) {
    navigator.serviceWorker.ready.then(reg => reg.sync.register('sync-forms'));
  }
});

window.addEventListener('offline', () => {
  showOfflineToast('You are offline. Forms will be saved locally.');
});

// Auto-init
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('att-form')) {
      setupOfflineForm('att-form', 'attendance', '/check-in/');
    }
  });
} else {
  if (document.getElementById('att-form')) {
    setupOfflineForm('att-form', 'attendance', '/check-in/');
  }
}

// Export for inline scripts
window.GPSLOffline = { queueForm, getQueued, syncAll, getPendingCount, showOfflineToast };
