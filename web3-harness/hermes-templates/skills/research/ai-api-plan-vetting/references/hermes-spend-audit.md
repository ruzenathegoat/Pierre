# Auditing real LLM spend from Hermes state

Use this to answer "how much am I actually spending per month?" with a number instead of a guess. Everything here is read-only.

## Where the data is

- `~/.hermes/state.db` — SQLite. Table `session_model_usage` has one row per (session, model, billing provider, base_url, billing mode, task) with `api_call_count`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `estimated_cost_usd`, `actual_cost_usd`, `cost_status`, `cost_source`, `first_seen`, `last_seen` (unix epoch floats).
- `sessions` table — `id`, `source` (e.g. `discord`, `cli`, `cron`), `display_name`, `message_count`, `started_at`.
- `~/.hermes/cron/usage_audit.jsonl` — one JSON line per cron LLM fire: `ts`, `job_id`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `model`, `duration_ms`. Shows which scheduled job drives cost.

Schema can differ per install: read `select sql from sqlite_master where name='session_model_usage'` first and adapt, do not assume columns.

## Recipes

By model, all time (highest cost first):
```sql
select model, sum(api_call_count), sum(input_tokens), sum(output_tokens),
       sum(cache_read_tokens), sum(estimated_cost_usd)
from session_model_usage group by model order by 6 desc;
```

Window (last N days) — pass unix epoch from python `time.time() - N*86400`:
```sql
select sum(api_call_count), sum(input_tokens), sum(output_tokens),
       sum(cache_read_tokens), sum(estimated_cost_usd)
from session_model_usage where last_seen > ?;
```

Per calendar day in the user's timezone (WIB = UTC+7) — group by the shifted date, not UTC:
```sql
select date(last_seen,'unixepoch','+7 hours') as day, sum(estimated_cost_usd),
       sum(api_call_count), sum(input_tokens), sum(output_tokens), sum(cache_read_tokens)
from session_model_usage where last_seen > ? group by day order by day;
```

By task type — separates chat cost from background overhead. Observed values: `''` (the actual conversation), `background_review`, `approval`, `title_generation`:
```sql
select task, sum(api_call_count), sum(input_tokens), sum(estimated_cost_usd)
from session_model_usage where last_seen > ? group by task order by 5 desc;
```

Top sessions by cost, joined to their source:
```sql
select u.session_id, s.source, s.display_name, s.message_count,
       sum(u.api_call_count), sum(u.estimated_cost_usd)
from session_model_usage u left join sessions s on s.id = u.session_id
where u.last_seen > ? group by u.session_id order by 6 desc limit 12;
```

Cron LLM fires (which job burns the tokens):
```bash
tail -n 3 ~/.hermes/cron/usage_audit.jsonl | cut -c1-500
```

## Reading the numbers

- `cache_read_tokens` usually dwarfs `input_tokens` in agent traffic (context is re-read every turn). Cache reads are priced roughly an order of magnitude below fresh input, so a big cache-read total with a small cost means healthy caching, not waste. Report both.
- A job configured as `no_agent` never calls a model, so its schedule frequency says nothing about spend. Check `usage_audit.jsonl` before blaming a frequent cron for cost.
- State coverage honestly: this is only what Hermes itself called. Direct API use, other tools, and other machines are not in it. Present it as "measured Hermes usage" and treat it as a lower bound on real spend.

## Scripting gotcha

A single f-string cannot use `,` as a thousands separator and also format a cost with `.4f` in the same expression when the value comes from a sqlite row tuple — unpack the row into variables first, or format in two steps. Saves a retry.
