# Agent log fixtures

Real Codex CLI and Gemini CLI session logs, reduced to what clocwork's token
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

## Licences

Both repositories are MIT-licensed.

Copyright (c) 2026 Furkan Kalaycioglu

Copyright (c) 2025 Ingo Eichhorst

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
