# Source archive — provenance

Files in this directory are **verbatim byte copies** of owner-authored source
documents. They are evidence of intended behaviour, not editable docs. Do not
reformat, re-wrap, fix typos in, or "update" them; write a new dated document
instead. `.gitattributes` marks this directory `-text` so Git never rewrites
line endings.

## 2026-05-31-fukasawa-quality-orchestrator-plan.md

| Field | Value |
|---|---|
| Title (front matter) | Fukasawa Quality Orchestrator Integration Plan |
| Date (front matter) | 2026-05-31 |
| Status (front matter) | draft — it was never marked approved; it records intent, not an accepted contract |
| Origin (front matter) | `wiki/Standards/FukasawaGPT` |
| Original location | `09_code/pipeline/docs/plans/2026-05-31-fukasawa-quality-orchestrator-plan.md` in the owner's Q2C pipeline workspace (private repository `Flaveon/q2c-pipeline`, path `docs/plans/…`) |
| First and only commit touching it | `c49a5cb644cf210731517a6af91fce284568324a`, 2026-05-31 01:43:50 UTC, "Add quality orchestration and deploy evidence" |
| Size | 18,458 bytes, 446 lines |
| SHA-256 | `82ca7abfbc78a2f0f82b7a8a0736e97e21d2f546d05b2e97d9b1307e10ad122f` |
| Imported | 2026-10-17, for issue #27 milestone M0 |

**How the bytes were verified.** The same SHA-256 was computed for: the file
as committed at `c49a5cb` (`git show c49a5cb:<path>`), the working copy in the
owner's pipeline checkout, and four further local checkouts of the pipeline
workspace (`q2c-substack`, `q2c-article-research-pr`,
`q2c-editorial-production-pr`, `q2c-local-research-pr`). All six match; the
file has not changed since it was written. To re-check:

```bash
sha256sum docs/source-archive/2026-05-31-fukasawa-quality-orchestrator-plan.md
```

**Relation to the summary.** `docs/2026-05-31-quality-orchestrator-source-guide-v1.0.md`
is a summary written later. It is not a substitute for this file; where the two
differ, this file is the original.

## Doctrine the plan cites (located, not imported)

The plan's "Source Review" names four documents under
`../wiki/Standards/FukasawaGPT/`. They exist in the owner's private `wiki`
repository. They are **not** copied here — importing them was not requested,
and the repository they live in is private. Their location and hashes are
recorded so a later reader can confirm which text the plan meant:

| Document | Location | SHA-256 |
|---|---|---|
| `FukasawaGPT.md` | `wiki/Standards/FukasawaGPT/` | `64fdc8a69f45b50ad972d340504d0204ecd05688b37a14185516f32d330a0f8c` |
| `Fukasawa_Task_Depth_Framework.md` | `wiki/Standards/FukasawaGPT/` | `bf7e8327c797981ee9f06116df98b68a0248c8fe72e4c1e7e1f56186f02adb35` |
| `Workflow_Design_Brief.md` | `wiki/Standards/FukasawaGPT/` | `d28aebb4e7d5b1b197e273e87daa8c56bb73118e538d0a184732666e098ea999` |
| `Non_Conformance_Improvement_Opportunity.md` | `wiki/Standards/FukasawaGPT/` | `eceecaa6311785f065f0dd0dcae9abb8f2e64da1aa9438f3c09b6d2dc8f17dd8` |

`AGENTS.md` points agents at a sibling copy, `../FukasawaGPT/`. That copy's
`Fukasawa_Task_Depth_Framework.md` is **older** (SHA-256
`4974547943e3febd744dd1129070e97edbfe4b5a403f866bc0a9a463010349e4`): the wiki
copy adds two sentences: "Lowest reasoning is a viability benchmark, not a
preference for weaker models." (near the top) and "Treat lowest reasoning as a
viability benchmark, not a preference for weaker models." (near the end). The
other three documents have identical content in both places; in the sibling
copy two of them carry different file names (`# FukasawaGPT.md`,
`# Non-Conformance Improvement Opportunit.md`), which are the names
`AGENTS.md` uses. Prefer the wiki copy; it is the one the plan cites.
