"""Shared Pierre visual kit: PNG status cards + webhook poster (Pillow + curl only).

Two card types:
  render_dashboard(spec)  hero number, status chips, label/value panels, stat tiles
  render_rows(spec)       a ranked list of rows (positions), each with ROI + stance chip

Specs are plain dicts so cron/LLM jobs can hand them over as JSON (see pierre_post.py).
"""
from __future__ import annotations

import datetime
import io
import json
import os
import subprocess
import tempfile
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

_FD = "/usr/share/fonts/truetype/dejavu/"
W, S = 1000, 2
BG, PANEL, PANEL2 = (14, 15, 19), (24, 26, 33), (31, 34, 43)
TXT, DIM, FAINT, GOLD = (240, 238, 232), (146, 150, 163), (88, 92, 104), (214, 178, 106)
TONES = {
    "ok": (66, 214, 134), "bad": (240, 84, 96), "warn": (245, 178, 60),
    "gold": GOLD, "info": (96, 165, 250), "neutral": (130, 136, 150),
}


def tone_rgb(t) -> tuple[int, int, int]:
    return TONES.get(str(t or "gold"), GOLD)


def color_int(t) -> int:
    r, g, b = tone_rgb(t)
    return (r << 16) | (g << 8) | b


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


@lru_cache(maxsize=64)
def _font(px: int, bold: bool, mono: bool):
    n = ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(_FD + n, px)


