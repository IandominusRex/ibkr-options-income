"""GET /envelope (risk-envelope plan Task 14): the latest measurement, the limits, the glide, the
switches and the Leveraged Entry Signal, read-only from the trading DB. Unknown is null, never 0."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from src.common.envelope_types import ShockResult
from tests.conftest import OWNER


def _result(s10: float = 22.3, uew: float = 1.36) -> ShockResult:
    return ShockResult(
        s10=s10, s20=41.0, g10=21.0, p20=38.0, t20=23.7, s_smh=12.0, s10_vol10=24.1,
        s10_net=21.1, s20_net=39.0, g10_net=20.0, p20_net=36.5, t20_net=22.9, s_smh_net=11.5,
        s10_vol10_net=23.0, uew=uew, unmeasured=("AMD",),
    )  # fmt: skip


def _seed_snapshot(source: str, *, at: datetime, s10: float = 22.3) -> None:
    from src.storage.envelope_state import save_snapshot

    save_snapshot(
        _result(s10),
        source=source,
        enforce="record",
        measured=False,
        s10_limit=23.0,
        uew_limit=1.37,
        t20_limit=None,
        nlv=650_000.0,
        cash_after_itm=-12_345.0,
        reasons=("unmeasured:AMD",),
        captured_at=at,
    )


def test_get_envelope_reads_the_latest_snapshot(client) -> None:
    from src.storage.db import session_scope
    from src.storage.envelope_switches import set_switch
    from src.storage.models import BreadthCountRow, LesSignalRow
    from src.storage.system_settings import set_setting

    now = datetime.now(UTC)
    _seed_snapshot("stored", at=now - timedelta(days=1), s10=19.0)
    _seed_snapshot("stored", at=now - timedelta(minutes=5), s10=22.0)
    _seed_snapshot("live", at=now - timedelta(minutes=4), s10=22.3)
    set_switch("t20_limit", "on", source="cli")
    start = (now - timedelta(days=15)).date()
    set_setting(
        "envelope_glide",
        json.dumps(
            {"start_date": start.isoformat(), "s10_start": 23.0, "uew_start": 1.37,
             "weeks": 13, "s10_target": 15.0, "uew_target": 1.25}
        ),
    )  # fmt: skip
    with session_scope() as s:
        s.add(
            LesSignalRow(
                asof=date(2026, 11, 13), index_symbol="QQQ", trend_up=True, pullback=True,
                washout=False, trend_break=False, tier_pct=3.0, reasons=["pullback: rsi2 3.1"],
            )
        )  # fmt: skip
        s.add(BreadthCountRow(day=date(2026, 11, 13), source="tt", adv=40, dec=60, unch=1,
                              osc=-22.5))  # fmt: skip

    body = client.get("/envelope", headers=OWNER).json()
    snap = body["snapshot"]
    assert snap["source"] == "live" and snap["s10"] == 22.3 and snap["s10_net"] == 21.1
    for key in ("s20", "g10", "p20", "t20", "s_smh", "s10_vol10"):
        assert snap[key] is not None and snap[f"{key}_net"] is not None, key
    assert snap["uew"] == 1.36
    assert snap["unmeasured"] == ["AMD"] and snap["measured"] is False
    assert body["stored"]["s10"] == 22.0 and body["live"]["s10"] == 22.3
    assert body["limits"] == {
        "s10": 23.0, "uew": 1.37, "t20": None, "s10_target": 15.0, "uew_target": 1.25,
    }  # fmt: skip
    assert body["enforce"] == "record"
    assert body["glide"]["week"] == 3 and body["glide"]["weeks"] == 13
    assert body["glide"]["start"] == start.isoformat()
    switches = {s["name"]: s for s in body["switches"]}
    assert switches["t20_limit"]["value"] == "on" and switches["t20_limit"]["source"] == "cli"
    assert switches["envelope_enforce"]["source"] == "default"
    assert body["cash_after_itm_assignment"] == -12_345.0
    (les,) = body["les"]
    assert les["index"] == "QQQ" and les["tier_pct"] == 3.0 and les["breadth_osc"] == -22.5


def test_get_envelope_reads_defaults_in_live(client, monkeypatch) -> None:
    from src.common.config import Config
    from src.storage.envelope_switches import set_switch

    set_switch("envelope_enforce", "on", source="cli")
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    body = client.get("/envelope", headers=OWNER).json()
    assert body["enforce"] == "record"  # live reads every switch's default, as the trader does


def test_get_envelope_needs_the_owner_token(client) -> None:
    assert client.get("/envelope").status_code == 401
    assert client.get("/envelope", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_get_envelope_is_unknown_not_zero_with_no_snapshot(client) -> None:
    body = client.get("/envelope", headers=OWNER).json()
    assert body["snapshot"] is None and body["live"] is None and body["stored"] is None
    assert body["cash_after_itm_assignment"] is None
    assert body["limits"]["s10"] is None and body["limits"]["uew"] is None
    assert body["limits"]["s10_target"] == 15.0
    assert body["glide"] is None and body["les"] == []
    assert len(body["switches"]) == 15


def test_get_envelope_writes_nothing(client) -> None:
    from sqlalchemy import func, select

    from src.storage.db import session_scope
    from src.storage.models import EnvelopeSnapshotRow, SystemSettingRow

    client.get("/envelope", headers=OWNER)
    with session_scope() as s:
        assert s.execute(select(func.count()).select_from(EnvelopeSnapshotRow)).scalar_one() == 0
        keys = set(s.execute(select(SystemSettingRow.key)).scalars())
    assert not {k for k in keys if k.startswith("envelope")}  # no glide, no switch written
