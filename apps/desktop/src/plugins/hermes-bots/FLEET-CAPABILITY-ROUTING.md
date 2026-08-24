# Fleet capability routing — what A2A teaches Bot Mode, and what it doesn't

**Status:** capability tags SHIPPED (`tools/bot_mode_probe.py`, 21 tests green,
verified on the live 12-profile fleet). Sender identity + work-item id are
specified but NOT built.

**Audience:** the `hermes-bots` workspace. This is the spec layer, not a tutorial.

---

## 0. The finding that frames everything

`hermes-bots` does **not** use the A2A protocol. Not one call.

The only `A2A` symbols in `plugin.js` are two regexes:

```js
const A2A_RE = /^Message from (?:agent '([^']+)'|🤖\s*([^\s(@]+))/i
const A2A_PREFIX_RE = /^Message from (?:agent '[^']+'|🤖[^:]+):\s*/i
```

`A2A` there means *agent-to-agent as a concept*, and both match **plain text
prefixes** inside a chat message. Verified with a grep for any import of the
A2A plugin from any bot-mode file: zero hits (only the plugin describing itself
and the loader naming it as an example).

Bot Mode built its own coordination layer end to end. That was the right call —
see §2, where the design is *better* than A2A at the thing A2A cannot do at all.

## 1. The three real transports

| Layer | Transport | Where |
|---|---|---|
| Group chats | Desktop JSON-RPC over WebSocket: `prompt.submit` + `session.resume` polling | `plugin.js` `runGroupChatRounds` / `requestForBot` |
| Local bot↔bot DM | subprocess `hermes -p <name> chat --in ~ -c "Bot Chat" --create-if-missing -Q --query-file <tmp>`, backgrounded with `notify_on_complete` | `tools/bot_mode_dm.py` |
| Cross-machine DM | `POST /api/sessions/{id}/chat` on the peer's `api_server` | `hermes_cli/subcommands/peer.py` |

Routing is one function:

```js
async function requestForBot(bot, method, params = {}) {
  const route = botConnectionRoute(bot)
  if (route) return host.requestProfile(route, method, scopedBotParams(route, method, params))
  return host.request(method, params)
}
```

`peer.py`'s own docstring states the constraint plainly: *"No new server
surface: the peer's stock api_server is the transport."*

## 2. Where the group design beats A2A

**A2A has no groups.** The protocol is strictly 1:1 — client agent → remote
agent, one task, one context. No multicast, no group context id, no shared room.
That is a direct consequence of agents being opaque: there is no shared memory
to hang group state on.

Bot Mode's group model answers questions A2A does not ask:

- **one ordered room log with a single owner** — A2A has no global ordering
  across N peers
- **serial round-robin, no LLM router**, speaker chosen by a deterministic
  `@mention` parse — reproducible, which is rare in multi-agent systems
- **per-member persistent session + watermark delta** — like `contextId` but
  per-member rather than per-pair, and each member is fed only what it has not
  seen
- **epoch invalidation** — a new user message bumps the epoch and the in-flight
  round dies cleanly. A2A has no equivalent
- **`(pass)` as first-class** — *"Passing is good — it lets the conversation
  settle"*
- **stranded/harvest** — a reply that lands after its timeout is posted late
  into the right thread rather than lost

Cost model, from the `c021784a67` commit message: **`members × rounds` is the
real multiplier, not `members` alone** → `GROUP_CHAT_MAX_MEMBERS = 12`,
`groupChatMaxRoundsFor(n)`: `n≤4 → 4`, `n≤8 → 3`, else `2`.

## 3. The three gaps

### 3.1 Capability advertisement — **CLOSED**

The roster used to carry name + free-text description only, so the sole routing
mechanism was `@mention` — a human decision. Meanwhile this same install's A2A
Agent Card derives **33 skills** from the live tool registry automatically. The
richer layer already existed; the bots could not see it.

Now `_profile_capabilities()` surfaces each teammate's installed skill
**categories** (`security`, `governance`, `research`, `devops` — the top-level
dirs of `skills/`, which are already the semantic domains) as bounded tags:

