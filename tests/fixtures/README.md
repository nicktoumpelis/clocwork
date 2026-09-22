# Agent log fixtures

Real Antigravity, Codex CLI, Copilot CLI, Gemini CLI, Kilo Code, OpenCode and Qwen Code
session logs, reduced to what clocwork's token readers use: session identity, working directory,
remote, model, token usage and timestamps. Prompts, replies, reasoning, tool
calls, instructions, branch names and time zones were removed, as were
commit hashes everywhere but the Copilot sessions, which keep theirs for the
reason given below; and only Codex's `session_meta`, `turn_context`,
`token_usage_record`, `token_count` and `compacted` lines were kept.

Every session is rewritten to a placeholder repository: its working
directory is `/work/agent-sample`, a Codex remote is
`https://github.com/example/agent-sample.git`, and a Gemini project hash is
the SHA-256 of `/work/agent-sample`. `tests/agent_logs.py` installs a copy
pointed at a temporary repository.

## Sources

- `codex/sessions/2026/08/26/` and `codex/sessions/2026/09/07/`:
  [furkankly/zoetrope](https://github.com/furkankly/zoetrope) at
  `b1f31dd26bd4e9e513885e39edb78d0850a5d1fe`, `assets/codex/cli-0.149.1/`
  and `assets/codex/cli-0.153.4/`.
- Every other `codex/` and `gemini/` file:
  [ingo-eichhorst/Irrlicht](https://github.com/ingo-eichhorst/Irrlicht) at
  `a3f1f8d4683e1194049a92b6b40e44d0aa11aef0`,
  `replaydata/agents/codex/scenarios/{1-6_checkpoint-rewind,5-3_model-switch-midsession,2-12_context-compaction}/`
  and
  `replaydata/agents/gemini-cli/scenarios/{1-4_session-resume,1-5_session-reset,1-6_checkpoint-rewind,2-3_task-list}/`,
  the first recording of each. A recording can hold several sessions one
  after another; each is a file of its own here, named the way the CLI
  names it.
- `copilot/session-state/`: the same repository at
  `bf9c07a50c715afde1b8f674061ef49fff9d9b27`,
  `replaydata/agents/copilot/scenarios/{1-2_session-end,1-4_session-resume}/`,
  the first recording of each — Copilot CLI 1.0.77 and 1.0.78. See below.
- `copilot-store/`: recorded for this repository on 2026-09-21 with Copilot
  CLI 1.0.87, in a throwaway git repository with `COPILOT_HOME` pointed at a
  temporary directory. Nobody else's data, so there is no licence to carry.
  See below.
- `qwen/`: recorded for this repository on 2026-09-21 (UTC) by running Qwen Code
  0.3.0, 0.4.0 and 0.24.2 from npm against a local mock of the OpenAI and
  Anthropic APIs, which answered "ok" with distinctive token counts. Real logs, written
  by the real CLI, around counts the mock chose; nobody's data and no
  licence to carry. See below.
- `antigravity/`: recorded for this repository on 2026-09-22 with agy 1.2.8,
  the Antigravity CLI, signed in to a real account, in a throwaway
  git repository with a fresh `HOME`. Real conversations with Gemini 3.8
  Flash; nobody else's data and no licence to carry. See below.

## Copilot CLI

Copilot writes one `events.jsonl` per session, under a directory named for
the session id, and the four files here are that layout. The recordings
concatenate the sessions of a replay into one transcript, so each session's
own records are split back out into the directory Copilot would have written
them to; the resumed session's block was recorded twice, and **that
repetition is kept**, because reading it once is the property the reader has
to have.

Only `session.start`, `session.resume`, `session.shutdown`,
`session.usage_checkpoint` and `assistant.message` are kept, reduced to the
fields the reader reads, plus the ones these notes rest on and a few that
sit beside them: the version, the branch, `reasoningTokens` and the rest of
`tokenDetails` are kept as evidence for what is said here, and
`startTime`, `hostType`, `shutdownType`, `resumeTime` and `requests.cost`
are kept because they cost nothing and show the shape a record really has.
Nothing reads any of them. The
checkpoint and the message are kept although the reader ignores them: the
checkpoint is where a reader might expect to find usage and does not, and
the message carries an output count that must not be added to the snapshot
that already covers it.

Between them the four sessions carry every rule a recording can show. The
rest have no recording and are tested against hand-written records in
`TestRules` instead -- among them a row whose own uncached input disagrees,
a snapshot grown in one counter and fallen in another, a snapshot with no
day, a non-JSON line, a log with no `session.start`, an unreadable log, and
every request count but one: each recorded row reports exactly one call, so
what a count does when it holds, falls, is omitted or is carried forward is
hand-written throughout.

- **`5920fe71…` and `5c068289…`** (v1.0.77, 2026-08-03): one `gpt-5-mini`
  snapshot each, the first mostly uncached input, the second almost all
  cache read. Their `tokenDetails` has no `cache_write` key at all.
- **`144d0848…`** (v1.0.77): a session that called no model, so its
  shutdown carries an **empty** `modelMetrics` -- present, and a table with
  nothing in it. A shutdown with the field missing altogether, or holding
  something that is not a table, is not a shape any recording has.
- **`aa737378…`** (v1.0.78, 2026-08-05): resumed once, so two cumulative
  snapshots — the second repeating the first model's row unchanged and
  adding a second model — and a real cache write. Its whole block appears
  twice.

The counts are as recorded. Every one of the four model rows has
`tokenDetails.input.tokenCount` equal to `inputTokens` less both cache
buckets (8,883 + 1,664 = 10,547; 435 + 10,112 = 10,547; 10 + 12,602 =
12,612; 9,277 + 1,536 = 10,813), which is what the reader checks each row
against. `reasoningTokens` is reported beside `outputTokens` in all four
(64 against 76, 64 against 89, 28 against 35, 64 against 88) with no
reasoning bucket in `tokenDetails`, and no record carries a total that could
settle whether it sits inside the output the way OpenCode's does.

The same identity held on a real Copilot CLI 1.0.87 install, run for #67
and committed as `copilot-store/` (below): its first shutdown has
`inputTokens` 47,986, cache read 35,818, cache write 12,156 and
`tokenDetails.input.tokenCount` 12. That run also confirmed the
layout these files are committed in (`$COPILOT_HOME/session-state/<session
id>/events.jsonl`, the directory named for `session.start`'s `sessionId`) and
that `COPILOT_HOME` moves the whole tree.

The author's own paths, branch and repository are replaced: `gitRoot` is the
placeholder and `cwd` a directory below it, as recorded, the branch is
`main`, and the repository is recorded as Copilot records one — the host and
`owner/name` apart, as `github.com` and `example/agent-sample`, which
together spell the placeholder remote. The recorded commit hashes are kept,
because they are a public repository's and the reader is shown asking git
about hashes that are not the test repository's.

## Copilot CLI store

`copilot-store/` is one real session read both ways Copilot CLI 1.0.87
records it: its `events.jsonl`, and the `session-store.db` beside
`session-state/`, whose `assistant_usage_events` table holds a row per model
call. The session made four calls, shut down, was resumed with `--resume`,
made a fifth and shut down again.

- **`session-state/20fdee16…/events.jsonl`**: only `session.start`,
  `session.resume` and the two `session.shutdown` records, each reduced to
  the fields the reader reads plus the version and the start, resume and
  shutdown fields the older recordings keep. The rest of the log — the
  system prompt, the messages, the tool calls — was dropped.
- **`s1/sessions.jsonl` and `s1/assistant_usage_events.jsonl`**: rows of the
  store's `sessions` and `assistant_usage_events` tables, which
  `tests/agent_logs.py` builds into `session-store.db`. The usage rows keep
  their ids, session id, turn index, model, the five token columns,
  `initiator`, `finish_reason` and `created_at` as recorded. Their
  `token_details_json` keeps each bucket's `tokenType` and `tokenCount` and
  drops its `model`, `batchSize` and `costPerBatch`. Every other usage
  column was dropped: `agent_id`, `parent_tool_call_id` and
  `copilot_usage_model` (null on every row here), `total_nano_aiu`,
  `request_multiplier`, the four latency columns, `api_endpoint`,
  `reasoning_effort` and `content_filter_triggered`. The session row keeps
  `id`, `cwd`, `repository`, `branch` and `created_at`, and drops
  `host_type`, `updated_at` and `summary`, which holds the prompt's text.
  None of the store's other tables is here; the reader reads only these two.

The counts are as recorded. The five rows sum to 15 uncached input, 248
output, 47,632 cache read and 12,503 cache write, which is exactly what the
second shutdown's cumulative `modelMetrics` reports (60,150 input, less
47,632 and 12,503, is 15). So the per-call path and the snapshot path agree
on this session, which is what lets the reader choose between them without
changing a total. Each row's `input_tokens` contains both cache buckets, as
`inputTokens` does, and its `token_details_json` input figure is the
uncached remainder (3 on every row).

The scratch paths are replaced by the placeholder, both in the log's
`cwd` and `gitRoot` and in the store's `sessions.cwd`. The repository had no
remote, so the store's `repository` is null and the log records none. The
commit hashes are the throwaway repository's.

## Qwen Code

Qwen Code writes its logs whether or not a real model answers, so these were
made by pointing it at a local mock of the OpenAI and Anthropic APIs
(`OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`) in a throwaway git repository with
a fresh `HOME`. Every count is the mock's, which is what lets each figure be
traced to the request that produced it, and what `RECORDED` in
`tests/test_sources_qwen.py` is computed from by hand.

- **`projects/-work-agent-sample/chats/*.jsonl`** (0.4.0 and 0.24.2): only
  the `ui_telemetry` records whose `uiEvent` is a `qwen-code.api_response`,
  reduced to the event's name, time, response id, model, auth type, status
  and token counts, and each run's one assistant record, reduced to its
  `usageMetadata`, kept to show it is not counted beside the telemetry. The
  prompts, replies, system records and the rest of each event were dropped.
  - `5cc0ed4c…` (0.24.2, `openai`): the main call, 1,001 input with 300
    cached, 21 output with 7 reasoning inside it (total 1,022), and the
    memory extractor's side call, 1,002 / 22 / 300, which has no assistant
    record of its own.
  - `d93d15d4…` (0.24.2, `anthropic`): the mock sent 500 uncached, 300 cache
    read, 40 cache write and 25 output; Qwen logged input 840 and cached 300,
    twice. The mock gave both calls the same response id; the run's own
    ledger (`usage/`, not kept) names them the main call and the memory
    extractor's. The cache write is folded into the input and reported
    nowhere else.
  - `f8fa5d6d…` (0.4.0, `openai`): 1,007 / 27 / 300, with the
    `tool_token_count` field that release still wrote.
- **`tmp/<sha256 of /work/agent-sample>/chats/session-*.json`** (0.3.0): the
  Gemini CLI format Qwen Code wrote before 0.4.0, reduced to each message's
  id, time, type, model and `tokens` (1,006 / 26 / 300, with `thoughts: 0`
  although the mock sent 7).

The working directories are the placeholder, and the project hash is the
placeholder's, so `tests/agent_logs.py` swaps both for the test repository.
The mock's model names, `mock-model` and `mock-claude`, are kept: they name
no real model and have no price, which is right for counts no model made.

## Antigravity

agy keeps each conversation in a SQLite database of protobuf blobs, which a
repository cannot hold as a readable fixture. So each table is committed as
JSONL, one directory per conversation under `conversations/`, with every
blob written as its protobuf field tree (`{"9": {"2": 11874}}`: field 9, a
message whose field 2 is 11,874). `tests/agent_logs.py` encodes the trees
back into protobuf and builds the databases. Only these fields were kept,
with the values as recorded:

- **`steps`**: each step's index and type, and from its metadata the time
  it was created (field 1) and, on a step that holds a model's reply, the
  call's usage (field 9).
- **`gen_metadata`**: each model call's usage (field 1.4) and model name
  (field 1.19).
- **`trajectory_metadata_blob`**: the conversation's start (field 2).
- In each usage message: the model's numeric id (1), input (2), output (3),
  thinking (9), visible reply (10) and response id (11). Fields 4 and 5, the
  cache write and read, appear in no call here. Field 6 (24 in every call,
  meaning unknown) and 7 and 8 (a bot id and a session id) were dropped.

Everything else was dropped: the prompts, the replies, the system prompt, the
tool calls and the executor's state. `conversation_summaries.jsonl` keeps
each summary row's `conversation_id` and `workspace_uris`, and drops its
title, its preview and the rest. `log/runs.jsonl` keeps the two facts the
reader takes from each CLI log: the run's `workspaceDirs`, and the
conversation it created. `tests/agent_logs.py` writes them back as the two
log lines agy prints for them.

There are three conversations, each on 2026-09-22:

- **`342e8ba1…`**: `agy -p` (print mode), one call, 11,874 input and 25
  output. Its summary row has no workspace, so it is placed by its CLI log
  alone.
- **`29ac6e7f…`**: interactive. `agy` asked for permission to create
  `hello.txt` and to run `git add hello.txt && git commit -m "Add hello"`,
  and made three calls (11,894 / 358, 12,378 / 151, 12,757 / 125). Its
  summary row names the workspace. The commit it made carries no
  `Co-authored-by` trailer.
- **`4b3fad79…`**: print mode, then continued twice with `--continue`, three
  calls (11,881 / 1,046, 13,333 / 26, 13,565 / 26). Placed by its log.

Each output holds its thinking: field 9 plus field 10 is field 3 in all
seven calls (e.g. 926 + 120 = 1,046). agy's own `--output-format json` agrees
with the stored fields. It reported 11,874 input, 25 output and 24 thinking
for the first conversation, and 11,881 input, 1,046 output and 926 thinking
for the third's first call. On each `--continue` it reports the conversation
so far rather than the call: 25,214 and 1,072, then 38,779 and 1,098, which
are the running sums of the stored calls. Those two outputs were read on
screen during the probe, not kept.

The scratch repository's path is replaced by the placeholder, in the
summaries' `file://` URI and in the logs.

## Kilo Code

Kilo Code is a fork of OpenCode and keeps the same store, so its rows are
committed the same way OpenCode's are — as JSONL, one file per table, built
into a database by `tests/agent_logs.py` — under `kilo/`, and installed as
`kilo.db`.

- **`s1/`: rows as recorded.** `message.jsonl` and `part.jsonl` hold the
  message and part ids, the models, the timestamps and the token counts as
  the export gives them. Two columns are filled in: the `session_id`, minted
  here to match the derived row below because the export names no session
  anywhere, and each part's `time_created`, taken from the message it hangs
  off, because the export carries a timestamp per message and not per part.
- **`s1-derived/`: the session row.** The export carries none, so this one
  is assembled here: a minted id, the placeholder project and directory, and
  the release its own provenance note states. Its roll-up columns are the
  true sums of the messages beside it.

The export is post-join JSON — each message with its parts — not SQL, so the
rows here are that shape unpacked back into the two tables Kilo writes.
Everything the reader does not read was dropped, which for this recording
means most of it: the prompts, the replies, the reasoning text, the tool
calls and their output, and the `path` the messages carry (its `cwd` was a
scratch directory and its `root` was `/`, and the session row's directory is
what places a session anyway). The `step-start` parts are kept, bare, to
show a part with no usage being passed over.

Six messages, four of them assistant messages carrying usage, all on
2026-08-10, and each one's
`total` equals its input + output + cache read **plus** its reasoning, so
every one of them says its reasoning sits outside the output:

| | input | output | reasoning | cache read | total |
|---|---|---|---|---|---|
| | 9,493 | 34 | 34 | 2,048 | 11,609 |
| | 411 | 98 | 153 | 11,264 | 11,926 |
| | 364 | 86 | 37 | 11,648 | 12,135 |
| | 9,890 | 47 | 17 | 2,048 | 12,002 |
| **sum** | **20,158** | **265** | **241** | **27,008** | |

So the archive records 20,158 input, 506 output (265 + 241), 27,008 cache
read and no cache write, over four turns.

Two things in it are the reason it was worth having. Every **assistant**
message names the model as `kilo-auto/free`, the router alias the user
chose, while every `step-finish` part names `stepfun/step-3.7-flash`, which
actually served the call — so a reader that took the message's name would file real usage under
a name that is not a model and has no price. And the session row's roll-up
columns hold Kilo's own sums of these same messages, so a reader that
counted them as well would report every figure twice.

No cache **write** appears anywhere in it, and no public Kilo store records
a session-row `version` — neither a `7.x.y` string nor the literal `local` a
build from source writes. Those two are covered by hand-written rows in
`tests/test_sources_kilo.py` instead, and the search that establishes their
absence is described in the source list below.

## OpenCode

OpenCode keeps its sessions in SQLite, which no repository can hold as a
readable fixture, so its rows are committed as JSONL, one file per table,
and `tests/agent_logs.py` builds the database from them. Three buckets keep
provenance straight, and every row of all three is installed into one
database:

- **`s1/`: rows as recorded.** Identity, counts and timestamps are as the
  recording holds them; only the project id and the working directory are
  swapped for the placeholders. Four of the recordings carry no session row
  of their own - kimaki's, tmux-pane-dash's and opencode.el's are event
  streams and codor's a run stream - so those session rows are assembled
  here from what the stream does say: its `session.updated` event where it
  has one, and for codor the name of the file it ships in.
- **`s1-derived/`: recorded counts, minted ids.** Irrlicht's recorder
  strips ids, model providers and session rows, so the token counts and
  timestamps are real and everything that identifies them was minted here.
- **`s1-synthetic/`: hand-written.** The releases and providers no public
  recording covers: the counter rules of v1.0.x and of v1.3.4-v1.3.5 (whose
  Anthropic records need a cache write to show them), a fork's copy, a
  session whose project id belongs to another repository, a session only
  the experimental V2 table holds, and a session whose directory is empty.

The file stores are hand-written too, in the layouts the releases wrote:
`storage/` as v0.6.0 to v1.1.65 wrote it, and
`project/work-agent-sample/storage/` as v0.1.0 to v0.5.29 did. No public
store from a real user was found for either. The database also holds a copy
of the `storage/` record, as v1.2.0's migration copies it, so that the
reader is shown counting a migrated record once.

### Sources

- `s1/`, the v1.17.9 rows (nine step-finish parts, every count in them
  zero, and the shape of every table including `session_message`):
  [OpenAgentsInc/openagents](https://github.com/OpenAgentsInc/openagents) at
  `8f84d05896ef14edee491621bf977ee5315cc8ed`, `docs/opencode/raw/`.
  Apache-2.0.
- `s1/`, the v1.2.15 and v1.2.20 records (Gemini and OpenAI counters, with
  a `total`): [remorses/kimaki](https://github.com/remorses/kimaki) at
  `4a36f47e45bf4778f682c145d98c8511adb272b1`,
  `cli/src/session-handler/event-stream-fixtures/`. MIT. These are server
  event streams, whose `message.updated` events carry the same objects the
  `message` rows hold; they are placed into rows here. Their provider id,
  `cached-google-real-events`, is the recorder's own: a caching proxy over
  a real Gemini key, so the counts are Gemini's and the label is not.
- `s1/`, the v1.17.14 record (real ids, real counts, no model named):
  [rjx18/codor](https://github.com/rjx18/codor) at
  `03481a33f87f8b16b8a35522084e37ebf7c9c168`,
  `packages/adapters/opencode/fixtures/live-pong-1.17.14.jsonl`. MIT.
- `s1/`, the v1.17.20 records (two Anthropic messages with a cache write
  and one OpenAI message with reasoning, of the 18 the streams hold):
  [xiopt/tmux-pane-dash](https://github.com/xiopt/tmux-pane-dash) at
  `1b358b9608e29fe550052ac5c9c13417cf2c9c95`,
  `opencode-plugin/tests/fixtures/{basic-idle,rich-permission-question-subagent,session-switch}.jsonl`.
  MIT. Event streams, placed into rows as kimaki's are.
- `s1/`, the v1.3.13 records (two Gemini messages with reasoning), the only
  recording from the window before v1.3.16:
  [karta0807913/opencode.el](https://github.com/karta0807913/opencode.el) at
  `31fccf10566c2e84e11d60f7f5fddb4fdc1c9689`,
  `test/fixtures/commit-tools-with-thinking/streaming-scenario.txt`.
  Apache-2.0. An event stream, placed into rows as kimaki's is. Its provider
  id, `Gemini`, is the user's own name for a custom provider.
- `kilo/`, one real Kilo Code 7.4.20 session (four assistant messages, the
  router alias beside the resolved model, no cache write):
  [autonomous-ai/openharness](https://github.com/autonomous-ai/openharness)
  at `a67e082b6e2985e7f226bf5737ebd3b39ce1d60b`,
  `cli/src/lib/__fixtures__/kilo-session.json`. **Apache-2.0** — the
  repository is MIT today, but it was relicensed on 2026-08-17, a week
  *after* the commit these rows come from, so they are used under the
  licence in force at that commit and not the current one. Its own spec
  describes the file as "a REAL kilo 7.4.20 session, exported from this
  machine's own kilo.db with the home directory scrubbed", which is where
  the release number comes from — the export holds no session row to read it
  off.
- `s1-derived/`, the v1.14.50 counts:
  [ingo-eichhorst/Irrlicht](https://github.com/ingo-eichhorst/Irrlicht) at
  `7812f069afad9289a615cb968c375dfaed093780`,
  `replaydata/agents/opencode/scenarios/{5-3_model-switch-midsession,1-1_session-start}/`.
  MIT.

Across the six recordings, **11 records carry any reasoning tokens at all**,
and they are what decided the rule the reader uses: 5 whose `total` equals
input + output + cache, so the reasoning is already inside the output
(kimaki's OpenAI records, 50,769 / 46,737 / 47,319, and opencode.el's Gemini
56,644 / 59,015), and 6 where it equals that plus the reasoning (kimaki's
Gemini 39,176 / 39,110 / 43,610, codor's 10,134, Irrlicht's 21,781 and
tmux-pane-dash's OpenAI 27,959). The same provider appears on both sides,
which is why the record's own `total` decides and neither the provider nor
the release. tmux-pane-dash's streams are the only ones with a cache write:
15 of their 18 records, from 36 to 51,300 tokens.

Three cases still have no recording, and are tested against hand-written
rows only:

- **A session only the experimental V2 table holds.** No OpenCode release
  note up to v1.18.31 says the V2 runner became the default, and every
  recorded store keeps its usage in the V1 tables, so a V2-only session is
  not yet one a user of a release would have.
- **The counter rules of v1.0.x and of v1.3.4-v1.3.5.** Both windows are
  superseded releases, and their readings come from `getUsage` as shipped at
  those tags.
- **The two file stores**, as v0.1.0 to v1.1.65 wrote them, which v1.2.0
  migrates into the database.

## Licences

The Codex, Copilot, Gemini and Irrlicht material is MIT-licensed, as is
kimaki's, codor's and tmux-pane-dash's; OpenAgents', opencode.el's and
openharness's are Apache-2.0.

Copyright (c) 2026 Furkan Kalaycioglu

Copyright (c) 2025 Ingo Eichhorst

Copyright (c) 2025 Kimaki

Copyright (c) 2026 Richard Xiong

Copyright (c) 2026 xiopt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The OpenAgents, opencode.el and openharness rows are used under the
Apache License, Version 2.0; a copy is at
<https://www.apache.org/licenses/LICENSE-2.0>. They are reduced to token
counts, ids and timestamps, with no modification beyond that and the
placeholder swaps, and each source repository is named above as the
licence's attribution notice requires.

openharness ships a NOTICE file at the commit its rows come from, whose
attribution the same licence requires be carried on:

> Autonomous Harness — Provider Protocol
> Copyright 2026 Autonomous, Inc.
>
> This product includes software developed at Autonomous, Inc.
>
> This repository is a *profile* of the Agent2Agent (A2A) protocol
> (<https://github.com/a2aproject/A2A>), which is itself licensed under
> Apache-2.0. It defines no competing protocol; everything specific to
> Autonomous is expressed as a declared A2A extension.
