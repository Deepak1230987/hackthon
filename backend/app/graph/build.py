import time
from collections.abc import Awaitable, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.graph.deps import Deps
from app.graph.nodes.acquire import acquire
from app.graph.nodes.compile_rules import compile_rules
from app.graph.nodes.evaluate import evaluate
from app.graph.nodes.extract import extract
from app.graph.nodes.guard import guard, needs_translation
from app.graph.nodes.parse import parse
from app.graph.nodes.passthrough import passthrough
from app.graph.nodes.script import script
from app.graph.nodes.segment import segment
from app.graph.nodes.translate import translate
from app.graph.nodes.triage import triage
from app.graph.nodes.tts import tts
from app.graph.nodes.verify import needs_repair, verify
from app.graph.state import RunState

Node = Callable[[RunState, Deps], Awaitable[dict | None]]

# In workflow order. Each entry is replaced as its phase is built.
NODES: list[tuple[str, Node]] = [
    ("acquire", acquire),
    ("parse", parse),
    ("segment", segment),
    ("triage", triage),
    ("extract", extract),
    ("verify", verify),
    ("compile_rules", compile_rules),
    ("evaluate", evaluate),
    ("script", script),
    ("translate", translate),
    ("guard", guard),
    ("tts", tts),
]


def _traced(name: str, node: Node, deps: Deps):
    async def run(state: RunState) -> dict:
        run_id = state["run_id"]
        await deps.events.emit(run_id, "node_started", {"node": name})
        started = time.monotonic()
        update = await node(state, deps) or {}
        await deps.events.emit(
            run_id,
            "node_finished",
            {
                "node": name,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "implemented": node is not passthrough,
            },
        )
        return update

    return run


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver):
    graph = StateGraph(RunState)
    previous = START
    for name, node in NODES:
        graph.add_node(name, _traced(name, node, deps))
        if previous == "verify":
            # Rejected claims go back for repair, a limited number of times.
            async def route_after_verify(state: RunState, following: str = name) -> str:
                return "extract" if await needs_repair(state, deps) else following

            graph.add_conditional_edges("verify", route_after_verify, ["extract", name])
        elif previous == "guard":
            # Translations the guard failed are tried again, a limited number of times.
            async def route_after_guard(state: RunState, following: str = name) -> str:
                return "translate" if await needs_translation(state, deps) else following

            graph.add_conditional_edges("guard", route_after_guard, ["translate", name])
        else:
            graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=checkpointer)
