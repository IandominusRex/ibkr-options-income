# Private config and prompt text the record quotes, as at the boundary

Source: config/risk_limits.yaml and config/settings.yaml (the operator's private copies, git-ignored; both last modified 2026-11-18 20:23-20:24 local = 12:23-12:24Z, before the liquidation, so they read as they did at the boundary), and `git show 4121b2d:src/claude/prompts/strategist.py`. Only the quoted keys are copied; nothing else from those files.
Supports: README section 8 L5 (envelope keys), L12 (the calibration warning), section 10 (breakers, delta band, DTE band, large-position slots), section 7 (the 'Default to sell' rubric).

## config/risk_limits.yaml lines 65-67 (envelope)
```yaml
  s10_target_pct: 15.0          # where the S10 limit ends, % of NLV at SPY -10% (E4)
  uew_target: 1.25              # where the U_ew limit ends, x NLV (E5)
  glide_weeks: 13               # weekly linear steps from the start level to the targets
```

## config/risk_limits.yaml lines 212-217 (concentration limits and the calibration warning)
```yaml
  # 2. Concentration, in risk units. CALIBRATION WARNING: these values are NOT comparable to
  #    the old collateral-based percentages. Risk units are collateral scaled by
  #    IV x sqrt(DTE/365) (typically 0.05-0.30), so 5.0 here is far more permissive than 5.0
  #    was before. Re-derive with `python -m scripts.capacity_report` before trusting them.
  max_risk_units_per_ticker_pct: 5.0
  max_risk_units_per_sector_pct: 25.0
```

## config/risk_limits.yaml lines 6-10 and 17-21 (delta and DTE bands, CSP and CC)
```yaml
covered_call:
  delta_min: 0.20
  delta_max: 0.35
  dte_min: 7
  dte_max: 28
  ...
cash_secured_put:
  delta_min: 0.20
  delta_max: 0.35
  dte_min: 7
  dte_max: 28
```

## config/risk_limits.yaml line 232 (large-position slots)
```yaml
  max_large_positions: 2
```

## config/settings.yaml lines 414-419 (breakers)
```yaml
  # Mark-to-market, not fill cashflow. See config.py AutomationCfg.
  daily_loss_halt_pct: 3.0
  # Drawdown from the highest net liq of the last N sessions (rolling; NOT an all-time peak, so a
  # standing drawdown does not re-halt every morning). The 3% daily line above covers one bad day.
  drawdown_halt_pct: 6.0
  drawdown_window_days: 3
```

## src/claude/prompts/strategist.py at 4121b2d, lines 712-716 (the rubric when every candidate already passed the gate)
```python
    else:
        rubric_intro = [
            "Every candidate below already PASSED the deterministic Rules Engine (F7). Default "
            'to "sell"',
            "unless you can cite a specific FACT (F#) or NEWS item (N#) that argues otherwise:",
```
