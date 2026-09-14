"""A figure operation must never adopt files that predate the invocation."""

from __future__ import annotations

import asyncio

import pytest

from ari.public.figures import parse_figure_batch

import planning
import server
from test_planning import _Response, _science_file


def test_preexisting_figure_is_not_adopted_by_fixed_renderer(tmp_path):
    science = _science_file(tmp_path)
    stale = tmp_path / "fig_1.pdf"
    stale_payload = b"%PDF-1.4 stale from an earlier run"
    stale.write_bytes(stale_payload)

    batch = parse_figure_batch(
        asyncio.run(
            server.generate_figures(
                science_data_path=str(science),
                output_dir=str(tmp_path),
                n_figures=1,
            )
        )
    )

    assert stale.read_bytes() == stale_payload
    assert "fig_1.pdf" not in set(batch.figures.values())
    assert all(item.spec.source.record_ids for item in batch.manifests)


def test_failed_planner_does_not_promote_preexisting_figures(
    tmp_path, monkeypatch
):
    science = _science_file(tmp_path)
    stale = tmp_path / "fig_1.pdf"
    stale_payload = b"%PDF-1.4 rejected by an earlier review"
    stale.write_bytes(stale_payload)

    async def invalid(**_kwargs):
        return _Response("I could not produce figures.")

    monkeypatch.setattr(planning.litellm, "acompletion", invalid)
    with pytest.raises(ValueError, match="planner|JSON|response"):
        asyncio.run(
            server.generate_figures_llm(
                science_data_path=str(science),
                output_dir=str(tmp_path),
                n_figures=1,
            )
        )

    assert stale.read_bytes() == stale_payload
    assert not list((tmp_path / "figures").glob("*.pdf"))
