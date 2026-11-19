"""Speculum reel builder: verified figures in, a 9:16 MP4 out (1080x1920, 30 fps, H.264) for Instagram Reels and TikTok.

    python tools/reel/reel.py SPEC.json [--out DIR] [--frames]      # --frames: draw key frames only, no video

A spec is a list of scenes. Each scene is drawn as an HTML page whose animation is a pure function of time, filmed
frame by frame with Playwright and encoded once per scene by ffmpeg; the scenes are joined without re-encoding.
Every number in a spec must come from a checked record (run the prepublish check first). Scene types:

  hook       kicker, lines: [{label, value, fmt, gold}]                big numbers that count up
  statement  kicker, text (use <b>..</b> for gold), sub                  words rise in
  bars       kicker, title, rows: [{label, sub, value, gold}], fmt, note   bars grow one after another
  columns    kicker, title, groups: [{label, a, b}], legend: [a, b], fmt, note   paired columns grow
  end        text, sub                                                   closing card with the address

Common scene fields: seconds (default 4.5), source (small print at the bottom).
Text is kept inside the area the apps leave clear (top 230 px, bottom 420 px, right 130 px are covered by buttons).
"""
from __future__ import annotations

import argparse
import html as H
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

W, HGT, FPS = 1080, 1920, 30
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart"]

SEAL = ('<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="none" stroke="#8a6f33" stroke-width="1.2"/>'
        '<circle cx="32" cy="32" r="24" fill="none" stroke="#8a6f33" stroke-width="0.8"/><g stroke="#8a6f33" stroke-width="1">'
        + "".join(f'<line x1="32" y1="3.5" x2="32" y2="7.5" transform="rotate({i*15} 32 32)"/>' for i in range(24))
        + '</g><ellipse cx="32" cy="32" rx="9" ry="14" fill="none" stroke="#c9a24a" stroke-width="1.4"/>'
        '<line x1="32" y1="18" x2="32" y2="46" stroke="#c9a24a" stroke-width="0.8"/>'
        '<line x1="23" y1="32" x2="41" y2="32" stroke="#c9a24a" stroke-width="0.8"/></svg>')

