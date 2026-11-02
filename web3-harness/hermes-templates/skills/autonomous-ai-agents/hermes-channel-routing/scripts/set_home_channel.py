#!/usr/bin/env python3
"""Move a Hermes platform home channel via the same APIs /sethome uses.

Usage (run with the hermes venv so imports resolve):
    cd ~/.hermes/hermes-agent
    ./venv/bin/python <this> discord 899646197650817025 "#general"

Writes config.yaml (persist_home_channel) and the legacy env mirror
(<PLATFORM>_HOME_CHANNEL / _THREAD_ID) in one shot, then prints the
resolved value cron will use.
"""
import sys

sys.path.insert(0, "/home/ubuntu/.hermes/hermes-agent")

from gateway.config import HomeChannel, Platform, load_gateway_config, persist_home_channel
from hermes_cli.config import save_env_value


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    platform_name = sys.argv[1].lower()
    chat_id = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else "#home"
    thread_id = sys.argv[4] or None if len(sys.argv) > 4 else None

    platform = Platform(platform_name)
    cfg = load_gateway_config()
    existing = cfg.get_home_channel(platform)

    home = HomeChannel(
        platform=platform,
        chat_id=str(chat_id),
        name=name,
        thread_id=thread_id,
        user_id=existing.user_id if existing else None,
        scope_id=existing.scope_id if existing else None,
    )
    persist_home_channel(home)

    env_base = f"{platform_name.upper()}_HOME_CHANNEL"
    save_env_value(env_base, str(chat_id))
    save_env_value(f"{env_base}_THREAD_ID", thread_id or "")
    if name and name.isascii():
        save_env_value(f"{env_base}_NAME", name)

    from cron.scheduler_delivery import _get_home_target_chat_id, _get_home_target_thread_id

    print("resolved home:", _get_home_target_chat_id(platform_name),
          "thread:", _get_home_target_thread_id(platform_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
