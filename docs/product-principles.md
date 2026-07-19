# Product Principles

## 1. Workflow Before Agent

Design the workflow first. Add agents only where judgment, interpretation, prioritization, or coordination is genuinely needed.

## 2. State Outside Chat

Chat is an interface, not durable memory. Runtime state must live in explicit files or a database.

## 3. Contracts Before Autonomy

An agent cannot safely act until its input contract, output contract, permissions, escalation rules, and review gates are defined.

## 4. Human Gates Are Features

Human approval should be a first-class runtime state, not an interruption or workaround.

## 5. Evidence Promotes Capability

Capability lift requires evidence: stable outputs, low error rate, correct escalation, and repeatable evaluation results.

## 6. Optimize Only What Can Be Scored

DSPy-style optimization is useful only after there are examples and metrics. Until then, write clearer contracts and collect reviewed cases.

## 7. Orchestration Must Stay Legible

LangGraph-style orchestration is useful only when it makes state, transitions, retries, and gates clearer. Do not hide the workflow in framework abstractions.

## 8. Local First, Portable Later

The first runtime should work from files, Python, SQLite or DuckDB, and local model adapters. Distribution comes after the local process proves useful.

## 9. Reduction Beats Control

When failure occurs, first ask whether the workflow is too complex. Add process only after reduction is insufficient.
