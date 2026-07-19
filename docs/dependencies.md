# Dependencies

## Core Phase 1 Dependencies

Use boring local dependencies first.

- Python 3.11+
- Pydantic or JSON Schema validator
- PyYAML
- SQLite or DuckDB
- pytest
- jsonschema or pydantic validation tests

Recommended storage:

- JSON files for portable artifacts
- SQLite for run ledger and state transitions
- DuckDB for analytical queries across runs, evals, and non-conformance records

## Optional Phase 2 Dependencies

- Jinja2 for templates
- Typer or argparse for CLI
- rich for readable terminal output
- pytest snapshot-style tests for generated packages

## Optional Phase 3 Dependencies

- local model adapter through Ollama or llama.cpp
- OpenAI API adapter for cloud model calls
- lightweight embedding model only if retrieval is needed

## Optional Phase 4 Dependencies

- LangGraph, only if the in-house state graph becomes too costly to maintain
- FastAPI, only when moving beyond CLI/local files
- MCP SDK, only when exposing runtime actions to agent hosts

## Optional Phase 6 Dependencies

- DSPy, only when prompt/module examples and metrics exist
- Qdrant, only when vector search beats the local lexical baseline on reviewed cases

## External Framework Adoption Test

Before adding any external framework, answer:

- What missing primitive does it provide?
- Can that primitive be implemented locally in less code?
- Does it preserve file-based inspectability?
- Does it make state easier to see?
- Does it make human gates clearer?
- Does it introduce vendor or dependency lock-in?
- What is the rollback path?

If the answers are weak, do not adopt it.
