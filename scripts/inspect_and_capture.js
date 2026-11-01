import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9222;
const OUTPUT_DIR = path.resolve('outputs/screenshots');

if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function sendCDP(ws, method, params = {}) {
  const id = Math.floor(Math.random() * 1000000);
  return new Promise((resolve, reject) => {
    const handler = (event) => {
      const msg = JSON.parse(event.data.toString());
      if (msg.id === id) {
        ws.removeEventListener('message', handler);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function captureScreen(ws, filename) {
  const { data } = await sendCDP(ws, 'Page.captureScreenshot', { format: 'png' });
  const buffer = Buffer.from(data, 'base64');
  const filepath = path.join(OUTPUT_DIR, filename);
  fs.writeFileSync(filepath, buffer);
  console.log(`Saved screenshot: ${filepath} (${buffer.length} bytes)`);
}

async function main() {
  console.log('Launching headless Chrome with remote debugging on port ' + PORT);
  const tempProfile = path.resolve('outputs/temp_chrome_profile');
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    `--user-data-dir=${tempProfile}`,
    'about:blank'
  ]);

  // Wait for debugger port
  let ready = false;
  for (let i = 0; i < 30; i++) {
    await sleep(300);
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (res.ok) {
        ready = true;
        break;
      }
    } catch (_) {}
  }

  if (!ready) {
    chromeProc.kill();
    throw new Error('Chrome failed to start within timeout');
  }

  // Query existing page target from /json/list
  const targetsRes = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  const targets = await targetsRes.json();
  const pageTarget = targets.find(t => t.type === 'page') || targets[0];
  if (!pageTarget || !pageTarget.webSocketDebuggerUrl) {
    chromeProc.kill();
    throw new Error('No page target found in Chrome');
  }

  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', reject);
  });

  const consoleLogs = [];
  const errors = [];

  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data.toString());
    if (msg.method === 'Runtime.consoleAPICalled') {
      const text = msg.params.args.map(a => a.value || JSON.stringify(a)).join(' ');
      consoleLogs.push({ type: msg.params.type, text });
      if (msg.params.type === 'error') {
        errors.push(text);
      }
    } else if (msg.method === 'Runtime.exceptionThrown') {
      const desc = msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text;
      errors.push(desc);
    }
  });

  await sendCDP(ws, 'Runtime.enable');
  await sendCDP(ws, 'Page.enable');

  console.log('Navigating to http://localhost:5173/...');
  await sendCDP(ws, 'Page.navigate', { url: 'http://localhost:5173/' });
  await sleep(2000);

  // 1. Set Desktop Viewport 1920x1080
  console.log('Setting desktop viewport 1920x1080...');
  await sendCDP(ws, 'Emulation.setDeviceMetricsOverride', {
    width: 1920,
    height: 1080,
    deviceScaleFactor: 1,
    mobile: false
  });

  // Wait for initial telemetry and DOM hydration
  await sleep(2500);

  // Capture Tab 1: Live Corridor
  await captureScreen(ws, 'desktop_live_corridor.png');

  // Helper to click tab by matching text content
  async function clickTab(tabText) {
    console.log(`Clicking tab: "${tabText}"...`);
    await sendCDP(ws, 'Runtime.evaluate', {
      expression: `(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const target = buttons.find(b => b.textContent.includes('${tabText}'));
        if (target) { target.click(); return true; }
        return false;
      })()`
    });
  }

  // Tab 2: Emissions & Benchmarks
  await clickTab('Emissions & Benchmarks');
  await sleep(1500);
  await captureScreen(ws, 'desktop_analytics.png');

  // Tab 3: Accident Hotspots & Risk Zones
  await clickTab('Accident Hotspots & Risk Zones');
  await sleep(1500);
  await captureScreen(ws, 'desktop_safety.png');

  // Tab 4: What-If Sandbox & History
  await clickTab('What-If Sandbox & History');
  await sleep(1500);
  await captureScreen(ws, 'desktop_sandbox.png');

  // Tab 5: 3D Digital Twin
  await clickTab('3D Digital Twin');
  await sleep(3500); // Allow WebGL BufferGeometries to mount and render
  await captureScreen(ws, 'desktop_3d_twin.png');

  // 2. Set Mobile Viewport 390x844 (iPhone 14 / modern smartphone)
  console.log('Setting mobile viewport 390x844...');
  await sendCDP(ws, 'Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 2,
    mobile: true
  });

  // Mobile Tab 1: Live Corridor
  await clickTab('Live Corridor & Signals');
  await sleep(1500);
  await captureScreen(ws, 'mobile_live_corridor.png');

  // Mobile Tab 5: 3D Digital Twin
  await clickTab('3D Digital Twin');
  await sleep(2500);
  await captureScreen(ws, 'mobile_3d_twin.png');

  // Clean shutdown
  ws.close();
  chromeProc.kill();

  console.log('\n--- Console Logs Summary ---');
  console.log(`Total console entries: ${consoleLogs.length}`);
  console.log(`Critical errors: ${errors.length}`);
  if (errors.length > 0) {
    console.error('Errors encountered:');
    errors.forEach(e => console.error('  - ' + e));
  } else {
    console.log('Zero critical errors detected in browser execution.');
  }

  // Save report JSON
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'inspection_summary.json'),
    JSON.stringify({
      timestamp: new Date().toISOString(),
      viewports: ['1920x1080 (Desktop)', '390x844 (Mobile)'],
      screenshots: [
        'desktop_live_corridor.png',
        'desktop_analytics.png',
        'desktop_safety.png',
        'desktop_sandbox.png',
        'desktop_3d_twin.png',
        'mobile_live_corridor.png',
        'mobile_3d_twin.png'
      ],
      total_console_logs: consoleLogs.length,
      errors: errors
    }, null, 2)
  );
}

main().catch(err => {
  console.error('Inspection failed:', err);
  process.exit(1);
});