CSS = """
:root{--ground:#0b0a09;--line:#2b2721;--ink:#e4e9ef;--ink2:#aeb6c0;--ink3:#7e8792;--gold:#c9a24a;--golddim:#8a6f33;--bar:#8a7a5c;
--serif:"Liberation Serif",serif;--mono:"DejaVu Sans Mono",monospace}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1920px;background:var(--ground);color:var(--ink);overflow:hidden;-webkit-font-smoothing:antialiased}
.s{position:absolute;inset:0;background:radial-gradient(ellipse 1000px 1100px at 50% 42%,#17140f 0%,#0b0a09 70%)}
.frame{position:absolute;inset:30px;border:1px solid var(--line)}
.grain{position:absolute;inset:0;opacity:.07;mix-blend-mode:screen;pointer-events:none;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")}
.prog{position:absolute;left:30px;right:30px;top:30px;height:4px;background:#1c1915}
.prog i{position:absolute;left:0;top:0;bottom:0;background:var(--gold)}
.safe{position:absolute;left:84px;right:130px;top:230px;bottom:420px}
.top{display:flex;align-items:center;gap:16px}
.top svg{width:52px;height:52px}
.wm{font:600 32px/1 var(--serif);letter-spacing:.24em;text-transform:uppercase}
.kick{margin-top:64px;font:500 24px/1.35 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);padding-bottom:20px;border-bottom:1px solid var(--line)}
.lab{font:400 32px/1.25 var(--serif);color:var(--ink2);margin-top:56px}
.num{font:400 150px/1 var(--mono);letter-spacing:-.04em;color:var(--ink);margin-top:14px}
.num.gold{color:var(--gold)}
.stmt{font:400 70px/1.16 var(--serif);color:var(--ink);margin-top:70px}
.stmt b{font-weight:400;color:var(--gold)}
.w{display:inline-block;will-change:transform,opacity}
.sub{font:400 32px/1.4 var(--serif);color:var(--ink2);margin-top:40px}
.title{font:400 54px/1.15 var(--serif);margin-top:48px}
.title b{font-weight:400;color:var(--gold)}
.rows{margin-top:44px}
.row{margin:0 0 30px}
.row .l{display:flex;justify-content:space-between;align-items:baseline;gap:16px;font:400 32px/1.2 var(--serif)}
.row .l .v{font:400 32px/1 var(--mono)}
.row .sm{font:400 20px/1.3 var(--mono);color:var(--ink3);margin-top:6px}
.row .t{height:34px;background:#221f1a;margin-top:10px;position:relative}
.row .t i{position:absolute;left:0;top:0;bottom:0;background:var(--bar)}
.row.gold .t i,.row.gold .v{background:var(--gold)} .row.gold .v{background:none;color:var(--gold)}
.note{font:400 36px/1.3 var(--serif);color:var(--ink);margin-top:26px}
.note b{font-weight:400;color:var(--gold)}
.chart{display:flex;align-items:flex-end;gap:22px;height:560px;margin-top:40px;border-bottom:1px solid #3a352d}
.g{flex:1;display:flex;align-items:flex-end;gap:6px;height:100%}
.c{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.c i{display:block;width:100%;background:var(--bar)} .c.b i{background:var(--gold)}
.c em{font:400 19px/1.2 var(--mono);font-style:normal;margin-bottom:8px;white-space:nowrap} .c.b em{color:var(--gold)}
.yrs{display:flex;gap:22px;margin-top:12px} .yrs div{flex:1;text-align:center;font:400 22px/1.2 var(--mono);color:var(--ink2)}
.legend{display:flex;gap:30px;margin-top:22px;font:400 22px/1 var(--mono);color:var(--ink2)}
.legend span::before{content:"";display:inline-block;width:18px;height:18px;margin-right:10px;vertical-align:-3px;background:var(--bar)}
.legend span.b::before{background:var(--gold)}
.end{font:400 76px/1.12 var(--serif);margin-top:110px}
.end b{font-weight:400;color:var(--gold)}
.url{font:500 64px/1 var(--mono);color:var(--gold);letter-spacing:.04em;margin-top:90px}
.src{position:absolute;left:84px;right:130px;bottom:300px;font:400 19px/1.5 var(--mono);color:var(--ink3)}
"""

JS = r"""
const ease=x=>1-Math.pow(1-Math.min(Math.max(x,0),1),3);
const seg=(t,a,d)=>ease((t-a)/d);
function money(v){if(v===0)return "$0";if(v>=1e6)return "$"+(v/1e6).toFixed(1)+"M";if(v>=1e3)return "$"+Math.round(v/1e3)+"K";return "$"+Math.round(v)}
function fmt(v,f){if(f==="money")return money(v);if(f==="pct")return Math.round(v)+"%";if(f==="x")return Math.round(v)+"×";return Math.round(v).toLocaleString("en-US")}
window.render=function(t){
  const D=window.DUR, fade=Math.min(seg(t,0,.35),1-seg(t,D-.3,.3));
  document.querySelector('.safe').style.opacity=fade; document.querySelector('.src').style.opacity=fade*0.95;
  document.querySelector('.prog i').style.width=((window.T0+t)/window.TOTAL*100)+"%";
  document.querySelectorAll('[data-in]').forEach(e=>{const a=+e.dataset.in,k=seg(t,a,.55);e.style.opacity=k;e.style.transform=`translateY(${(1-k)*26}px)`});
  document.querySelectorAll('[data-count]').forEach(e=>{const a=+e.dataset.at,k=seg(t,a,1.2);e.textContent=fmt(+e.dataset.count*k,e.dataset.fmt)});
  document.querySelectorAll('[data-grow]').forEach(e=>{const a=+e.dataset.at,k=seg(t,a,1.0);e.style[e.dataset.axis||'width']=(+e.dataset.grow*k)+"%"});
};
"""