class Canvas:
    def __init__(self, h: int):
        self.h = h
        self.img = Image.new("RGB", (W * S, h * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def rrect(self, x0, y0, x1, y1, r, fill, outline=None, width=1):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill=fill,
                                 outline=outline, width=width * S)

    def tw(self, s, size, bold=False, mono=False, spacing=0) -> float:
        f = _font(size * S, bold, mono)
        return (sum(self.d.textlength(c, font=f) + spacing * S for c in s) - spacing * S) / S if spacing \
            else self.d.textlength(s, font=f) / S

    def fit(self, s, maxw, size, bold=False, mono=False, lo=10) -> int:
        while size > lo and self.tw(s, size, bold, mono) > maxw:
            size -= 1
        return size

    def text(self, x, y, s, size, fill, bold=False, mono=False, anchor="la", spacing=0):
        f = _font(size * S, bold, mono)
        if spacing:
            w = self.tw(s, size, bold, mono, spacing)
            x0 = x - (w if anchor[0] == "r" else w / 2 if anchor[0] == "m" else 0)
            for c in s:
                self.d.text((x0 * S, y * S), c, font=f, fill=fill, anchor="l" + anchor[1])
                x0 += self.d.textlength(c, font=f) / S + spacing
        else:
            self.d.text((x * S, y * S), s, font=f, fill=fill, anchor=anchor)

    def chip_w(self, s, size=13):
        return self.tw(s, size, True, spacing=1) + 50

    def chip(self, x, y, s, tone, h=34, size=13, align="l"):
        col = tone_rgb(tone)
        w = self.chip_w(s, size)
        x0 = x - w if align == "r" else x
        self.rrect(x0, y, x0 + w, y + h, h // 2, mix(PANEL, col, 0.14), outline=mix(PANEL, col, 0.55))
        self.d.ellipse([(x0 + 14) * S, (y + h / 2 - 5) * S, (x0 + 24) * S, (y + h / 2 + 5) * S], fill=col)
        self.text(x0 + 32, y + h / 2, s, size, col, bold=True, anchor="lm", spacing=1)
        return w

    def header(self, title, accent):
        self.rrect(0, 0, W - 1, self.h - 1, 26, PANEL, outline=mix(PANEL, accent, 0.35), width=2)
        self.rrect(0, 28, 8, self.h - 28, 4, accent)
        t = title.upper()
        self.text(44, 38, t, self.fit(t, W - 88, 26, True), GOLD, bold=True, spacing=5)
        self.d.line([(44 * S, 76 * S), ((W - 44) * S, 76 * S)], fill=mix(PANEL, DIM, 0.25), width=S)

    def tiles(self, y, tiles, h=76):
        gap = 12
        tw = (W - 88 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (k, v) in enumerate(tiles):
            x0 = 44 + i * (tw + gap)
            self.rrect(x0, y, x0 + tw, y + h, 14, PANEL2)
            self.text(x0 + 16, y + 20, str(k).upper(), 11, DIM, bold=True, spacing=2)
            v = str(v)
            self.text(x0 + 16, y + 50, v, self.fit(v, tw - 28, 22, True, True), TXT, bold=True, mono=True, anchor="lm")

    def png(self) -> bytes:
        out = self.img.resize((W, self.h), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def render_dashboard(spec: dict) -> bytes:
    accent = tone_rgb(spec.get("tone"))
    hero, chips = spec.get("hero"), spec.get("chips") or []
    panels, tiles = spec.get("panels") or [], spec.get("tiles") or []
    hero_h = 170 if hero else 0
    prow = max((len(p.get("rows") or []) for p in panels), default=0)
    panel_h = prow * 34 + 64 if panels else 0
    H = 76 + hero_h + (panel_h + 18 if panels else 0) + (76 + 18 if tiles else 0) + 24
    c = Canvas(H)
    c.header(spec.get("title", ""), accent)

    y = 76
    if hero:
        maxw = 470 if chips else W - 88
        c.text(44, y + 18, str(hero.get("label", "")).upper(), 13, DIM, bold=True, spacing=3)
        val = str(hero.get("value", ""))
        vcol = tone_rgb(hero.get("tone")) if hero.get("tone") else TXT
        c.text(44, y + 40, val, c.fit(val, maxw, 76, True, lo=24), vcol, bold=True)
        if hero.get("sub"):
            sub = str(hero["sub"])
            c.text(46, y + 134, sub, c.fit(sub, maxw, 18), DIM)
        for i, ch in enumerate(chips[:3]):
            txt, tn = (ch + ["neutral"])[:2] if isinstance(ch, list) else (str(ch), "neutral")
            c.chip(W - 44, y + 22 + i * 44, str(txt).upper(), tn, align="r")
        y += hero_h

    if panels:
        n, gap = len(panels), 14
        pw = (W - 88 - gap * (n - 1)) / n
        for i, p in enumerate(panels):
            x0 = 44 + i * (pw + gap)
            c.rrect(x0, y, x0 + pw, y + panel_h, 16, PANEL2)
            c.text(x0 + 20, y + 24, str(p.get("title", "")).upper(), 12, GOLD, bold=True, spacing=2)
            for j, row in enumerate(p.get("rows") or []):
                k, v = str(row[0]), str(row[1])
                tn = tone_rgb(row[2]) if len(row) > 2 else TXT
                ry = y + 62 + j * 34
                c.text(x0 + 20, ry, k, 14, DIM, anchor="lm")
                room = pw - 40 - c.tw(k, 14) - 14
                c.text(x0 + pw - 20, ry, v, c.fit(v, room, 15, True, True), tn, bold=True, mono=True, anchor="rm")
        y += panel_h + 18

    if tiles:
        c.tiles(y, tiles)
    return c.png()


def render_rows(spec: dict) -> bytes:
    accent = tone_rgb(spec.get("tone"))
    rows, tiles = spec.get("rows") or [], spec.get("tiles") or []
    rh, gap = 92, 10
    body = len(rows) * (rh + gap) if rows else 110
    H = 76 + 18 + body + (76 + 8 if tiles else 0) + 14
    c = Canvas(H)
    c.header(spec.get("title", ""), accent)
    y = 76 + 18
    if not rows:
        c.text(W / 2, y + 40, spec.get("empty", "Nothing to show"), 20, DIM, anchor="ma")
        y += 110
    for r in rows:
        c.rrect(44, y, W - 44, y + rh, 16, PANEL2)
        col = tone_rgb(r.get("chip_tone"))
        c.rrect(44, y + 14, 50, y + rh - 14, 3, col)
        chip = str(r.get("chip", "")).upper()
        cw = c.chip_w(chip) if chip else 0
        if chip:
            c.chip(W - 66, y + rh / 2 - 17, chip, r.get("chip_tone"), align="r")
        roi = str(r.get("roi", ""))
        rx = W - 66 - cw - 26
        if roi:
            c.text(rx, y + rh / 2, roi, 28, tone_rgb(r.get("roi_tone")) if r.get("roi_tone") else TXT,
                   bold=True, mono=True, anchor="rm")
        left_w = rx - 68 - (c.tw(roi, 28, True, True) + 20 if roi else 0)
        name = str(r.get("name", ""))
        c.text(68, y + 26, name, c.fit(name, left_w, 21, True), TXT, bold=True, anchor="lm")
        for k, key in enumerate(("sub", "sub2")):
            if r.get(key):
                s = str(r[key])
                c.text(68, y + 52 + k * 22, s, c.fit(s, left_w, 13), DIM if k == 0 else FAINT, anchor="lm")
        y += rh + gap
    if tiles:
        c.tiles(y + 2, tiles)
    return c.png()


def wib_stamp() -> str:
    wib = datetime.timezone(datetime.timedelta(hours=7))
    return datetime.datetime.now(wib).strftime("%Y-%m-%d %H:%M WIB")


def make_embed(*, title: str, description: str = "", tone="gold", card: bytes | None = None,
               footer: str = "Pierre Execution Desk", url: str | None = None,
               fields: list[dict] | None = None, color: int | None = None) -> dict:
    e = {
        "author": {"name": "R\u016e\u017dE HOUSE"},
        "title": title,
        "color": color if color is not None else color_int(tone),
        "footer": {"text": footer},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if description:
        e["description"] = description
    if url:
        e["url"] = url
    if fields:
        e["fields"] = fields
    if card:
        e["_card"] = card
    return e


def link_rows(buttons) -> list[dict]:
    """Link buttons (non-interactive, allowed on plain webhooks) packed 5 per action row."""
    rows, cur = [], []
    for b in (buttons or [])[:25]:
        label, url = (b["label"], b["url"]) if isinstance(b, dict) else (b[0], b[1])
        if not str(url).startswith("http"):
            continue
        cur.append({"type": 2, "style": 5, "label": str(label)[:80], "url": str(url)})
        if len(cur) == 5:
            rows.append({"type": 1, "components": cur})
            cur = []
    if cur:
        rows.append({"type": 1, "components": cur})
    return rows


def post(url: str, username: str, embeds: list[dict], wait: bool = True, buttons=None,
         files: dict | None = None) -> tuple[bool, str, str | None]:
    """Post embeds (+ optional link buttons / attachments) through a plain webhook.

    Embeds may carry private keys: "_buttons" (list of (label, url)) and "_card"
    (PNG bytes attached as the embed image). Uses curl because Discord rejects
    urllib's default fingerprint (Cloudflare 1010). Returns (ok, http_code, message_id).
    """
    if not url:
        return False, "no-webhook", None
    atts: list[tuple[str, bytes]] = list((files or {}).items())
    out, btns = [], list(buttons or [])
    for e in embeds:
        e = dict(e)
        btns += e.pop("_buttons", None) or []
        card = e.pop("_card", None)
        if card:
            name = f"card{len(atts)}.png"
            atts.append((name, card))
            e["image"] = {"url": f"attachment://{name}"}
        out.append(e)

    def attempt(with_buttons: bool):
        body = {"username": username, "embeds": out}
        rows = link_rows(btns) if with_buttons else []
        if rows:
            body["components"] = rows
        q = [x for x in (("wait=true" if wait else ""), ("with_components=true" if rows else "")) if x]
        cmd = ["curl", "-s", "-m", "40", "-w", "\n%{http_code}", "-A", "Mozilla/5.0", "-X", "POST",
               url + ("?" + "&".join(q) if q else "")]
        with tempfile.TemporaryDirectory() as td:
            if atts:
                cmd += ["--form-string", f"payload_json={json.dumps(body)}"]
                for i, (n, b) in enumerate(atts):
                    pth = os.path.join(td, n)
                    with open(pth, "wb") as f:
                        f.write(b)
                    cmd += ["-F", f"files[{i}]=@{pth};type=image/png"]
            else:
                cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body)]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except Exception:
                return "curl-error", ""
        text, _, code = (r.stdout or "").rpartition("\n")
        return code.strip(), text

    code, text = attempt(True)
    if code == "400" and btns:          # never lose an alert because of the buttons
        code, text = attempt(False)
    mid = None
    if code == "200":
        try:
            mid = json.loads(text).get("id")
        except Exception:
            pass
    return code in ("200", "204"), code, mid


def short(h, n=6, m=4) -> str:
    h = str(h or "")
    return f"{h[:n]}\u2026{h[-m:]}" if len(h) > n + m + 3 else h


SCAN = {"BSC": "https://bscscan.com", "BNB": "https://bscscan.com", "ETH": "https://etherscan.io",
        "ETHEREUM": "https://etherscan.io", "BASE": "https://basescan.org",
        "POLYGON": "https://polygonscan.com", "ARBITRUM": "https://arbiscan.io"}


def read_webhook(path: str, keys=("WEBHOOK_URL",)) -> str:
    import re
    try:
        txt = open(os.path.expanduser(path), encoding="utf-8").read()
    except OSError:
        return ""
    for k in keys:
        m = re.search(rf"^{k}=(.*)$", txt, re.M)
        if m:
            v = m.group(1).strip().strip("'\"")
            if v.startswith("https://discord.com/api/webhooks/"):
                return v
    return ""
