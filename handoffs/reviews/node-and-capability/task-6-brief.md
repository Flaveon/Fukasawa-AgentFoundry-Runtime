### Task 6: The `node` CLI sub-app

**Files:**
- Modify: `src/cli.py` (add a `node_app` Typer sub-app and register it beside the existing `model_app`)
- Test: `tests/test_node_cli.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: commands `node scan`, `node list`, `node show`, `node add`, `node forget`, `node consent`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_cli.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""The command line, in the same voice as the desktop.

Not terse. A person who reached for a terminal still deserves sentences, and
the copy rules of the design apply here exactly as they do on screen.
"""

import json

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.nodes.store import NodeStore
from src.schemas.node import (
    InferenceNode,
    ModelCapability,
    NodeKind,
    ScanConsent,
    ScanScope,
)

JUDGEMENT = ["slow", "fast", "good", "poor", "powerful", "weak", "adequate"]
OWNERSHIP = ["stays with you", "your workflow", "your model", "off your hands"]


@pytest.fixture()
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "nodes.yaml"
    monkeypatch.setattr("src.nodes.store.NodeStore.default_path",
                        staticmethod(lambda: path))
    return path


def seed(store_path, **kw):
    store = NodeStore(store_path)
    base = dict(node_id="home-pc", label="Home PC", kind=NodeKind.OLLAMA,
                url="http://localhost:11434", reachable=True,
                models=[ModelCapability(name="llama3.1:8b", context_length=8192)])
    base.update(kw)
    store.save([InferenceNode(**base)],
               ScanConsent.granted(ScanScope.THIS_MACHINE, "sam"))
    return store


class TestList:
    def test_nothing_configured_says_what_the_program_does(self, store_path):
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "nothing yet" in result.output
        assert "do not require a computer" in result.output

    def test_a_stored_computer_is_shown_with_its_figures(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list"])
        assert result.exit_code == 0
        assert "Home PC" in result.output
        assert "words" in result.output

    def test_json_output_is_machine_readable(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "list", "--json"])
        payload = json.loads(result.output)
        assert payload["nodes"][0]["node_id"] == "home-pc"


class TestScan:
    def test_scanning_without_permission_is_refused_not_crashed(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "none", "--yes"])
        assert result.exit_code == 3, result.output
        assert "permission" in result.output.lower()

    def test_an_unknown_scope_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "scan", "--scope", "wat", "--yes"])
        assert result.exit_code == 1

    def test_a_scan_prints_each_finding_as_it_arrives(self, store_path, monkeypatch):
        from src.nodes.discovery import DiscoveryEvent

        def fake(scope, host="", **kw):
            yield DiscoveryEvent("trying", "Looking on port 11434...")
            yield DiscoveryEvent("reachable", "Something's listening on port 11434")
            yield DiscoveryEvent("done", "Found 1 computer.", finished=True)

        monkeypatch.setattr("src.cli._discover", fake)
        result = CliRunner().invoke(
            app, ["node", "scan", "--scope", "this-machine", "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "Looking on port 11434" in result.output
        assert "Found 1 computer." in result.output


class TestAddAndForget:
    def test_a_computer_can_be_added_by_hand(self, store_path):
        result = CliRunner().invoke(app, [
            "node", "add", "--label", "Kitchen Box", "--kind", "ollama",
            "--url", "http://10.0.0.9:11434",
        ])
        assert result.exit_code == 0, result.output
        nodes, _ = NodeStore(store_path).load()
        assert nodes[0].node_id == "kitchen-box"
        assert nodes[0].source_of("url").value == "DECLARED"

    def test_forgetting_something_absent_is_a_user_error(self, store_path):
        result = CliRunner().invoke(app, ["node", "forget", "nope"])
        assert result.exit_code == 1
        assert "nope" in result.output


class TestConsent:
    def test_the_current_permission_is_shown(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent"])
        assert result.exit_code == 0
        assert "this computer" in result.output.lower()

    def test_permission_can_be_changed(self, store_path):
        seed(store_path)
        result = CliRunner().invoke(app, ["node", "consent", "--set", "none"])
        assert result.exit_code == 0
        _nodes, consent = NodeStore(store_path).load()
        assert consent.scope is ScanScope.NONE


class TestCopyRules:
    @pytest.mark.parametrize("argv", [
        ["node", "list"],
        ["node", "consent"],
    ])
    def test_no_command_judges_or_assumes_ownership(self, store_path, argv):
        seed(store_path)
        output = CliRunner().invoke(app, argv).output.lower()
        assert not [w for w in JUDGEMENT if w in output]
        assert not [w for w in OWNERSHIP if w in output]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_node_cli.py -q`
