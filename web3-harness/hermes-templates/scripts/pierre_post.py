#!/usr/bin/env python3
"""Post a clean Pierre embed (native fields + link buttons, no images) from a JSON spec.

Usage:
  pierre_post.py --webhook-env positions_webhook_pnl.env --username "Pierre  |  PnL Ledger" --spec /path/spec.json

Spec JSON:
{
  "title": "Portfolio Ledger",                 # plain text
  "description": "**+$42.18** net  ·  2 open", # 1-2 short lines, markdown ok (bold the key number)
  "tone": "gold|ok|bad|warn|info|neutral",     # embed side color
  "footer": "Pierre Execution Desk  ·  30m",   # timestamp is added automatically
  "fields": [ {"name": "Realized", "value": "`+0.05 BNB`", "inline": true}, ... ],  # max 25, 3 inline per row
  "buttons": [ {"label": "BscScan", "url": "https://..."} ]                       # optional link buttons, max 25
}
Prints one line: "posted <http code>" or "FAILED <code>". Never prints the webhook URL.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pierre_ui as ui  # noqa: E402


def legacy_fields(card: dict) -> list[dict]:
    """Old card-style specs still work: flatten them into plain fields."""
    out = []
    hero = card.get("hero")
    if hero:
        out.append({"name": str(hero.get("label", "")).title(),
                    "value": f"**{hero.get('value', '')}**  {hero.get('sub', '')}".strip(), "inline": False})
    for p in card.get("panels") or []:
        out.append({"name": str(p.get("title", "")),
                    "value": "\n".join(f"{r[0]}  `{r[1]}`" for r in p.get("rows") or []) or "-", "inline": True})
    for k, v in card.get("tiles") or []:
        out.append({"name": str(k).title(), "value": f"`{v}`", "inline": True})
    for r in card.get("rows") or []:
        out.append({"name": f"{r.get('name', '')}  ·  {str(r.get('chip', '')).title()}",
                    "value": "\n".join(str(r.get(k)) for k in ("roi", "sub", "sub2") if r.get(k)) or "-",
                    "inline": False})
    return out[:25]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook-env", required=True, help="file name under ~/.hermes/secrets/")
    ap.add_argument("--username", default="Pierre")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the embed JSON, do not post")
    a = ap.parse_args()

    spec = json.load(open(os.path.expanduser(a.spec), encoding="utf-8"))
    fields = spec.get("fields") or (legacy_fields(spec["card"]) if spec.get("card") else [])
    embed = ui.make_embed(title=spec.get("title", ""), description=spec.get("description", ""),
                          tone=spec.get("tone", "gold"), footer=spec.get("footer", "Pierre Execution Desk"),
                          fields=fields or None, url=spec.get("url"))
    if spec.get("buttons"):
        embed["_buttons"] = spec["buttons"]
    if a.dry_run:
        print(json.dumps(embed, indent=2, ensure_ascii=False))
        return 0
    url = ui.read_webhook(f"~/.hermes/secrets/{a.webhook_env}", ("WEBHOOK_URL", "POSITIONS_WEBHOOK_URL"))
    ok, code, _mid = ui.post(url, a.username, [embed], wait=False)
    print(f"posted {code}" if ok else f"FAILED {code}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
