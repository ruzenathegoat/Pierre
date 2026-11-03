#!/usr/bin/env python3
"""switch_model — atur model utama Hermes; profil lain otomatis jadi fallback.

Pemakaian:
  switch_model openrouter          # OpenRouter utama, NVIDIA cadangan
  switch_model nvidia              # NVIDIA utama, OpenRouter cadangan
  switch_model openrouter nvidia   # urutan eksplisit: utama lalu fallback
  switch_model --list              # tampilkan profil yang tersedia

Untuk model baru nanti: tambahkan satu entri di PROFILES (dan API key-nya di ~/.hermes/.env).
"""
import os
import sys

import yaml

CONFIG = os.path.expanduser("~/.hermes/config.yaml")

PROFILES = {
    "openrouter": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4.1-flash",
        "base_url": "https://openrouter.ai/api/v1",
        "api_mode": "chat_completions",
    },
    "nvidia": {
        "provider": "nvidia",
        "model": "deepseek-ai/deepseek-v4.1-flash",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_mode": "chat_completions",
    },
}

# Batas tunggu per provider (detik) supaya provider lambat tidak menggantung lama.
PROVIDER_TIMEOUTS = {
    "nvidia": {"request_timeout_seconds": 60, "stale_timeout_seconds": 60},
}


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--list":
        for name, p in PROFILES.items():
            print(f"{name:12s} {p['model']}  (via {p['provider']})")
        return 0

    unknown = [a for a in args if a not in PROFILES]
    if unknown:
        print(f"Profil tidak dikenal: {', '.join(unknown)}. Pilihan: {', '.join(PROFILES)}")
        return 1

    order = list(dict.fromkeys(args))
    order += [name for name in PROFILES if name not in order]
    primary, fallbacks = order[0], order[1:]

    with open(CONFIG) as f:
        cfg = yaml.safe_load(f) or {}
    with open(CONFIG + ".bak", "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    p = PROFILES[primary]
    cfg["model"] = {
        "provider": p["provider"],
        "default": p["model"],
        "base_url": p["base_url"],
        "api_mode": p["api_mode"],
    }
    cfg["fallback_providers"] = [dict(PROFILES[name]) for name in fallbacks]
    cfg.pop("fallback_model", None)

    providers = cfg.setdefault("providers", {})
    for name, timeouts in PROVIDER_TIMEOUTS.items():
        providers.setdefault(name, {}).update(timeouts)

    with open(CONFIG, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    print(f"Utama   : {p['model']} (via {p['provider']})")
    for i, name in enumerate(fallbacks, 1):
        fb = PROFILES[name]
        print(f"Cadangan{i}: {fb['model']} (via {fb['provider']})")
    print("Jalankan: systemctl --user restart hermes-gateway")
    return 0


if __name__ == "__main__":
    sys.exit(main())
