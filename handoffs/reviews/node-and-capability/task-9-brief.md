# Task 9 brief — doctrine tests, documentation, the phase note

Written 2026-09-11, **after checking the plan's Task 9 section
(`docs/superpowers/plans/2026-08-23-node-and-capability.md`, lines 3010–3134)
against `main` at `fdea12d`.** Everything below overrides the plan's text.

## A gap in the phase itself, found while checking

**A recorded computer cannot be used by the runtime.** Design §6: "a node
automatically becomes a usable endpoint under its `node_id`". Task 5 built
`src/nodes/registry.py::merged_endpoints` to do exactly that, and tested it —
but no task wired it in. `src/cli.py::_model_endpoints()` still builds the
registry from `model_endpoints.yaml` alone, so `model list`, `model test` and
graph runs never see a computer added by `node scan`, `node add` or the
Environment tab. The unit tests tested the function; nothing tested that the
runtime calls it.

Fixed first, as its own commit, because every document Task 9 writes would
otherwise describe something that does not happen. An unusable `nodes.yaml`
must not stop graph runs that do not use it: it is named in a warning and the
runtime continues with the endpoints it can read.

## What the plan's text gets wrong

| # | Plan says | Why that is wrong now | Instead |
|---|---|---|---|
| 1 | an exported brief is checked for `http://`, `:11434` with **no computer recorded** | nothing on the export path reads node data, so with no computer recorded the test cannot fail — a fixture that makes the failure impossible | record computers at a distinctive documentation address, in `nodes.yaml` **and** `model_endpoints.yaml`, then export for real and search for that address |
| 2 | private-address allowlist `{"192.168.1.50", "10.0.0.9"}` | the tree already holds six more example addresses (tests, and the tab's placeholder); the test would fail on arrival | allow the examples by name with the reason; scan **tracked** files (`git ls-files`), since the repository is public |
| 3 | nothing about operator hostnames | spec §9 requires it, and a test cannot list them without publishing them | an optional `FUKASAWA_FORBIDDEN_NAMES` list, read at test time from the environment, never committed |
| 4 | README: replace "Known gaps" only | the README also lists no `node` commands, quotes test counts from phase 8, and its directory map has no `src/nodes/` | update all of it; guard `fukasawa node …` commands in the README against the CLI, as the workflow commands already are |
| 5 | `docs/environment-guide.md` only | `docs/desktop-guide.md` has no Environment tab; `docs/cli-guide.md` has no `node` commands | a section in each, pointing at the guide |
| 6 | nothing about `model list` | it still says an endpoint "carries no capabilities … see Known gaps" | say where computers are recorded and listed |
| 7 | spec §9 unchanged | §9 still says an empty store means "every step stays with you" — a phrase §3.1.2 of the same document forbids | the approved words: "no step can be assigned to an agent" |
| 8 | spec §9's "`node` only as a command noun" | no test checks it | check CLI and tab prose for `node`, *scope*, *endpoint*, *provenance*, *capability*, *VRAM* outside typed commands |
| 9 | FROZEN check `main...HEAD` | `main` already contains the whole phase, so that diff is empty and proves nothing | check from the phase's base, `3d81d36` |

## Public history

Not fixable by Task 9 and not attempted: commit `93e4d64` (Phase 5B) put the
operator's own LAN addresses into the default endpoint config, and `9d49d56`
removed them. They are gone from the tree and still in the public history.
Rewriting published history is the operator's decision. Recorded in the phase
note.
