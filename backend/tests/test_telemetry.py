"""Tests for Neatlogs observability integration (aip.core.telemetry)."""

from __future__ import annotations

import neatlogs
import pytest

from aip.agents.orchestrator import DesignPipeline, PipelineConfig
from aip.core import telemetry
from aip.core.config import clear_settings_override, hermetic_settings, override_settings
from aip.domain.brief import default_residence_brief
from aip.engines.architecture.layout import GeneratorConfig


@pytest.mark.asyncio
async def test_pipeline_emits_neatlogs_hierarchy_when_enabled():
    exporter = neatlogs.InMemoryDiagnosticSpanExporter()
    neatlogs.init(
        api_key="test-key",
        disable_export=True,
        _doctor_probe=True,
        _doctor_probe_exporter=exporter,
        register_shutdown_handlers=False,
    )
    telemetry._INITIALIZED = True
    telemetry._ACTIVE = True
    override_settings(hermetic_settings(neatlogs_enabled=True, neatlogs_api_key="test-key"))

    try:
        brief = default_residence_brief()
        pipeline = DesignPipeline(
            PipelineConfig(
                candidate_count=1,
                generator=GeneratorConfig(population=10, generations=6, seed=7),
            )
        )
        res = await pipeline.run(brief)
        neatlogs.flush()

        envelopes = exporter.get_finished_envelopes()
        assert len(envelopes) >= 15
        names = {e.name for e in envelopes}
        assert "atriarch.design_pipeline" in names
        assert "rag.retrieve_for_brief" in names
        assert "critic.vastu" in names
        assert "critic.daylight" in names
        assert "offline.chat.completions" in names
        assert res.winner is not None
    finally:
        telemetry.shutdown_telemetry()
        clear_settings_override()