```
- `@c1-security-purist` [collaboration, security]
- `@leader` — leader — you are the leader [apple, autonomous-ai-agents, brain-os, claim-verification]
```

Two decisions worth keeping:

**Cost.** `capability_fingerprint()` is deliberately uncached — it runs on
every Bot Chat turn. Measured on this fleet (12 profiles, 875 skills):

| approach | per call |
|---|---|
| recursive `**/SKILL.md` across all profiles | 20.74 ms |
| **top-level `iterdir()` across all profiles** | **0.56 ms** |

Same routing signal, ~37× cheaper. Total added cost: **0.66 ms, 2.8% of the
fingerprint call.**

**The invariant that makes it work.** Tags render into *every* teammate's
eternal prompt, so `capability_fingerprint()` had to grow a
`roster_capabilities` key. Without it, installing a skill on `researcher` would
never refresh anyone else's prompt and the whole fleet would route handoffs off
a list frozen at prompt-build time. Verified live: a real teammate gaining a
domain moves the fingerprint `f0b07ac0382c → c9de441ed2ab`; undoing it restores
the original hash exactly, and 6 consecutive calls on an unchanged surface
return one distinct value (prompt caching intact).

`protocol_version` 2 → 3 so existing eternal chats adopt the new block once.

### 3.1b The bug the real fleet exposed

A unit test alone would have missed this. Rendering the live roster showed:

```
- `@bot-plungin-manger` — bot plungin manger — bot plungin manger — bot plungin manger [...]
```

`_profile_role()` joins the Bot Mode title and the profile description, but the
Bots UI **seeds the description from the title**, so the join tripled the words
— in a block that lives in every teammate's eternal prompt. **5 of 12 profiles
affected. Pre-existing, unrelated to capability tags.** Fixed via
`_strip_title_echo()`; roster block 1566 → 1312 chars.

Lesson for this workspace: the first test asserted a length bound on a
*role-less* profile, so the dominant term was never in the assertion. The
rewritten test is shaped like the real fleet (long role + long category names)
and its bound is **structural** — `role cap (160) + tag budget (96) +
separators` — not a guessed number.

### 3.2 Identity inside the payload — **CLOSED (display layer)**

Measured before building. The probe ran the live regexes against the live
concatenation (`tools/bot_mode_dm.py` builds the prefix server-side):

**Direct spoofing was already blocked.** Every forged-body case still
attributed to the real sender (`dixie`), because `message_agent` applies the
prefix server-side and `previewKind()` matches the *start* of the delivered
text. The legacy shellout path keeps working but is no longer the attribution
source of truth.

**The real gap was one layer up: display.** `A2A_PREFIX_RE` stripped exactly
ONE prefix, so a body that itself opened with
`Message from 🤖 leader (@leader): …` became the visible text:

- roster row said **"from dixie"** while rendering a line reading
  **"Message from 🤖 leader"**
- second hop: dixie quoting what she was shown re-delivered the forgery as a
  first-class attribution line — after one strip it read as from `leader`

**Fix:** `stripDeliveryPrefix()` in `plugin.js` peels every *leading* prefix
(bounded at 8); both display sites (`generatedSessionTitle`, the roster row's
`displayPreview`) route through it. The row is now the ONLY thing that says who
sent a message — displayed bodies can never read as a second attribution.
Anchored `^` matching means honest mid-text mentions of "Message from…" are
never touched.

**Harness hardening:** `profile-prewarm.test.mjs` slices `BotRow` source
without its helper, so the new call sat outside the slice behind stubs that
never executed the branch — a latent ReferenceError plus a dead
`A2A_PREFIX_RE: /^$/` injection. Fixed by injecting the REAL stripper source
(`deliveryPrefixSource()`), same philosophy the harness already used for
`botConnectionRoute`.

Tests: `tests/sender-attribution.test.mjs` (5, RED first), bots suite
486/486 green. Remaining honesty boundary (model sees forged text as content)
is owned by the protocol-section untrusted-input framing, not by display.

### 3.3 No task object — **CLOSED (handoff ledger)**

Measured first: a DM left behind only a deleted temp file and a dangling
`process_id`. The relay path already had work-item plumbing (`envelope.id`,
`replies/<id>.json`, waiter) but it was transient (6h sweep), linked nothing,
and local/peer DMs had no equivalent at all.

