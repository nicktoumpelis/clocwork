# Agent log fixtures

Real Codex CLI, Gemini CLI and OpenCode session logs, reduced to what clocwork's token
readers use: session identity, working directory, remote, model, token
usage and timestamps. Prompts, replies, reasoning, tool calls, instructions,
branch names, commit hashes and time zones were removed, and only Codex's
`session_meta`, `turn_context`, `token_usage_record`, `token_count` and
`compacted` lines were kept.

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
- Every other file:
  [ingo-eichhorst/Irrlicht](https://github.com/ingo-eichhorst/Irrlicht) at
  `a3f1f8d4683e1194049a92b6b40e44d0aa11aef0`,
  `replaydata/agents/codex/scenarios/{1-6_checkpoint-rewind,5-3_model-switch-midsession,2-12_context-compaction}/`
  and
  `replaydata/agents/gemini-cli/scenarios/{1-4_session-resume,1-5_session-reset,1-6_checkpoint-rewind,2-3_task-list}/`,
  the first recording of each. A recording can hold several sessions one
  after another; each is a file of its own here, named the way the CLI
  names it.

## OpenCode

OpenCode keeps its sessions in SQLite, which no repository can hold as a
readable fixture, so its rows are committed as JSONL, one file per table,
and `tests/agent_logs.py` builds the database from them. Three buckets keep
provenance straight, and every row of all three is installed into one
database:

- **`s1/`: rows as recorded.** Identity, counts and timestamps are as the
  recording holds them; only the project id and the working directory are
  swapped for the placeholders. Two of the recordings carry no session row
  of their own - kimaki's is an event stream and codor's a run stream - so
  those session rows are assembled here from what the stream does say, and
  codor's version comes from the name of the file it ships in.
- **`s1-derived/`: recorded counts, minted ids.** Irrlicht's recorder
  strips ids, model providers and session rows, so the token counts and
  timestamps are real and everything that identifies them was minted here.
- **`s1-synthetic/`: hand-written.** The releases and providers no public
  recording covers: the counter rules of v1.0.x and of v1.3.4-v1.3.5, a
  non-zero `cache.write`, a fork's copy, a session whose project id belongs
  to another repository, a session only the experimental V2 table holds, and
  a session whose directory is empty.

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
- `s1-derived/`, the v1.14.50 counts:
  [ingo-eichhorst/Irrlicht](https://github.com/ingo-eichhorst/Irrlicht) at
  `7812f069afad9289a615cb968c375dfaed093780`,
  `replaydata/agents/opencode/scenarios/{5-3_model-switch-midsession,1-1_session-start}/`.
  MIT.

Across the four recordings, **8 records carry any reasoning tokens at all**,
and they are what decided the rule the reader uses: 3 whose `total` equals
input + output + cache, so the reasoning is already inside the output
(kimaki's OpenAI records, 50,769 / 46,737 / 47,319), and 5 where it equals
that plus the reasoning (kimaki's Gemini 39,176 / 39,110 / 43,610, codor's
10,134 and Irrlicht's 21,781). Every record in all four recordings has a
`cache.write` of 0, which is why the only cache-write case here is
hand-written.

## Licences

The Codex, Gemini and Irrlicht material is MIT-licensed, as is kimaki's and
codor's; OpenAgents' is Apache-2.0.

Copyright (c) 2026 Furkan Kalaycioglu

Copyright (c) 2025 Ingo Eichhorst

Copyright (c) 2025 Kimaki

Copyright (c) 2026 Richard Xiong

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

The OpenAgents rows are used under the Apache License, Version 2.0; a copy
is at <https://www.apache.org/licenses/LICENSE-2.0>. They are reduced to
token counts, ids and timestamps, with no modification beyond that and the
placeholder swaps, and the source repository is named above as the licence's
attribution notice requires.
