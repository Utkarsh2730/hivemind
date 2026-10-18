"""Record the Hivemind demo video for YouTube (1920x1080, 30 fps, H.264 + AAC, burned-in captions).

Drives a real headless Chrome session against a running Hivemind server, narrates each scene with the macOS
`say` voice, and writes:
  video/hivemind-demo.mp4        the video
  video/hivemind-thumbnail.jpg   1280x720 thumbnail
  video/youtube.txt              title, description and chapters

Usage:  .venv/bin/python scripts/make_demo_video.py   (server must be running at BASE, default http://localhost:8000)
Needs:  pip install imageio-ffmpeg websocket-client pillow fonttools brotli ; macOS `say` ; Google Chrome
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave

import imageio_ffmpeg
import websocket
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "video")
BASE = os.environ.get("BASE", "http://localhost:8000")
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
VOICE = os.environ.get("VOICE", "Samantha")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1920, 1080, 30
CSS_W, CSS_H = 1440, 810            # page laid out at 1440x810, rendered at 4/3 scale -> 1920x1080
SR = 44100
WORK = tempfile.mkdtemp(prefix="hivemind-video-")

INK, NIGHT, NIGHT2, AMBER, MUTED = (27, 24, 56), (19, 17, 43), (29, 26, 69), (245, 158, 11), (185, 181, 230)


def font(kind, size, wght=None, opsz=None):
    files = {"serif": "Fraunces-9e509503.ttf", "serif-italic": "Fraunces-d5715532.ttf",
             "sans": "Inter-bec94a4d.ttf", "mono": "JetBrainsMono-b87346fd.ttf"}
    f = ImageFont.truetype(os.path.join(OUT, "fonts", files[kind]), size)
    try:
        axes = f.get_variation_axes()
        vals = []
        for a in axes:
            name = a.get("name", b"")
            name = name.decode() if isinstance(name, bytes) else str(name)
            if "ptical" in name or name.lower().startswith("opsz"):
                vals.append(opsz or min(144, max(9, size / 2)))
            else:
                vals.append(wght or 400)
        f.set_variation_by_axes(vals)
    except Exception:
        pass
    return f


# ---------------------------------------------------------------- narration

def tts(text, idx):
    aiff, wav = os.path.join(WORK, f"n{idx}.aiff"), os.path.join(WORK, f"n{idx}.wav")
    subprocess.run(["say", "-v", VOICE, "-r", "178", "-o", aiff, text], check=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", aiff, "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", wav], check=True)
    with wave.open(wav) as w:
        return wav, w.getnframes() / SR


GAP, LEAD, TAIL = 0.45, 0.5, 0.9


class Scene:
    def __init__(self, title, sentences, action=None, card=None):
        self.title, self.sentences, self.action, self.card = title, sentences, action, card
        self.frames, self.length = [], 0.0

    def narrate(self, idx0):
        self.audio = [tts(s, f"{idx0}_{i}") for i, s in enumerate(self.sentences)]  # (wav, seconds)
        self.starts = [None] * len(self.sentences)

    # Sentences start back to back, but a sentence with a cue (see at()) waits until the screen reaches it,
    # so the voice never runs ahead of what is shown.
    def earliest(self, i):
        if i == 0:
            return LEAD
        self.fill(i - 1)
        return self.starts[i - 1] + self.audio[i - 1][1] + GAP

    def fill(self, upto):
        for j in range(upto + 1):
            if self.starts[j] is None:
                self.starts[j] = self.earliest(j)

    @property
    def schedule(self):
        self.fill(len(self.sentences) - 1)
        return [(st, st + d, s, wav) for st, (wav, d), s in zip(self.starts, self.audio, self.sentences)]

    @property
    def narration_len(self):
        a, e, _, _ = self.schedule[-1]
        return e + TAIL


# ---------------------------------------------------------------- Chrome DevTools

class CDP:
    def __init__(self, ws_url, timeout=None):
        self.ws = websocket.create_connection(ws_url, max_size=None, suppress_origin=True, timeout=timeout)
        self.id, self.lock = 0, threading.Lock()

    def call(self, method, **params):
        with self.lock:
            self.id += 1
            mid = self.id
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
            while True:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

    def js(self, expr, timeout=60):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True, timeout=timeout * 1000)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "JS error"))
        return r.get("result", {}).get("value")


HELPER = r"""
(() => {
  if (window.__demo) return;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const st = document.createElement('style');
  st.textContent = `#__cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;will-change:transform}
    #__cur svg{width:26px;height:26px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
    .__rp{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #f59e0b;z-index:2147483646;
      pointer-events:none;animation:__rp .55s ease-out forwards}
    @keyframes __rp{from{transform:scale(.3);opacity:1}to{transform:scale(1.5);opacity:0}}
    html{scroll-behavior:auto!important}`;
  const cur = document.createElement('div'); cur.id = '__cur';
  cur.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 2l16 9.5-7 1.6L9.6 20z" fill="#fff" stroke="#13112b" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const mount = () => { document.head.appendChild(st); document.body.appendChild(cur); };
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
  const D = window.__demo = { x: innerWidth * 0.62, y: innerHeight * 0.55 };
  cur.style.transform = `translate(${D.x}px,${D.y}px)`;
  D.move = async (x, y, ms = 650) => {
    const x0 = D.x, y0 = D.y, t0 = performance.now();
    while (true) {
      const k = Math.min(1, (performance.now() - t0) / ms), e = k < .5 ? 4*k*k*k : 1 - Math.pow(-2*k + 2, 3) / 2;
      D.x = x0 + (x - x0) * e; D.y = y0 + (y - y0) * e;
      cur.style.transform = `translate(${D.x}px,${D.y}px)`;
      if (k >= 1) break; await sleep(16);
    }
  };
  D.el = sel => { const el = typeof sel === 'string' ? document.querySelector(sel) : sel; if (!el) throw new Error('missing ' + sel); return el; };
  D.point = async (sel, ms) => { const el = D.el(sel); const r = el.getBoundingClientRect();
    await D.move(r.left + Math.min(r.width / 2, 120), r.top + r.height / 2, ms); return el; };
  D.click = async (sel, ms) => { const el = await D.point(sel, ms);
    const rp = document.createElement('div'); rp.className = '__rp'; rp.style.left = D.x + 'px'; rp.style.top = D.y + 'px';
    document.body.appendChild(rp); setTimeout(() => rp.remove(), 700); await sleep(140); el.click(); await sleep(120); };
  D.type = async (sel, text, cps = 26) => { const el = await D.click(sel) || D.el(sel); const t = D.el(sel); t.focus(); t.value = '';
    for (const c of text) { t.value += c; t.dispatchEvent(new Event('input', { bubbles: true })); await sleep(1000 / cps); } };
  D.waitFor = async (sel, ms = 20000) => { const t0 = Date.now(); while (!document.querySelector(sel)) { if (Date.now() - t0 > ms) throw new Error('timeout ' + sel); await sleep(80); } };
  D.waitGone = async (sel, ms = 30000) => { const t0 = Date.now(); while (document.querySelector(sel)) { if (Date.now() - t0 > ms) return; await sleep(80); } };
  D.scroll = async (sel, top, ms = 1200) => { const el = sel ? D.el(sel) : document.scrollingElement; const y0 = el.scrollTop, t0 = performance.now();
    while (true) { const k = Math.min(1, (performance.now() - t0) / ms), e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
      el.scrollTop = y0 + (top - y0) * e; if (k >= 1) break; await sleep(16); } };
  D.scrollToEl = async (box, sel, pad = 40, ms = 1300) => { const c = D.el(box), el = D.el(sel);
    const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - pad; await D.scroll(box, top, ms); };
})();
"""


class Browser:
    def __init__(self):
        self.profile = tempfile.mkdtemp(prefix="hivemind-chrome-")
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={self.profile}",
                                      "--hide-scrollbars", "--mute-audio", "--no-first-run", "--disable-gpu",
                                      f"--window-size={CSS_W},{CSS_H}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.1)
        self.ws_url = page["webSocketDebuggerUrl"]
        self.act = CDP(self.ws_url)
        self.act.call("Emulation.setDeviceMetricsOverride", width=CSS_W, height=CSS_H, deviceScaleFactor=W / CSS_W, mobile=False)
        self.cap = type("Nil", (), {"ws": None})()
        self._connect_capture()
        self.act.call("Page.enable")
        self.act.call("Page.addScriptToEvaluateOnNewDocument", source=HELPER)
        self.act.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        self.recording, self.frames, self.t0 = False, [], 0.0
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def _connect_capture(self):
        # Separate connection with a timeout: a screenshot requested mid-navigation can go unanswered.
        try:
            self.cap.ws.close()
        except Exception:
            pass
        self.cap = CDP(self.ws_url, timeout=4)
        self.cap.call("Emulation.setDeviceMetricsOverride", width=CSS_W, height=CSS_H, deviceScaleFactor=W / CSS_W, mobile=False)

    def _capture_loop(self):
        n = 0
        while True:
            if not self.recording:
                time.sleep(0.01)
                continue
            t = time.time() - self.t0
            try:
                data = self.cap.call("Page.captureScreenshot", format="jpeg", quality=92, optimizeForSpeed=True)["data"]
            except Exception:
                time.sleep(0.2)
                try:
                    self._connect_capture()
                except Exception:
                    pass
                continue
            path = os.path.join(WORK, f"f{n:06d}.jpg")
            import base64
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(data))
            if self.recording:
                self.frames.append((t, path))
            n += 1

    def goto(self, url, settle=1.2):
        self.act.call("Page.navigate", url=url)
        for _ in range(200):
            if self.act.js("document.readyState") == "complete":
                break
            time.sleep(0.05)
        self.act.js(HELPER)
        time.sleep(settle)

    def start(self):
        self.frames, self.t0, self.recording = [], time.time(), True

    def stop(self):
        self.recording = False
        time.sleep(0.15)
        return list(self.frames), time.time() - self.t0

    def close(self):
        self.proc.terminate()
        shutil.rmtree(self.profile, ignore_errors=True)


# ---------------------------------------------------------------- cards and captions

def card(kind):
    img = Image.new("RGB", (W, H), NIGHT)
    g = Image.new("RGB", (W, H), NIGHT2)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((W * 0.45, -H * 0.4, W * 1.35, H * 0.9), fill=170)
    img = Image.composite(g, img, mask.filter(ImageFilter.GaussianBlur(160)))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 36):  # dot grid
        for y in range(0, H, 36):
            d.point((x, y), fill=(44, 40, 92))
    # logo
    lx, ly, s = 160, 150, 92
    d.rounded_rectangle((lx, ly, lx + s, ly + s), radius=22, fill=AMBER)
    import math
    hexp = [(lx + s / 2 + 0.33 * s * math.cos(math.radians(a)), ly + s / 2 + 0.33 * s * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    d.polygon(hexp, outline=NIGHT, width=5)
    for px, py in [(0.5, 0.42), (0.37, 0.61), (0.63, 0.61)]:
        d.ellipse((lx + px * s - 6, ly + py * s - 6, lx + px * s + 6, ly + py * s + 6), fill=NIGHT)
    d.text((lx + s + 26, ly + 18), "Hivemind", font=font("sans", 50, 600), fill=(255, 255, 255))
    if kind == "title":
        d.text((160, 370), "The memory your company", font=font("serif", 112, 600, 144), fill=(255, 255, 255))
        d.text((160, 500), "never had.", font=font("serif-italic", 112, None, 144), fill=AMBER)
        d.text((164, 700), "Cited answers, decision history and sprint plans from one FalkorDB knowledge graph.",
               font=font("sans", 36, 400), fill=MUTED)
        d.text((164, 900), "WEMAKEDEVS × FALKORDB HACKATHON  ·  TRACK 03", font=font("mono", 28, 500), fill=(152, 147, 201))
    else:
        d.text((160, 330), "One private graph per company.", font=font("serif", 92, 600, 144), fill=(255, 255, 255))
        d.text((160, 450), "Answers with receipts.", font=font("serif-italic", 92, None, 144), fill=AMBER)
        d.text((164, 640), "github.com/Utkarsh2730/hivemind", font=font("mono", 40, 500), fill=(233, 231, 255))
        d.text((164, 710), "Run it in the cloud or fully offline with  docker compose up", font=font("sans", 34, 400), fill=MUTED)
        d.text((164, 900), "BUILT WITH FALKORDB  ·  FASTAPI  ·  CLAUDE  ·  MCP", font=font("mono", 28, 500), fill=(152, 147, 201))
    return img


CAP_FONT = None


def wrap(text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def caption_layer(text):
    global CAP_FONT
    CAP_FONT = CAP_FONT or font("sans", 38, 500)
    lines = wrap(text, CAP_FONT, 1500)
    lh = 52
    box_h = lh * len(lines) + 34
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bw = max(CAP_FONT.getlength(l) for l in lines) + 64
    x0, y0 = (W - bw) / 2, H - 70 - box_h
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + box_h), radius=16, fill=(19, 17, 43, 215))
    for i, l in enumerate(lines):
        d.text(((W - CAP_FONT.getlength(l)) / 2, y0 + 17 + i * lh), l, font=CAP_FONT, fill=(255, 255, 255, 255))
    return layer


def make_thumbnail(path):
    """1280x720 YouTube thumbnail: big headline left, product screenshot right."""
    TW, TH = 1280, 720
    img = card("title").resize((TW, TH), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, TW, TH), fill=NIGHT)  # clean background, redraw below
    glow = Image.new("RGB", (TW, TH), NIGHT2)
    mask = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(mask).ellipse((TW * 0.45, -TH * 0.5, TW * 1.4, TH * 1.1), fill=200)
    img = Image.composite(glow, img, mask.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)
    shot = os.path.join(ROOT, "docs", "ask.png")
    if os.path.exists(shot):
        s = Image.open(shot).convert("RGB")
        s = s.crop((int(s.width * 0.17), int(s.height * 0.06), s.width, int(s.height * 0.78)))
        s = s.resize((700, int(700 * s.height / s.width)), Image.LANCZOS)
        fr = Image.new("RGB", (s.width + 10, s.height + 10), (255, 255, 255))
        fr.paste(s, (5, 5))
        fr = fr.rotate(-4, expand=True, resample=Image.BICUBIC, fillcolor=NIGHT)
        shadow = Image.new("RGBA", fr.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle((20, 20, fr.width - 20, fr.height - 20), fill=(0, 0, 0, 150))
        shadow = shadow.filter(ImageFilter.GaussianBlur(24))
        x, y = TW - fr.width + 90, (TH - fr.height) // 2 + 40
        img.paste(shadow, (x + 10, y + 18), shadow)
        img.paste(fr, (x, y))
        d = ImageDraw.Draw(img)
    # left column
    lx, ly, s2 = 64, 60, 64
    d.rounded_rectangle((lx, ly, lx + s2, ly + s2), radius=16, fill=AMBER)
    import math
    hexp = [(lx + s2 / 2 + 0.33 * s2 * math.cos(math.radians(a)), ly + s2 / 2 + 0.33 * s2 * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    d.polygon(hexp, outline=NIGHT, width=4)
    d.text((lx + s2 + 18, ly + 10), "Hivemind", font=font("sans", 40, 700), fill=(255, 255, 255))
    big = font("serif", 92, 650, 144)
    d.text((60, 200), "The memory", font=big, fill=(255, 255, 255))
    d.text((60, 300), "your company", font=big, fill=(255, 255, 255))
    d.text((60, 400), "never had.", font=font("serif-italic", 92, None, 144), fill=AMBER)
    d.rounded_rectangle((64, 560, 470, 616), radius=28, fill=AMBER)
    d.text((88, 571), "FalkorDB knowledge graph", font=font("sans", 27, 700), fill=NIGHT)
    img.save(path, quality=93)


# ---------------------------------------------------------------- scenes

def at(scene, browser, i, extra=0.0):
    """Cue sentence i: wait until the voice is free to say it, then start it now (later if the screen was slow)."""
    if scene.starts[i] is not None:
        return
    target = scene.earliest(i) + extra
    while time.time() - browser.t0 < target:
        time.sleep(0.02)
    scene.starts[i] = max(target, time.time() - browser.t0)


def s_problem(sc, b):
    b.act.js("__demo.move(innerWidth*0.7, innerHeight*0.45, 900)")
    at(sc, b, 3)
    b.act.js("__demo.scroll(null, document.getElementById('features').offsetTop - 20, 2200)")
    at(sc, b, 4)
    b.act.js("__demo.scroll(null, 0, 1600)")


def s_ask(sc, b):
    b.act.js("__demo.move(innerWidth*0.3, innerHeight*0.4, 700)")
    at(sc, b, 1)
    b.act.js("__demo.type('#q', 'Who should I ask about Kafka consumer lag?', 24)")
    b.act.js("__demo.click('#go')")
    b.act.js("__demo.waitFor('.answer')")
    at(sc, b, 3)
    b.act.js("__demo.point('.answer b', 700)")
    at(sc, b, 5)
    b.act.js("__demo.click('.answer .cite')")
    b.act.js("__demo.move(innerWidth*0.72, innerHeight*0.5, 900)")


def s_decisions(sc, b):
    b.act.js("__demo.click([...document.querySelectorAll('.chip')].find(c => c.textContent.includes('customer login')))")
    b.act.js("__demo.waitFor('.answer')")
    at(sc, b, 1)
    b.act.js("__demo.point('.answer li', 700)")
    at(sc, b, 2)
    b.act.js("__demo.point('.answer li:nth-child(2)', 700)")


def s_risks(sc, b):
    b.act.js("__demo.click('#nav-risks')")
    b.act.js("__demo.waitFor('.answer')")
    at(sc, b, 1)
    b.act.js("__demo.point('.answer li', 700)")
    at(sc, b, 2)
    b.act.js("__demo.point('.answer li:nth-child(2)', 700)")
    at(sc, b, 3)
    b.act.js("__demo.point('.answer li:nth-child(4)', 700)")


def s_sprint(sc, b):
    b.act.js("__demo.click('.nav button[data-view=\"write\"]')")
    b.act.js("__demo.click('#kind button[data-k=\"sprint\"]')")
    b.act.js("__demo.click('#g-project'); document.getElementById('g-project').value = 'project:checkout'")
    at(sc, b, 1)
    b.act.js("__demo.click('#g-go')")
    b.act.js("__demo.waitFor('.doc table')")
    at(sc, b, 2)
    b.act.js("__demo.scrollToEl('#v-write', [...document.querySelectorAll('.doc h2')][1], 30, 1400)")
    b.act.js("__demo.point('.doc table tr:nth-child(2) td:nth-child(2)', 700)")
    at(sc, b, 3)
    b.act.js("__demo.scrollToEl('#v-write', [...document.querySelectorAll('.doc h2')].pop(), 300, 2200)")


def s_current(sc, b):
    b.act.js("__demo.click('#addinfo')")
    at(sc, b, 1)
    b.act.js("__demo.point('#k-text', 800)")
    b.act.js("__demo.click('#k-save')")
    b.act.js("__demo.waitFor('#k-res.ok')")
    at(sc, b, 2)
    b.act.js("__demo.point('#k-res', 600)")
    at(sc, b, 3)
    b.act.js("__demo.click('#dclose')")
    b.act.js("document.getElementById('g-project').value = 'project:ledger'; __demo.click('#g-go')")
    b.act.js("__demo.waitFor('.doc table')")
    b.act.js("__demo.scrollToEl('#v-write', '.doc table', 90, 1200)")
    b.act.js("__demo.point([...document.querySelectorAll('.doc td')].find(td => td.textContent.includes('CockroachDB')), 800)")


def s_company(sc, b):
    b.act.js("__demo.scroll(null, document.getElementById('start').offsetTop - 60, 1500)")
    b.act.js("__demo.type('#name', 'Acme Robotics', 14)")
    b.act.js("__demo.click('#go')")
    b.act.js("__demo.waitFor('#done.show')")
    time.sleep(1.2)
    href = b.act.js("document.getElementById('open').href")
    b.act.js("__demo.point('#open', 600)")
    at(sc, b, 1)
    b.goto(href, settle=1.0)
    b.act.js("__demo.click('#addinfo')")
    b.act.js("__demo.type('#gh-repo', 'FalkorDB/falkordb-py', 18)")
    b.act.js("__demo.click('#gh-go')")
    b.act.js("__demo.waitFor('#gh-res.ok:not(:empty)', 60000)")
    b.act.js("(async () => { while (document.getElementById('gh-res').textContent.includes('Reading')) await new Promise(r => setTimeout(r, 100)); })()")
    b.act.js("__demo.point('#gh-res', 600)")
    time.sleep(1.2)
    b.act.js("__demo.click('#dclose')")
    b.act.js("__demo.waitFor('.chip')")
    at(sc, b, 2)
    b.act.js("__demo.click([...document.querySelectorAll('.chip')].find(c => /ask about/i.test(c.textContent)) || '.chip')")
    b.act.js("__demo.waitFor('.answer')")


def s_connect(sc, b):
    b.act.js("__demo.click('#connect')")
    at(sc, b, 1)
    b.act.js("__demo.scroll('#cbody', 520, 1600)")
    at(sc, b, 2)
    b.act.js("__demo.scroll('#cbody', 99999, 1600)")


SCENES = [
    Scene("Intro", ["This is Hivemind: the memory your company never had.",
                    "It's built on FalkorDB for the WeMakeDevs hackathon."], card="title"),
    Scene("The problem", [
        "Every company's knowledge is scattered across documents, tickets, chats and pull requests.",
        "The facts exist, but the connections between them don't.",
        "So new engineers ask the same people the same questions, and decisions get argued again and again.",
        "Hivemind turns all of it into one knowledge graph, where people, projects, systems, documents and decisions are connected.",
        "And it answers from those connections, with sources."], s_problem),
    Scene("Ask with sources", [
        "Here is Lumen Pay, a sample company with twelve people, six projects, and dozens of documents, tickets and messages.",
        "Let's ask: who should I ask about Kafka consumer lag?",
        "Hivemind searches the graph and shows each step as it works.",
        "The answer is Tomas Silva, ranked from real evidence: he wrote the runbook and the consumer library.",
        "Priya owns the Event Bus on paper, but Tomas is the one who actually knows Kafka.",
        "Every claim is cited. Clicking a source opens the original, and the graph zooms to the evidence."], s_ask),
    Scene("Decision history", [
        "Hivemind also traces decisions back to where they were made.",
        "Asking what changed about customer login shows the original choice of Auth0, now marked outdated.",
        "And the move to Keycloak as the current decision, with its reasons and the meeting, RFC and message that record it."], s_decisions),
    Scene("Knowledge risks", [
        "Under Knowledge risks, FalkorDB's graph algorithms find what no search box can.",
        "Betweenness centrality reveals the key connectors in the company.",
        "Single expert checks show where only one person holds the knowledge, like Noor on authentication.",
        "And blocked or stalled work surfaces automatically."], s_risks),
    Scene("Sprint plans and PRDs", [
        "Now let's turn knowledge into a plan.",
        "Generate a sprint plan for the checkout redesign, and Hivemind reads the project's tickets, blockers, decisions and experts.",
        "The blocker, PAY fifty two, is scheduled first, and owners come from assignments and expertise.",
        "Risks are flagged, every line links to its source, and the same works for PRDs."], s_sprint),
    Scene("Always current", [
        "Knowledge changes, and Hivemind keeps up.",
        "Maya posts that the ledger is moving from Postgres to CockroachDB.",
        "Hivemind links the message, detects a new decision, and marks the old Postgres decision as outdated.",
        "Generate the ledger's sprint plan, and the CockroachDB rollout is already in it."], s_current),
    Scene("Your company in seconds", [
        "Any company can start in seconds with its own private workspace.",
        "Import a GitHub repository, here FalkorDB's own Python client.",
        "Hivemind now knows the contributors, the experts and the open issues, and it's ready to answer and plan."], s_company),
    Scene("Connections", [
        "Connect Slack to capture conversations as they happen, and ask questions with slash hivemind.",
        "Jira, Linear and GitHub webhooks keep tickets current, and decisions can be announced in Slack, Teams, Discord or Google Chat.",
        "Hivemind runs in the cloud or fully offline with Docker, and it works inside Claude Desktop through MCP."], s_connect),
    Scene("Outro", ["Hivemind. One private FalkorDB graph per company, answers with receipts, and knowledge that stays current.",
                    "Thanks for watching."], card="end"),
]
SCENE_URL = {"The problem": "/", "Ask with sources": "/w/demo", "Your company in seconds": "/"}


# ---------------------------------------------------------------- build

def build():
    os.makedirs(OUT, exist_ok=True)
    print("Resetting the demo workspace...")
    urllib.request.urlopen(urllib.request.Request(BASE + "/api/w/demo/reset", data=b"{}", method="POST",
                                                  headers={"Content-Type": "application/json"}), timeout=60)
    print("Generating narration...")
    for i, sc in enumerate(SCENES):
        sc.narrate(i)

    b = Browser()
    try:
        for sc in SCENES:
            if sc.card:
                sc.length = sc.narration_len
                print(f"  card  {sc.title:26s} {sc.length:5.1f}s")
                continue
            if sc.title in SCENE_URL:
                b.goto(BASE + SCENE_URL[sc.title])
            b.act.js("(() => { const i = document.getElementById('inspect'); if (i) i.style.display = 'none'; })()")
            b.start()
            sc.action(sc, b)
            while time.time() - b.t0 < sc.narration_len:  # let the page keep living until the voice is done
                time.sleep(0.02)
            sc.frames, sc.length = b.stop()
            print(f"  scene {sc.title:26s} {sc.length:5.1f}s  {len(sc.frames)} frames")
    finally:
        b.close()

    # ---- audio
    print("Mixing audio...")
    total = sum(sc.length for sc in SCENES)
    pcm = bytearray(int(total * SR) * 2 + 4)
    offset = 0.0
    for sc in SCENES:
        for start, _, _, wav in sc.schedule:
            with wave.open(wav) as w:
                data = w.readframes(w.getnframes())
            p = int((offset + start) * SR) * 2
            pcm[p:p + len(data)] = data
        offset += sc.length
    audio = os.path.join(WORK, "narration.wav")
    with wave.open(audio, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(bytes(pcm))

    # ---- video
    print("Encoding video...")
    out = os.path.join(OUT, "hivemind-demo.mp4")
    enc = subprocess.Popen([FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                            "-shortest", out], stdin=subprocess.PIPE)
    cards = {"title": card("title"), "end": card("end")}
    caps = {}
    black = Image.new("RGB", (W, H), (0, 0, 0))
    chapters, t_total = [], 0.0
    last_frame = None
    for sc in SCENES:
        if not sc.card and not sc.frames and last_frame:
            sc.frames = [(0.0, last_frame)]  # never leave a scene empty
        if sc.frames:
            last_frame = sc.frames[-1][1]
        chapters.append((t_total, sc.title))
        n = int(round(sc.length * FPS))
        cache_key, cache_bytes = None, None
        fi = 0
        for k in range(n):
            t = k / FPS
            if sc.card:
                src_key, base_img = sc.card, cards[sc.card]
            else:
                while fi + 1 < len(sc.frames) and sc.frames[fi + 1][0] <= t:
                    fi += 1
                src_key = sc.frames[fi][1] if sc.frames else None
                base_img = None
            text = next((s for (a, e, s, _) in sc.schedule if a - 0.1 <= t <= e + 0.35), None)
            fade = 1.0
            if sc.card == "title":
                fade = min(1.0, t / 0.8)
            elif sc.card == "end":
                fade = min(1.0, (sc.length - t) / 1.2)
            key = (src_key, text, round(fade, 2))
            if key != cache_key:
                if base_img is None:
                    base_img = Image.open(src_key).convert("RGB")
                    if base_img.size != (W, H):
                        base_img = base_img.resize((W, H), Image.LANCZOS)
                img = base_img.copy()
                if text and not sc.card:
                    if text not in caps:
                        caps[text] = caption_layer(text)
                    img.paste(caps[text], (0, 0), caps[text])
                if fade < 1:
                    img = Image.blend(black, img, max(0.0, fade))
                cache_key, cache_bytes = key, img.tobytes()
            enc.stdin.write(cache_bytes)
        t_total += n / FPS
    enc.stdin.close()
    enc.wait()

    # ---- thumbnail + YouTube text
    make_thumbnail(os.path.join(OUT, "hivemind-thumbnail.jpg"))

    def ts(sec):
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"
    desc = f"""TITLE
Hivemind — The memory your company never had (FalkorDB knowledge graph agent)

DESCRIPTION
Hivemind turns a company's documents, tickets, chats and repositories into one FalkorDB knowledge graph. Ask who owns what, who actually knows what, and why decisions were made — every answer cites its sources — then generate PRDs and sprint plans from the same graph.

Built for the WeMakeDevs × FalkorDB Hackathon (Track 03 — Company Brain).

Code: https://github.com/Utkarsh2730/hivemind

Chapters
{chr(10).join(f"{ts(t)} {title}" for t, title in chapters)}

Built with FalkorDB, FastAPI, Claude (optional) and MCP. Runs in the cloud or fully offline with Docker.
The demo company, Lumen Pay, and its people are fictional. Photos: Unsplash.

#FalkorDB #KnowledgeGraph #AI #Hackathon #WeMakeDevs
"""
    open(os.path.join(OUT, "youtube.txt"), "w").write(desc)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"Done: {out}  ({t_total:.0f}s)")


if __name__ == "__main__":
    build()