Expected: FAIL — no `node` command registered.

- [ ] **Step 3: Write the implementation**

Add to `src/cli.py`. Place the sub-app registration beside the existing `model_app` registration, and the commands after the `model` section.

```python
# --- near the other sub-app definitions -------------------------------------
node_app = typer.Typer(help="Tell Fukasawa what computers can run AI for it.")
app.add_typer(node_app, name="node")


# --- indirection so tests can substitute the scanner -------------------------
def _discover(scope, host="", **kwargs):
    """Run a scan. Named so a test can replace it without a live network."""
    from src.nodes.discovery import discover

    return discover(scope, host, **kwargs)


def _node_store():
    """Open the store at its configured location."""
    from src.nodes.store import NodeStore

    return NodeStore()


#: Both directions of the scope vocabulary, declared once. The CLI flag values
#: are hyphenated; the enum values are not; the sentence is neither.
_SCOPE_FLAGS = {
    "none": "NONE",
    "this-machine": "THIS_MACHINE",
    "named-host": "NAMED_HOST",
    "local-network": "LOCAL_NETWORK",
}
_SCOPE_WORDS = {
    "NONE": "Not looking at anything",
    "THIS_MACHINE": "Just this computer",
    "NAMED_HOST": "One computer, named",
    "LOCAL_NETWORK": "Every computer on this network",
}


def _scope_from(text: str):
    """Turn a --scope value into a ScanScope, or exit 1 naming the choices."""
    from src.schemas.node import ScanScope

    if text not in _SCOPE_FLAGS:
        console.print(
            f"[red]'{text}' is not one of the choices.[/red] "
            f"Use one of: {', '.join(_SCOPE_FLAGS)}"
        )
        raise typer.Exit(1)
    return ScanScope(_SCOPE_FLAGS[text])


def _render_summary(nodes) -> None:
    """Print the panel: figures with units, and at most one consequence."""
    from src.nodes.summary import summarise

    summary = summarise(nodes)
    console.print("\n[bold]What this means when steps run[/bold]")
    for row in summary.rows:
        source = f"   [dim]{row.source}[/dim]" if row.source else ""
        console.print(f"  {row.label:<32} {row.value}{source}")
    if summary.consequence:
        console.print(f"\n  {summary.consequence}")


@node_app.command("scan")
def node_scan(
    scope: str = typer.Option(
        "", "--scope", help="none | this-machine | named-host | local-network"
    ),
    host: str = typer.Option("", "--host", help="Address, for --scope named-host."),
    label: str = typer.Option("", "--label", help="What to call what is found."),
    yes: bool = typer.Option(False, "--yes", help="Skip the prompts."),
    as_json: bool = typer.Option(False, "--json", help="One event per line, as JSON."),
) -> None:
    """Look for computers that can run AI, and record what is found.

    Nothing is examined until a permission is chosen. Findings are printed as
    they arrive rather than in a block at the end, because a scan takes time
    and a person watching one deserves to see it happening.
    """
    from src.schemas.node import ScanConsent, ScanScope

    store = _node_store()
    _nodes, existing = store.load()

    if scope:
        chosen = _scope_from(scope)
    elif yes:
        chosen = existing.scope
    else:
        console.print(
            "\nFukasawa can run some workflow steps automatically, using AI\n"
            "on a computer you point it at.\n"
        )
        console.print("[bold]Where should I look?[/bold]")
        console.print("  1  Just this computer            nothing leaves this machine")
        console.print("  2  A computer I'll name")
        console.print("  3  Every computer on this network  takes about a minute; some")
        console.print("                                     workplaces disallow this")
        console.print("  4  Don't look — I'll type it in")
        answer = typer.prompt("Choose", default="1")
        chosen = {
            "1": ScanScope.THIS_MACHINE,
            "2": ScanScope.NAMED_HOST,
            "3": ScanScope.LOCAL_NETWORK,
            "4": ScanScope.NONE,
        }.get(answer.strip(), ScanScope.THIS_MACHINE)

    if chosen is ScanScope.NONE:
        console.print(
            "[yellow]Refused:[/yellow] no permission to look. "
            "Choose a different option, or add a computer with "
            "[cyan]fukasawa node add[/cyan]."
        )
        raise typer.Exit(3)

    if chosen is ScanScope.NAMED_HOST and not host:
        host = typer.prompt("Address of the computer")

    store.set_consent(ScanConsent.granted(chosen, "operator"))

    console.print("")
    found = []
    for event in _discover(chosen, host):
        if as_json:
            # NOTE: src/cli.py imports the json module as `jsonlib`.
            console.print(jsonlib.dumps({
                "stage": event.stage, "message": event.message,
                "ok": event.ok, "finished": event.finished,
            }))
        else:
            mark = "  [green]OK[/green]" if event.ok else "  [yellow]--[/yellow]"
            console.print(f"{mark}  {event.message}")
        if event.node is not None and event.node not in found:
            found.append(event.node)

    for node in found:
        if label:
            node.label = label
        store.upsert(node)

    if found:
        _render_summary(store.load()[0])


@node_app.command("list")
def node_list(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show every computer Fukasawa has been told about."""
    nodes, _consent = _node_store().load()
    if as_json:
        console.print(jsonlib.dumps(
            {"nodes": [n.model_dump(mode="json") for n in nodes]}, indent=2
        ))
        return

    from src.nodes.summary import human_words, source_label

    for node in nodes:
        console.print(f"\n[bold]{node.label}[/bold]  [dim]{node.url}[/dim]")
        console.print(f"  Models it can run    {len(node.models)}")
        if node.max_context_length:
            console.print(
                f"  Longest input        {human_words(node.max_context_length)}"
                f"   [dim]{source_label(node.source_of('models'))}[/dim]"
            )
    _render_summary(nodes)


@node_app.command("show")
def node_show(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Show one computer and every model it can serve."""
    nodes, _ = _node_store().load()
    match = next((n for n in nodes if n.node_id == node_id), None)
    if match is None:
        console.print(f"[red]Nothing stored called '{node_id}'.[/red]")
        raise typer.Exit(1)

    from src.nodes.summary import human_bytes, human_rate, human_words

    console.print(f"\n[bold]{match.label}[/bold]  [dim]{match.url}[/dim]")
    console.print(f"  Answering            {'yes' if match.reachable else 'no'}")
    console.print(f"  Speed                {human_rate(match.host.tokens_per_second)}")
    console.print(f"  Graphics card        {human_bytes(match.host.vram_bytes)}")
    for model in match.models:
        console.print(
            f"    {model.name:<28} {human_words(model.context_length)}"
        )


@node_app.command("add")
def node_add(
    label: str = typer.Option(..., "--label", help="What to call it."),
    kind: str = typer.Option(..., "--kind", help="ollama | llamacpp"),
    url: str = typer.Option(..., "--url", help="Base URL it answers on."),
) -> None:
    """Add a computer by hand, without looking for it."""
    from src.schemas.node import InferenceNode, NodeKind, Provenance, slugify

    if kind not in {k.value for k in NodeKind}:
        console.print(f"[red]'{kind}' is not one of: ollama, llamacpp[/red]")
        raise typer.Exit(1)

    node = InferenceNode(
        node_id=slugify(label), label=label, kind=NodeKind(kind), url=url,
        provenance={
            "label": Provenance.DECLARED,
            "url": Provenance.DECLARED,
            "kind": Provenance.DECLARED,
        },
    )
    _node_store().upsert(node)
    console.print(f"Added [bold]{label}[/bold].")


@node_app.command("forget")
def node_forget(node_id: str = typer.Argument(..., help="Which computer.")) -> None:
    """Remove a computer."""
    if not _node_store().forget(node_id):
        console.print(f"[red]Nothing stored called '{node_id}'.[/red]")
        raise typer.Exit(1)
    console.print(f"Removed {node_id}.")


@node_app.command("consent")
def node_consent(
    set_to: str = typer.Option("", "--set", help="none | this-machine | named-host | local-network"),
) -> None:
    """Show or change how far a scan may reach."""
    from src.schemas.node import ScanConsent

    store = _node_store()
    _nodes, consent = store.load()
    if not set_to:
        console.print(f"Currently: {_SCOPE_WORDS[consent.scope.value]}")
        return
    chosen = _scope_from(set_to)
    store.set_consent(ScanConsent.granted(chosen, "operator"))
    console.print(f"Changed to: {_SCOPE_WORDS[chosen.value]}")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/test_node_cli.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Run the whole suite — `src/cli.py` is shared**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regression in `tests/test_workflow_cli.py`.

- [ ] **Step 6: Commit**

```bash
git add src/cli.py tests/test_node_cli.py
git commit -m "feat: a node sub-app that speaks in sentences"
```

---

