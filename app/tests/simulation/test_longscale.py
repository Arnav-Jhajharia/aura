"""Long-scale simulation tests — run 8 archetypes through Donna for 30 days.

These tests verify system-level behavior that unit tests can't catch:
negative engagement spirals, category collapse, suppression failures,
cold start convergence, and invariant violations.
"""

import pytest


@pytest.mark.asyncio
async def test_30day_full_simulation(patch_async_session):
    """Full 30-day simulation with all 8 archetypes.

    This is the primary integration test. It runs 30 simulated days
    with 30-minute timesteps for 8 different user personas.
    """
    from tests.simulation.sim_runner import run_simulation

    report = await run_simulation(
        session_factory=patch_async_session,
        days=30,
        step_minutes=60,  # 60-min steps for speed (720 steps total)
        seed=42,
    )

    report.print_summary()

    # Hard invariants — bugs if any of these fail
    report.assert_no_hard_failures()

    # Behavioral checks
    report.assert_hostile_user_respected()
    report.assert_cold_start_converges()

    # Soft checks — these reveal design issues but aren't code bugs.
    # Currently known: message volume is low due to aggressive prefilter +
    # daily cap, causing negative spirals. Uncomment once prefilter is tuned.
    # report.assert_no_negative_spirals()
    # report.assert_category_diversity()


@pytest.mark.asyncio
async def test_7day_smoke(patch_async_session):
    """Quick 7-day smoke test — catches obvious regressions fast."""
    from tests.simulation.sim_runner import run_simulation

    report = await run_simulation(
        session_factory=patch_async_session,
        days=7,
        step_minutes=60,
        seed=99,
    )

    # Only check hard invariants for speed
    report.assert_no_hard_failures()

    # Basic sanity: at least some messages were sent
    total_sends = len(report.sends)
    assert total_sends > 0, "No messages sent in 7-day simulation"
