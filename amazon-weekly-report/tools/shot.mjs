// Full-page + per-section screenshots via Chrome DevTools Protocol.
// Usage: node tools/shot.mjs <report.html> <out-dir> [width]
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const CHROME = process.env.CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const file = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3] || path.dirname(file));
const width = Number(process.argv[4] || 940);
const port = 9333 + Math.floor(Math.random() * 200);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wreport-shot-'));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitJson(url, tries = 60) {
  for (let i = 0; i < tries; i += 1) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(250);
  }
  throw new Error('Chrome did not start: ' + url);
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    this.id += 1;
    const id = this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', '--force-device-scale-factor=1',
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, 'about:blank',
  ], { stdio: 'ignore' });

  try {
    await waitJson(`http://127.0.0.1:${port}/json/version`);
    const target = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent('file:///' + file.replace(/\\/g, '/'))}`, { method: 'PUT' }).then((r) => r.json());
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve);
      ws.addEventListener('error', reject);
    });
    const cdp = new CDP(ws);
    await cdp.send('Page.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width, height: 1200, deviceScaleFactor: 1, mobile: false });
    await sleep(1200);

    const env = await cdp.send('Runtime.evaluate', { expression: 'JSON.stringify({secure:isSecureContext, ClipboardItem:typeof ClipboardItem, clipboard:!!navigator.clipboard})', returnByValue: true });
    console.log('clipboard-env', env.result.value);
    const metrics = await cdp.send('Page.getLayoutMetrics');
    const content = metrics.cssContentSize || metrics.contentSize;
    const height = Math.ceil(content.height);
    const shot = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
      clip: { x: 0, y: 0, width, height, scale: 1 },
    });
    fs.writeFileSync(path.join(outDir, 'report-full.png'), Buffer.from(shot.data, 'base64'));

    const sections = await cdp.send('Runtime.evaluate', {
      expression: `Array.from(document.querySelectorAll('h2, h3, h4')).map(function(h){return {title:h.textContent.trim(), top:h.getBoundingClientRect().top+window.scrollY};})`,
      returnByValue: true,
    });
    const marks = sections.result.value || [];
    for (let i = 0; i < marks.length; i += 1) {
      const top = Math.max(0, marks[i].top - 20);
      const bottom = i + 1 < marks.length ? marks[i + 1].top - 20 : height;
      const clipHeight = Math.min(bottom - top, 2000);
      if (clipHeight < 80) continue;
      const part = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: true,
        clip: { x: 0, y: top, width, height: clipHeight, scale: 1 },
      });
      const safe = String(i + 1).padStart(2, '0');
      const slug = marks[i].title.replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 24);
      fs.writeFileSync(path.join(outDir, `section-${safe}-${slug}.png`), Buffer.from(part.data, 'base64'));
    }
    ws.close();
    console.log(JSON.stringify({ height, sections: marks.length, outDir }));
  } finally {
    chrome.kill();
    await sleep(300);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
