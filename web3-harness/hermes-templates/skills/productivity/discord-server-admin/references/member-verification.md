# Member verification: Carl-bot and friends

Reaction-role verification is the cheapest gate that still assigns a real role. Carl-bot is the usual pick on small/medium servers (free, no hosting, dashboard + commands).

## Carl-bot

Client id `235148962103951360`. Invite with the permissions from SKILL.md section 2:

```
https://discord.com/oauth2/authorize?client_id=235148962103951360&scope=bot+applications.commands&permissions=268954737
```

`268954737` = MANAGE_ROLES + MANAGE_CHANNELS + MANAGE_GUILD + MANAGE_MESSAGES + VIEW/SEND/EMBED/ATTACH/READ_HISTORY + ADD_REACTIONS + USE_EXTERNAL_EMOJIS + MENTION_EVERYONE. Includes Manage Server because Carl's `rr`/dashboard commands require it; drop MENTION_EVERYONE (`131072`) if the owner objects.

After it joins, confirm from REST: `/guilds/<gid>/roles` should list a `managed: true` role named after the bot, its position above `@everyone`; that role is what must sit above `Verified` in the hierarchy.

### Make the hierarchy unambiguous

Bot roles often land on the same raw `position` as each other (several managed roles at 1 beside `@everyone` at 0), and a tie has no defined winner — the verification bot can end up unable to assign `Verified`. Reorder in one call, array form only:

```python
PATCH /guilds/<gid>/roles
[{"id":"<owner role>","position":7},{"id":"<staff>","position":6},
 {"id":"<verification bot role>","position":4},{"id":"<hermes bot role>","position":3},
 {"id":"<verified role>","position":1}]
```

A dict body fails with `400 {"code":50035,"errors":{"_errors":[{"code":"LIST_TYPE_CONVERT"}]}}`. Positions must be unique, so reshuffle the whole ladder rather than nudging one role. Verify by printing every role sorted by `-position`, and state in the report that the verification bot now sits above `Verified`.

### Two ways to build the verify message

All-in-one (creates the embed, reacts, stores the pair):

```
/reactionrole aiov channel:#verify color:Green title:"Verification" description:"Click to verify and unlock the server." emoji:✅ role:@Verified
```

Arg order per docs: `<channel> <color> <title|description> <emoji> <role>`. Say "title|description" literally means the embed title, description as the second field.

Manual, when the message should already exist (e.g. Hermes posted it and holds the id):

```
@Carl-bot rr add #verify <message_id> ✅ @Verified
@Carl-bot rr verify <message_id>
```

`rr verify <msg_id>` is what makes it a gate: the reaction only ever **adds** the role (cannot be used to drop it) and Carl removes the reaction afterwards, so the message stays usable. `rr unique` / `rr binding` are for one-choice-ever pickers, not verification. `reactionrole normal <msg_id>` undoes it.

Alternative without commands: `carl.gg` → pick the server → Reaction Roles → new message in the verify channel.

### What Carl does not do

- No timed "verify within N minutes or be kicked". That needs Wick or Double Counter (or a custom bot). Do not promise it with Carl.
- Carl ignores commands posted by other bots, so the `rr` step is always the human's, in the Discord client.
- `rr temp` (temporary role) is a Premium command; verification does not need it.

## Build the overwrites inside the create call

`POST /guilds/<gid>/channels` accepts `permission_overwrites`, so there is no moment where a fresh `#verify` is invisible or unmanageable. Masks used for a gate:

- `VIEW_CHANNEL` 1024, `SEND_MESSAGES` 2048, `READ_MESSAGE_HISTORY` 65536, `ADD_REACTIONS` 64, `ATTACH_FILES` 32768, `EMBED_LINKS` 16384, `MANAGE_CHANNELS` 16, `MANAGE_ROLES` 268435456.

```python
POST /guilds/<gid>/channels
{"name":"verify","type":0,"parent_id":"<cat>","permission_overwrites":[
  {"id":"<everyone>","type":0,"allow":"66560","deny":"52224"},
  {"id":"<verified role>","type":0,"allow":"66560","deny":"0"},
  {"id":"<bot role>","type":0,"allow":"268485175","deny":"0"}]}
```

Always carry the bot's own role (or user id) as an allow entry in every overwrite set that denies `@everyone`: a channel overwrite beats role permission, so a bot that cannot VIEW a channel cannot `GET`/`PATCH`/`DELETE` it afterwards. That mistake is unrecoverable from REST and needs the owner to grant Administrator.

Posting the verify message is the Hermes bot's job (embed + `PUT /channels/<id>/messages/<mid>/reactions/%E2%9C%85/@me`), which returns **204 with an empty body** — empty is success, not failure. Confirm with `GET /channels/<id>/messages/<mid>` and check `reactions[].count`, then hand the human the message id and the channel link so the `@Carl-bot rr add` step is one paste.

## Permission shape after verify is wired

- `@everyone`: `VIEW_CHANNEL` denied on `degens` / content categories, allowed on `#verify` and `#rules` only.
- `Verified`: `VIEW_CHANNEL` allowed on the content categories (and `SEND_MESSAGES` if `@everyone` was where SEND lived), nothing else needed.
- Add the overwrites on the **category**, plus any channel that has its own overwrites (a channel-level overwrite beats the category). Re-list channels and check `len(permission_overwrites)` before declaring it locked.
- Existing members hold no `Verified` yet, so they lose access until they click once. That is expected, say it up front.
- Locking loop that survives staff needs: for every channel outside the verify category, drop the existing entries for `@everyone`, `Verified` and each staff/bot role from the overwrite list, then prepend `@everyone` `deny VIEW` and `Verified` `allow VIEW|READ`, and append one allow entry per staff/bot role. Preserve every other role's entry untouched so per-channel exceptions survive. Then `GET` each channel and print back the `@everyone` and `Verified` entries before declaring it locked — entries are returned in stored order, so scan the list for the id instead of trusting index 0.
- Do the lock **after** the third-party bot is wired and one test click works. Locking first means a failed `rr add` leaves the server dark with no self-service way back in.
- Staff roles need their own allow entry on the locked categories, otherwise the owner and moderators get gated too. Write staff/owner allows in the same PATCH as the deny, not afterwards.

## Native alternative: Membership Screening

Requires the **Community** feature, which a bot cannot enable (`features` is server-side only, `PATCH /guilds/<id>` cannot set it). Once Community is on: rules channel → Membership Screening → new members are `pending` and cannot send messages until they accept. No role, no extra bot, no channel locking, but it is a click-through, not verification of humanity.

PATCHable anyway when the bot has `MANAGE_GUILD`: `rules_channel_id`, `public_updates_channel_id`, `verification_level` (0 none … 4 highest, phone-verified).
