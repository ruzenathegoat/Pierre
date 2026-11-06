"""Visual status card for the Pierre mint radar embed (PNG bytes, Pillow only)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

_F = "/usr/share/fonts/truetype/dejavu/"
W, H = 1000, 420
BG, PANEL, PANEL2 = (14, 15, 19), (24, 26, 33), (31, 34, 43)
TXT, DIM, FAINT = (240, 238, 232), (146, 150, 163), (88, 92, 104)
GOLD = (214, 178, 106)
OK, BAD, WARN = (66, 214, 134), (240, 84, 96), (245, 178, 60)


def _font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(_F + name, size)


def _text(d, xy, s, font, fill, anchor="la", spacing=0):
    if spacing:
        x, y = xy
        for ch in s:
            d.text((x, y), ch, font=font, fill=fill, anchor=anchor)
            x += d.textlength(ch, font=font) + spacing
        return
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render_card(*, label: str, sym: str, pct: int | None, left: str, total: str,
                velocity: str, eta: str, paid: str, price: str, age: str,
                wallets: list[tuple[str, str]], accent: tuple[int, int, int]) -> bytes:
    """wallets: [(name, state)] with state in ELIGIBLE / NOT ELIGIBLE / UNVERIFIED."""
    S = 2  # supersample for smooth edges
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)

    def R(x0, y0, x1, y1, r, fill, outline=None, width=1):
        d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill=fill,
                            outline=outline, width=width * S)

    def T(x, y, s, size, fill, bold=False, mono=False, anchor="la", spacing=0):
        f = _font(size * S, bold, mono)
        if spacing:
            sp = spacing * S
            total_w = sum(d.textlength(c, font=f) + sp for c in s) - sp
            x0 = x * S - (total_w if anchor[0] == "r" else total_w / 2 if anchor[0] == "m" else 0)
            for c in s:
                d.text((x0, y * S), c, font=f, fill=fill, anchor="l" + anchor[1])
                x0 += d.textlength(c, font=f) + sp
        else:
            d.text((x * S, y * S), s, font=f, fill=fill, anchor=anchor)

    # card frame + accent rail
    R(0, 0, W - 1, H - 1, 26, PANEL, outline=_mix(PANEL, accent, 0.35), width=2)
    R(0, 28, 8, H - 28, 4, accent)

    # header row
    T(44, 38, sym.upper(), 26, GOLD, bold=True, spacing=5)
    d.line([(44 * S, 76 * S), ((W - 44) * S, 76 * S)], fill=_mix(PANEL, DIM, 0.25), width=S)

    # hero number
    T(44, 92, "FREE SHARES LEFT", 13, DIM, bold=True, spacing=3)
    T(44, 112, left, 84, TXT, bold=True)
    big_w = d.textlength(left, font=_font(84 * S, True)) / S
    T(44 + big_w + 14, 168, f"/ {total}", 30, DIM)

    # wallet chips (right of hero)
    cx, cy = 560, 98
    for i, (name, state) in enumerate(wallets[:3]):
        col = OK if state == "ELIGIBLE" else BAD if state == "NOT ELIGIBLE" else WARN
        txt = {"ELIGIBLE": "ELIGIBLE", "NOT ELIGIBLE": "NOT ELIGIBLE"}.get(state, "UNVERIFIED")
        y = cy + i * 44
        R(cx, y, W - 44, y + 36, 18, _mix(PANEL, col, 0.14), outline=_mix(PANEL, col, 0.55), width=1)
        d.ellipse([(cx + 14) * S, (y + 12) * S, (cx + 26) * S, (y + 24) * S], fill=col)
        T(cx + 38, y + 18, name, 14, TXT, bold=True, anchor="lm")
        T(W - 60, y + 18, txt, 13, col, bold=True, anchor="rm", spacing=1)

    # progress bar
    by0, by1, bx0, bx1 = 222, 252, 44, W - 44
    R(bx0, by0, bx1, by1, 15, PANEL2)
    if pct is not None:
        fw = max(0, min(100, pct)) / 100 * (bx1 - bx0)
        if fw > 0:
            bar = Image.new("RGB", (int(fw * S), (by1 - by0) * S))
            bd = ImageDraw.Draw(bar)
            for x in range(bar.width):
                bd.line([(x, 0), (x, bar.height)], fill=_mix(_mix(accent, BG, 0.45), accent, x / max(1, bar.width)))
            mask = Image.new("L", bar.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, bar.width - 1, bar.height - 1], 15 * S, fill=255)
            img.paste(bar, (bx0 * S, by0 * S), mask)
        T(bx0, by1 + 14, f"{pct}% CLAIMED", 14, TXT, bold=True, spacing=2)
        T(bx1, by1 + 14, "FREE POOL", 12, FAINT, bold=True, anchor="ra", spacing=3)

    # stat tiles
    tiles = [("VELOCITY", velocity), ("ETA DEPLETED", eta), ("PAID POOL", paid), ("PRICE", price), ("AGE", age)]
    ty0, ty1, gap = 316, 392, 12
    tw = (W - 88 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (k, v) in enumerate(tiles):
        x0 = 44 + i * (tw + gap)
        R(x0, ty0, x0 + tw, ty1, 14, PANEL2)
        T(x0 + 16, ty0 + 20, k, 11, DIM, bold=True, spacing=2)
        size = 22 if len(v) <= 9 else 18 if len(v) <= 12 else 15
        T(x0 + 16, ty0 + 50, v, size, TXT, bold=True, mono=True, anchor="lm")

    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "card_preview.png"
    open(out, "wb").write(render_card(
        label="Radar Snapshot", sym="SAGENT", pct=26, left="369", total="500",
        velocity="1/h", eta="-", paid="0/3,333", price="0.002 BNB", age="870m",
        wallets=[("Wallet II  Agentic .ai", "ELIGIBLE"), ("Wallet I  Viem EOA", "NOT ELIGIBLE")],
        accent=(66, 214, 134)))
    print("wrote", out)
