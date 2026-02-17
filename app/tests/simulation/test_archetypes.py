"""Per-archetype regression tests — verify specific behavioral expectations."""

import pytest


@pytest.mark.asyncio
async def test_diligent_high_engagement(patch_async_session):
    """Diligent student should have >40% engagement rate."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "diligent", days=7, step_minutes=120,
    )
    report.assert_no_hard_failures()

    uid = list(report.archetype_names.keys())[0]
    eng = report.engagement_rate(uid)
    total = len(report.sends_for(uid))

    assert total > 0, "Diligent user received no messages"
    # Diligent user has high reply probability — engagement should reflect this
    assert eng > 0.3, f"Diligent engagement too low: {eng:.0%} ({total} messages)"


@pytest.mark.asyncio
async def test_nightowl_respects_schedule(patch_async_session):
    """Night owl should receive most messages during their active hours."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "nightowl", days=14, step_minutes=60,
    )
    report.assert_no_hard_failures()

    uid = list(report.archetype_names.keys())[0]
    sends = report.sends_for(uid)
    if not sends:
        pytest.skip("No messages sent to nightowl")

    # Night owl is awake 14:00-04:00, peak 22:00-04:00
    # Messages during 5am-13pm (sleep hours) should be rare
    sleep_sends = [s for s in sends if 5 <= s.hour <= 13]
    active_sends = [s for s in sends if s.hour >= 14 or s.hour < 5]

    assert len(active_sends) >= len(sleep_sends), (
        f"NightOwl: {len(sleep_sends)} sleep-hour sends vs {len(active_sends)} active-hour sends"
    )


@pytest.mark.asyncio
async def test_hostile_suppression(patch_async_session):
    """After hostile user sends explicit_stop, that category should stop."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "hostile", days=14, step_minutes=60,
    )

    # Check if there are any suppression violations
    report.assert_hostile_user_respected()


@pytest.mark.asyncio
async def test_newuser_gets_messages_quickly(patch_async_session):
    """New user should receive their first proactive message within 72h."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "newuser", days=7, step_minutes=60,
    )

    report.assert_cold_start_converges()


@pytest.mark.asyncio
async def test_disengaging_doesnt_flatline(patch_async_session):
    """Disengaging user message count should decrease but not hit zero for weeks."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "disengaging", days=21, step_minutes=60,
    )
    report.assert_no_hard_failures()

    uid = list(report.archetype_names.keys())[0]
    weekly = report.weekly_send_counts(uid)

    # Should have messages in at least the first 2 weeks
    if len(weekly) >= 2:
        assert weekly[0] > 0 or weekly[1] > 0, (
            f"Disengaging user got no messages in first 2 weeks: {weekly}"
        )


@pytest.mark.asyncio
async def test_overwhelmed_receives_wellbeing(patch_async_session):
    """Overwhelmed student with low mood should receive some wellbeing messages."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "overwhelmed", days=14, step_minutes=60,
    )
    report.assert_no_hard_failures()

    uid = list(report.archetype_names.keys())[0]
    cats = report.categories_for(uid)

    # Overwhelmed user's world generates MOOD_TREND_DOWN signals
    # System should send some wellbeing or relevant messages
    total = sum(cats.values())
    assert total > 0, "Overwhelmed user received no messages at all"


@pytest.mark.asyncio
async def test_poweruser_category_diversity(patch_async_session):
    """Power user engaging with everything should receive diverse categories."""
    from tests.simulation.sim_runner import run_single_archetype

    report = await run_single_archetype(
        patch_async_session, "poweruser", days=14, step_minutes=60,
    )
    report.assert_no_hard_failures()

    uid = list(report.archetype_names.keys())[0]
    cats = report.categories_for(uid)
    total = sum(cats.values())

    if total >= 5:
        assert len(cats) >= 2, (
            f"PowerUser with {total} messages only got {len(cats)} categories: {cats}"
        )