def esc(s):
    return H.escape(str(s), quote=False)


def rich(s):
    """Escape, then allow <b> for gold."""
    return esc(s).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def words(s, start, step):
    """Split rich text into words that rise in one after another (tags kept intact)."""
    out, i, gold = [], 0, False
    for tok in re.split(r"(\s+)", rich(s)):
        if not tok.strip():
            out.append(tok); continue
        o = tok
        o = o.replace("<b>", "").replace("</b>", "")
        cls = "w"
        if "<b>" in tok:
            gold = True
        piece = f'<span class="{cls}" data-in="{start + i*step:.2f}">{o}</span>'
        out.append(f"<b>{piece}</b>" if gold else piece)
        if "</b>" in tok:
            gold = False
        i += 1
    return "".join(out)


def money(v):
    return "$0" if v == 0 else "$%.1fM" % (v / 1e6) if v >= 1e6 else "$%dK" % round(v / 1e3) if v >= 1e3 else "$%d" % round(v)


def fmtv(v, f):
    return money(v) if f == "money" else f"{round(v)}%" if f == "pct" else f"{round(v):,}"


def scene_html(sc: dict) -> str:
    k = sc.get("type")
    kick = f'<div class="kick" data-in="0.1">{esc(sc.get("kicker", ""))}</div>' if sc.get("kicker") else ""
    body = ""
    if k == "hook":
        t = 0.45
        for ln in sc["lines"]:
            body += f'<div class="lab" data-in="{t:.2f}">{rich(ln["label"])}</div>'
            body += (f'<div class="num{" gold" if ln.get("gold") else ""}" data-in="{t+0.15:.2f}" data-count="{ln["value"]}" '
                     f'data-fmt="{ln.get("fmt", "money")}" data-at="{t+0.2:.2f}">{fmtv(ln["value"], ln.get("fmt", "money"))}</div>')
            t += 1.5
    elif k == "statement":
        body = f'<div class="stmt">{words(sc["text"], 0.4, 0.07)}</div>'
        if sc.get("sub"):
            body += f'<div class="sub" data-in="{0.6 + 0.07*len(sc["text"].split()):.2f}">{rich(sc["sub"])}</div>'
    elif k == "bars":
        mx = sc.get("max") or max(r["value"] for r in sc["rows"])
        body = f'<div class="title" data-in="0.3">{rich(sc["title"])}</div><div class="rows">'
        for i, r in enumerate(sc["rows"]):
            a = 0.8 + i * 0.45
            body += (f'<div class="row{" gold" if r.get("gold") else ""}" data-in="{a:.2f}"><div class="l"><span>{rich(r["label"])}</span>'
                     f'<span class="v" data-count="{r["value"]}" data-fmt="{sc.get("fmt", "money")}" data-at="{a+0.1:.2f}">{fmtv(r["value"], sc.get("fmt", "money"))}</span></div>'
                     + (f'<div class="sm">{rich(r["sub"])}</div>' if r.get("sub") else "")
                     + f'<div class="t"><i data-grow="{max(r["value"]/mx*100, 0.7):.3f}" data-at="{a+0.1:.2f}"></i></div></div>')
        body += "</div>"
        if sc.get("note"):
            body += f'<div class="note" data-in="{0.9 + len(sc["rows"])*0.45 + 0.6:.2f}">{rich(sc["note"])}</div>'
    elif k == "columns":
        mx = max(max(g["a"], g["b"]) for g in sc["groups"])
        body = f'<div class="title" data-in="0.3">{rich(sc["title"])}</div><div class="chart">'
        for i, g in enumerate(sc["groups"]):
            a = 0.8 + i * 0.4
            body += '<div class="g">'
            for key, cls in (("a", ""), ("b", " b")):
                v = g[key]
                body += (f'<div class="c{cls}"><em data-in="{a+0.6:.2f}">{fmtv(v, sc.get("fmt", "money"))}</em>'
                         f'<i data-axis="height" data-grow="{max(v/mx*100, 0.8):.3f}" data-at="{a:.2f}"></i></div>')
            body += "</div>"
        body += "</div><div class=\"yrs\">" + "".join(f'<div data-in="0.5">{esc(g["label"])}</div>' for g in sc["groups"]) + "</div>"
        lg = sc.get("legend") or ["", ""]
        body += f'<div class="legend" data-in="0.6"><span>{esc(lg[0])}</span><span class="b">{esc(lg[1])}</span></div>'
        if sc.get("note"):
            body += f'<div class="note" data-in="{0.9 + len(sc["groups"])*0.4 + 0.8:.2f}">{rich(sc["note"])}</div>'
    elif k == "end":
        body = f'<div class="end">{words(sc["text"], 0.3, 0.06)}</div>'
        if sc.get("sub"):
            body += f'<div class="sub" data-in="1.2">{rich(sc["sub"])}</div>'
        body += '<div class="url" data-in="1.6">speculum.vote</div>'
    else:
        raise ValueError(f"unknown scene type {k!r}")
    head = f'<div class="top" data-in="0">{SEAL}<div class="wm">Speculum</div></div>'
    src = f'<div class="src">{esc(sc.get("source", ""))}</div>'
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="s">'
            f'<div class="grain"></div><div class="frame"></div><div class="prog"><i></i></div><div class="safe">{head}{kick}{body}</div>{src}</div>'
            f'<script>{JS}</script></body></html>')


