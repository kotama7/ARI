"""When a governed run needs a typed contract, the generator that mints one must
actually be routable.

Regression: `_enabled` returned True for virsci whenever knowledge/capability/
assurance were not all at their defaults, but `_available_for_event` then
dropped virsci unless `trigger_on` named the event -- and it names none by
default. Every governed run therefore routed to `cheap`, whose proposal has no
Research Contract, and KCA admission refused it.
"""
from types import SimpleNamespace

from ari.rqgm.proposals.router import ProposalRouter


def _router(*, governed: bool, trigger_on=()):
    cfg = SimpleNamespace(
        knowledge=SimpleNamespace(mode="enforce" if governed else "off"),
        capability_binding=SimpleNamespace(mode="enforce" if governed else "legacy"),
        assurance=SimpleNamespace(mode="enforce" if governed else "off"),
        proposal_router=SimpleNamespace(
            generators=SimpleNamespace(
                virsci=SimpleNamespace(enabled=True, trigger_on=list(trigger_on),
                                       max_calls_per_epoch=0))),
    )
    router = ProposalRouter.__new__(ProposalRouter)
    router.cfg = cfg
    router._generators = {"cheap": object(), "virsci": object()}
    return router


def test_governed_run_can_route_to_virsci_without_trigger_on():
    router = _router(governed=True, trigger_on=())
    assert "virsci" in router._available_for_event("initial_exploration")


def test_ungoverned_run_still_obeys_trigger_on():
    router = _router(governed=False, trigger_on=())
    assert "virsci" not in router._available_for_event("initial_exploration")


def test_ungoverned_run_routes_to_virsci_when_trigger_on_names_the_event():
    router = _router(governed=False, trigger_on=("initial_exploration",))
    assert "virsci" in router._available_for_event("initial_exploration")
