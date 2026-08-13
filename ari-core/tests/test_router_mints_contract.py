"""Any generator's proposal must be able to satisfy governed admission.

Regression: `_projection_meta` bubbled typed keys out of a *virsci* record only,
and virsci is opt-in and default-OFF. So a governed run routed to `cheap`,
produced a proposal with no Research Contract, and KCA admission refused it --
the governed path was reachable only when virsci happened to be enabled.
"""
from types import SimpleNamespace

from ari.rqgm.proposals.router import ProposalRouter


class _MCP:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.payload


def _router(*, governed=True, mcp=None):
    r = ProposalRouter.__new__(ProposalRouter)
    r.cfg = SimpleNamespace(
        knowledge=SimpleNamespace(mode="enforce" if governed else "off"),
        capability_binding=SimpleNamespace(mode="enforce" if governed else "legacy"),
        assurance=SimpleNamespace(mode="enforce" if governed else "off"),
    )
    r.mcp = mcp
    return r


def _record(title="Blocked GEMM"):
    return SimpleNamespace(
        status="selected",
        summary=SimpleNamespace(title=title, short_description="d",
                                hypothesis="h", experiment_plan=("step",)),
    )


CONTRACT = {"typed_schema_version": "ari.research-contract/v1",
            "contract_status": "admitted",
            "research_contract": {"title": "Blocked GEMM"},
            "research_contract_digest": "sha256:" + "a" * 64}


def test_a_cheap_proposal_gets_a_contract():
    mcp = _MCP(CONTRACT)
    meta = _router(mcp=mcp)._ensure_typed_contract([_record()], None, {"goal": "g"})
    assert meta["research_contract"] == {"title": "Blocked GEMM"}
    assert mcp.calls[0][0] == "mint_contract_for_proposal"
    assert mcp.calls[0][1]["proposal"]["title"] == "Blocked GEMM"


def test_an_ungoverned_run_is_left_alone():
    mcp = _MCP(CONTRACT)
    assert _router(governed=False, mcp=mcp)._ensure_typed_contract(
        [_record()], None, {"goal": "g"}) is None
    assert mcp.calls == []


def test_an_existing_contract_is_not_reminted():
    mcp = _MCP(CONTRACT)
    meta = {"research_contract": {"title": "already here"}}
    assert _router(mcp=mcp)._ensure_typed_contract([_record()], meta, {"goal": "g"}) is meta
    assert mcp.calls == []


def test_a_refusal_to_mint_is_not_turned_into_a_contract():
    # An empty literature snapshot must stay a refusal, never an invention.
    mcp = _MCP({"contract_status": "rejected", "research_contract": None})
    meta = _router(mcp=mcp)._ensure_typed_contract([_record()], None, {"goal": "g"})
    assert meta is None


def test_a_tool_failure_leaves_the_projection_untouched():
    class _Boom:
        def call_tool(self, *a, **k):
            raise RuntimeError("mcp down")
    meta = {"gap_analysis": "x"}
    assert _router(mcp=_Boom())._ensure_typed_contract(
        [_record()], meta, {"goal": "g"}) is meta
