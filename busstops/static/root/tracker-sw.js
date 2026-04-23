const CACHE_NAME = 'araleya-tracker-v1';

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(clients.claim()); });

self.addEventListener('message', e => {
  if (e.data.type === 'START_TRACKING') { trackingConfig = e.data.config; startPinging(); }
  if (e.data.type === 'STOP_TRACKING') { stopPinging(); }
  if (e.data.type === 'LOCATION_UPDATE') { lastLocation = e.data.location; }
});

let trackingConfig = null;
let lastLocation = null;
let pingInterval = null;
let pingCount = 0;

function startPinging() {
  stopPinging();
  pingCount = 0;
  pingInterval = setInterval(doPing, 30000);
}

function stopPinging() {
  if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
}

async function doPing() {
  if (!lastLocation || !trackingConfig) return;
  const { latitude, longitude, heading, speed, accuracy } = lastLocation;
  const when = new Date().toISOString();
  const { noc, fleet, lineName, journeyRef, endpoint } = trackingConfig;
  const deviceId = noc + ':' + fleet + ':' + lineName + ':' + journeyRef;
  const payload = {
    locations: [{ type: "Feature", geometry: { type: "Point", coordinates: [longitude, latitude] },
      properties: { timestamp: when, device_id: deviceId, heading: heading || 0,
        speed: speed || 0, altitude: 0, horizontal_accuracy: accuracy || 0 } }]
  };
  try {
    const res = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    pingCount++;
    const allClients = await clients.matchAll({ type: 'window' });
    allClients.forEach(c => c.postMessage({ type: 'PING_RESULT', ok: res.ok, status: res.status, pingCount, latitude, longitude, heading }));
  } catch(e) {
    const allClients = await clients.matchAll({ type: 'window' });
    allClients.forEach(c => c.postMessage({ type: 'PING_RESULT', ok: false, error: e.message, pingCount }));
  }
}