def build(spec_path: Path, out_dir: Path, frames_only: bool = False) -> Path:
    from playwright.sync_api import sync_playwright
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    scenes = spec["scenes"]
    durs = [float(s.get("seconds", 4.5)) for s in scenes]
    total = sum(durs)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = spec.get("name") or spec_path.stem
    tmp = Path(tempfile.mkdtemp(prefix="reel-"))
    parts = []
    with sync_playwright() as pw:
        exe = "/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None
        b = pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else pw.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": HGT}, device_scale_factor=1)
        t0 = 0.0
        for i, (sc, d) in enumerate(zip(scenes, durs)):
            pg.set_content(scene_html(sc), wait_until="load")
            pg.evaluate(f"window.DUR={d};window.T0={t0};window.TOTAL={total}")
            if frames_only:
                for frac in (0.5, 0.88):     # the busiest moments: mid-build and fully drawn
                    pg.evaluate(f"render({d*frac})")
                    pg.screenshot(path=str(out_dir / f"{name}-frame{i+1}-{int(frac*100)}.jpg"), type="jpeg", quality=92)
                    # check that nothing falls outside the safe area
                over = pg.evaluate("(()=>{const s=document.querySelector('.safe').getBoundingClientRect();"
                                   "return [...document.querySelectorAll('.safe *')].filter(e=>{const r=e.getBoundingClientRect();"
                                   "return r.width&&(r.bottom>s.bottom+2||r.right>s.right+2)}).map(e=>e.className||e.tagName).slice(0,5)})()")
                if over:
                    print(f"scene {i+1}: outside the safe area: {over}")
                t0 += d
                continue
            n = round(d * FPS)
            part = tmp / f"s{i:02d}.mp4"
            part_tmp = tmp / f"s{i:02d}.part.mp4"
            ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                                   *ENC, str(part_tmp)], stdin=subprocess.PIPE)
            for f in range(n):
                pg.evaluate(f"render({f / FPS})")
                ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
            ff.stdin.close()
            if ff.wait() != 0:
                raise RuntimeError(f"ffmpeg failed on scene {i+1}")
            part_tmp.rename(part)
            parts.append(part)
            t0 += d
            print(f"scene {i+1}/{len(scenes)} done ({n} frames)")
        b.close()
    if frames_only:
        return out_dir
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    final = out_dir / f"{name}.mp4"
    final_tmp = out_dir / f"{name}.part.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(final_tmp)], check=True)
    final_tmp.rename(final)
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--frames", action="store_true", help="draw key frames only")
    a = ap.parse_args()
    print(build(a.spec, a.out, a.frames))
