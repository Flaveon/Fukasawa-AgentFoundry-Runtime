<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 ConcordiaPax LLC -->

# Environment Guide — the computers that can run agent steps

Fukasawa can run some workflow steps automatically, using AI on a computer you
point it at. This guide covers telling it which computers those are: finding
them, typing them in, reading what it learned, and what it does with that.

**None of this is needed to use the rest of Fukasawa.** Capture, validation,
promotion and export never require a computer. With none recorded, every
screen still works; the only consequence is that no step can be assigned to an
agent.

Two front ends, one set of rules. The desktop's **Environment** tab and the
terminal's `fukasawa node …` commands ask the same questions in the same order
and record the same things.

## Where should I look?

Nothing on the network is contacted until you choose how far to look. The
choice is recorded, and you can change it at any time.

| Choice | What it contacts | Terminal |
|---|---|---|
| **Just this computer** | this computer only, at the two usual addresses of Ollama (port 11434) and llama.cpp (port 8081). Nothing leaves this machine. | `node scan --scope this-machine` |
| **A computer I'll name** | the one address you give, on those two ports — or on the port you name | `node scan --scope named-host --host <address>` |
| **Every computer on this network** | **not built yet.** Choosing it contacts nothing and says so. | — |
| **Don't look at anything** | nothing. You type the computer in instead (below). | `node scan`, then choice 4 |

A look reports what it learns **as it learns it**, one line at a time: whether
something answered, which program it is, how many models it has, the largest
of them, the longest input any of them accepts, and whether a graphics card is
in use. A step that fails does not end the look — everything already found is
kept, and the line that failed says so plainly.

What is found is saved before the look says it has finished.

## Typing one in

Choose **I'll type it in** (desktop) or choice 4 on `node scan`'s menu
(terminal). You are asked:

1. **What should I call it?** — the name you will see everywhere.
2. **Address of the computer** — `192.168.1.20`, `kitchen-box.local`, or a full
   address such as `http://192.168.1.20:11434`.
3. **Which is running on it?** — Ollama or llama.cpp.

It is saved straight away and **not contacted**. Typing an address is not
permission to contact it. You are then asked separately:

> May I contact it now to see what it can run? Nothing else is contacted.

The answer defaults to **no**. Say yes and the one address you typed is looked
at; what is found fills in the record you just made, keeping the name, address
and program you gave. If nothing answers, the computer stays saved and is
marked as looked at and not answering.

A bare address gets that program's usual port (11434 for Ollama, 8081 for
llama.cpp). An address that names a port, or a full address, is kept as you
typed it. An address already recorded is refused, naming the computer that has
it — nothing is added and nothing is renamed.

## Reading a card

Every fact says where it came from:

| On screen | Means |
|---|---|
| *found it* | a look read it off the computer |
| *measured* | a look timed or counted it |
| *you told me* | you typed it — and it is never overwritten by a later look |
| *not sure* | nobody has established it |

Each card also says whether the computer answered:

| Status | Means |
|---|---|
| **Not checked yet** | typed in, and nothing has contacted it |
| **Answering when last checked** | the last look reached it |
| **Not answering when last checked** | it was looked at and nothing replied |

**Graphics card memory is always "or more".** A program like Ollama reports
how much graphics memory the models it has *loaded* are using, not how much
the card has. So the figure is a floor, and the screen never states it as a
total.

Figures are stated, never judged. "About 40 words a second" is a
measurement; whether that is enough depends on the work, which you know and
this program does not.

Buttons on each card: **Change something** (the name and the address; each
change is then marked *you told me*), **Check again** (look at that one
computer, at its recorded address), and **Forget** (press twice). Nothing can
be changed while a look is running — the buttons are unavailable until it
finishes.

## What this means when steps run

Below the cards, a short panel says what follows from the computers recorded:

```
What this means when steps run
  Agent steps can run on         Home PC, Kitchen Box (not checked yet)
  Longest input any model takes  about 6,100 words (8,192 tokens)
  Measured speed                 about 40 words a second
  Graphics card                  yes, on Home PC — 6 GB or more

  A step needing more than about 6,100 words of input is likely to fail on
  the computers checked so far.
```

- A computer that answered counts, and every figure comes from those.
- A computer **typed in and not yet checked** counts too, named as such, and
  adds no figures — recording it is what makes it one agent steps may run on.
- A computer **looked at that did not answer** does not count.

The last line appears only when it follows arithmetically. It says *likely to
fail* because a step longer than a model accepts either errors or is cut
short, and both fail the step. With an unchecked computer on the list it says
*the computers checked so far*, because the unchecked one might accept more.

## Using a recorded computer

A recorded computer is usable by name. A graph's model step says
`endpoint: kitchen-box` — the computer's id, shown by `node list` — and never
carries an address. `fukasawa model list` shows every usable name, including
recorded computers, and `fukasawa model test kitchen-box --model <name>`
sends it one prompt.

Using a computer you recorded needs no further permission. The permission
question exists for **looking** — reaching machines nobody named. A computer
you recorded is one you named.

## Where it is kept

One file: `$FUKASAWA_HOME/nodes.yaml` (by default `~/.fukasawa/nodes.yaml`),
holding the computers and the look permission together.

It describes somebody's house, so it stays there. It is never committed, never
bundled into a distribution, and never written into an exported brief — a
shared workflow names a computer and the address stays in this file. The file
can be edited by hand; one that cannot be read is named on screen, with what is
wrong with it, rather than failing silently.

An existing `model_endpoints.yaml` keeps working alongside it. Endpoints
resolve in this order, later winning: built-in defaults →
`model_endpoints.yaml` → `nodes.yaml`.

## Terminal equivalents

```bash
fukasawa node scan                  # asks where to look, then looks
fukasawa node scan --scope this-machine --yes
fukasawa node scan --scope named-host --host 192.168.1.20 --label "Kitchen Box"
fukasawa node scan --scope this-machine --yes --json   # one event per line
fukasawa node list                  # every computer, and the panel
fukasawa node show kitchen-box      # one computer, and every model it serves
fukasawa node add --label "Kitchen Box" --kind ollama --url http://192.168.1.20:11434
fukasawa node forget kitchen-box
fukasawa node consent               # the current look permission
fukasawa node consent --set this-machine
```

Exit codes: `0` done, `1` something to correct (an unknown choice, a missing
address, an address already recorded, a part not built yet), `3` a refusal —
`--scope none`, or `--yes` with no permission to look recorded.

## Not yet

- **Every computer on this network.** Offered, and answered with "not built
  yet". Name one computer's address instead.
- **Matching steps to computers.** Nothing yet checks whether a particular
  step can run on a particular computer; the panel's figures are for you to
  judge. This is phase 10b.
- **Programs other than Ollama and llama.cpp.** LM Studio, vLLM and other
  programs that speak the OpenAI format are planned (design §10.1).
- **A terminal command to edit a computer.** Change a name or address in the
  desktop, or in `nodes.yaml`.
