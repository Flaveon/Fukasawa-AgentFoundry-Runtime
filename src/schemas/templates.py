# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Hand-editable templates for the contracts a person fills in.

Lives outside both the CLI and the GUI because both create drafts, and a
teaching template that exists in two copies is a template that will say two
different things about the rules within a release or two. The comments carry
rule ids, so drift here is drift in what the product teaches.
"""

#: A valid but deliberately incomplete draft. It saves and reloads; the
#: validator then names what is missing. Comments carry the rule ids so the
#: template teaches the rules rather than merely satisfying them.
DRAFT_SKELETON = """\
# Workflow draft — created by Fukasawa.
#
# Record what ACTUALLY happens, gaps included. This file is allowed to be
# incomplete: `fukasawa workflow validate` will list what is missing, and
# nothing here blocks saving it. Honest capture comes first.

schema_version: '1'
workflow_id: {workflow_id}
name: {name}
version: '1'
maturity: OBSERVED

purpose: ''            # why this workflow exists
trigger: ''            # what starts it            <- required (HW-001)
claimed_outcome: ''    # what it is supposed to achieve  <- required (HW-002)

actors: []             # every person or agent involved
systems: []            # tools and services it touches
artifacts: []          # things it produces

steps:
- step_id: first-step
  name: First step
  description: ''
  action: ''
  actor: ''            # who performs it           <- always required (HW-003)
  decision_authority: ''  # who decides here
                       # HW-004 requires this once the step branches, is gated,
                       # or has irreversible or high-risk effect. Fill it in
                       # anyway: cooperation assessment floors a step with no
                       # named authority at NOT_READY_FOR_AUTOMATION.
  trigger: ''
  preconditions: []
  inputs: []           # name / source / required  (HW-009 wants a source)
  outputs:
  - name: ''
    artifact_type: ''          # HW-010 wants both of these
    evidence_requirement: ''
  entry_condition: ''
  exit_condition: ''   # how you know it finished  (vague wording -> HW-014)
  next_steps: []       # step ids that may follow; empty means terminal
  exception_paths: []  # failure_mode / owner / handling / next_step
  characteristics:
    # Each defaults to UNKNOWN, and UNKNOWN always resolves toward a human.
    # Fill these in before assessing cooperation, or every step floors at
    # NOT_READY_FOR_AUTOMATION -- which is the honest answer, not a bug.
    judgment_load: UNKNOWN      # NONE | LOW | MODERATE | HIGH
    repeatability: UNKNOWN      # ONE_OFF | OCCASIONAL | ROUTINE
    determinism: UNKNOWN        # DETERMINISTIC | MOSTLY_DETERMINISTIC | JUDGMENT_BASED
    risk: UNKNOWN               # LOW | MODERATE | HIGH
    reversibility: UNKNOWN      # REVERSIBLE | PARTIALLY_REVERSIBLE | IRREVERSIBLE
    data_sensitivity: UNKNOWN   # PUBLIC | INTERNAL | SENSITIVE

gates: []              # observed approval points: gate_id / at_step / approver
                       # / criteria / on_approve / on_reject

observed_exceptions: []  # failure modes seen in practice
unwritten_rules: []      # what people know but nobody wrote down (HW-013)
known_pain_points: []    # where it hurts today, in the operators' words
source_evidence: []      # kind / reference / note
notes: ''
"""
