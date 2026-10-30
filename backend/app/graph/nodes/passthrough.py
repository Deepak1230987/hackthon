from app.graph.deps import Deps
from app.graph.state import RunState


async def passthrough(state: RunState, deps: Deps) -> None:
    """Stands in for a node that isn't built yet. Its trace event says so."""