**Built: `tools/bot_handoffs.py`** — append-only JSONL at
`<root>/bot_handoffs/handoffs.jsonl`, same root-level pattern as `bot_relay/`.
Every `message_agent` delivery appends one record:

```json
{"id": "96af0b931d1044f8", "at": 1787571429, "from": "default",
 "to": "c3-economist", "transport": "local", "process_id": "..."}
```

- **Choke point**: `_spawn_delivery` — all three transports (local / peer /
  relay) pass through it, so one recording site covers everything. Relay rows
  additionally carry `envelope_id`, joining the relay's existing reply
  plumbing instead of duplicating it.
- **The ack carries `handoff_id`** — the sender's model can cite the work item,
  and the reply still wakes the same background process.
- **No plaintext**: names + transport metadata only; swept on the relay clock
  (`STALE_AFTER_SECONDS`) via `cleanup_bot_handoff_ledger`, registered in the
  gateway housekeeping tuple next to Bot DM and Bot relay.
- **Never raises**: the ledger is observability — a failure to record can
  never block a send.

Live proof on the real fleet: a real `message_agent` call to `c3-economist`
wrote the record above and returned the matching `handoff_id` in its ack
(record removed afterwards — it was probe noise).

"Who owes whom what" is now answerable by reading one JSONL file instead of
inferring from message-count deltas in `session.resume` polling.

## 4. Where A2A actually belongs in this fleet

**At the machine boundary — not inside it.**

`hermes peer` does cross-machine correctly, but over a **private** endpoint
(`/api/sessions/{id}/chat` + `API_SERVER_KEY`). Consequence: a **non-Hermes
agent can never be a bot in this roster.** LangChain, CrewAI, Google ADK — all
locked out.

A2A is precisely the standard that opens that door, and this install is one
config key away:

```
have:  hermes serve on 0.0.0.0:9119 + a working cloudflared tunnel
        + the a2a toolset enabled (outbound works: a2a_call / a2a_discover / a2a_orchestrate)
need:  platforms.a2a.enabled   → inbound + a 33-skill Agent Card
```

Verified by running the real adapter: card at
`/.well-known/agent-card.json`, `message/send` returning
`TASK_STATE_COMPLETED`, and inbound peer text automatically framed as untrusted.

The coherent end state:

```
bot roster (same machine)   → WS RPC + subprocess     ← exists, and beats A2A here
peer bots (remote Hermes)   → hermes peer / api_server ← exists
non-Hermes agents           → A2A                      ← the only real gap
each agent's own tools      → MCP                      ← exists
```

## 5. Decision rules

1. **Do not replace the group transport with A2A.** A2A has no group semantics;
   this design is stronger there.
2. **Borrow A2A's three ideas, not its wire format:** capability descriptors
   (done), identity outside the payload, addressable work items.
3. **Reach for A2A only at the non-Hermes boundary.** Inside one install,
   `delegate_task` / group rounds / `message_agent` are correct.
4. **Anything rendered into the roster block must be hashed into
   `capability_fingerprint()`** — otherwise the change never reaches the fleet.
5. **Anything added to `capability_fingerprint()` pays its cost on every
   turn.** Measure before adding; prefer a shallow scan that carries the same
   signal.
6. **Verify roster changes by rendering the live fleet**, not only in unit
   tests. Both bugs found here (title echo, unbounded line) were invisible to
   the first passing test.

---

## Evidence

- Live A2A round-trip: real adapter, real card, real `message/send`
  (`TASK_STATE_COMPLETED`), 33 skills from the live registry
- Cost benchmark: 12 profiles / 875 skills, 20.74 ms vs 0.56 ms
- Fingerprint invariant: teammate change → hash moves; undo → hash restored;
  6 calls unchanged → 1 distinct value
- Tests: `tests/tools/test_bot_mode_probe.py`, 21 passed (RED first: 2 failures
  for tags, 2 for the fleet bug)
- MCP test failures seen during the wider run are **pre-existing** — reproduced
  on stashed-clean `HEAD`
