"""Read-only OHLC identifiability classification, separate from execution policy.

Never changes a fill. Engine flags and genuine uncertainty are separate fields.
Daily timestamps are bar identifiers, NOT known intraday execution times.
"""
from __future__ import annotations

ENTRY = "ENTRY_THEN_STOP_AMBIGUITY"
TP_STOP = "TP_VS_STOP_AMBIGUITY"
MULTI = "MULTI_THRESHOLD_AMBIGUITY"
NONE = "NON_AMBIGUOUS"


def classify(row, parameters, modules, simple=False):
    o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
    ma = row["reference_ma"]
    upper = ma + ma * parameters.entry_stop_pct / 100
    buy = next((e for e in row["executions"] if e["side"] == "BUY"), None)
    s = row["state_open"] if row["quantity_open"] else {}
    p0 = s.get("entry_price") or (buy["price"] if buy else None)
    flagged = [e for e in row["events"] if e["event"] == "DAILY_INTRABAR_AMBIGUITY"]
    result = {"date": row["date"], "ohlc": {k: row[k] for k in ("open", "high", "low", "close")},
              "quantity_open": row["quantity_open"], "quantity_close": row["quantity_close"],
              "entry_threshold": upper, "stop_threshold": None, "conditions": [], "classes": [],
              "evidence": [], "engine_flagged": bool(flagged), "engine_flags": flagged,
              "entry_stop_candidate": False}
    if not row["quantity_open"] and not buy:
        result["evidence"].append("No position; opening gap above UpperEntry is never an entry in v2." if o > upper else "No completed entry.")
    elif s.get("pending_next_open_exit_reason"):
        result["evidence"].append("Scheduled exit executes at OPEN before any range conditions.")
    else:
        risks = []
        first_active = bool(s.get("first_tp_triggered"))
        if simple:
            risks.append(("MA_EXIT", ma * (1 - parameters.exit_below_ma_pct / 100), False))
        elif first_active:
            if modules.protective:
                risks.append(("PROTECTIVE_STOP", max(p0, ma * (1 - parameters.ma_risk_pct / 100)), False))
        elif modules.ma_break:
            if s.get("break_day_low") is not None and str(s.get("break_day")) != row["date"]:
                risks.append(("BREAK_DAY_LOW", s["break_day_low"], True))
            elif s.get("break_day_low") is None:
                risks.append(("MA_HALF_STOP", ma * (1 - parameters.ma_risk_pct / 100), False))
        risks = [(name, level, strict) for name, level, strict in risks if l < level or (not strict and l <= level)]
        profits = []
        first = p0 * (1 + parameters.first_tp_pct / 100) if p0 else None
        first_hit = not simple and modules.first_tp and not first_active and h >= first
        if first_hit:
            profits.append(("FIRST_TP", first))
        if not simple and (first_active or first_hit) and s.get("extreme_tp_count", 0) < parameters.max_extreme_tp_count:
            q = row["quantity_open"] or (buy["quantity"] if buy else 0)
            q0 = s.get("q0") or q
            if q0 and q / q0 >= parameters.minimum_position_pct_q0 / 100:
                bias = ma * (1 + parameters.bias_sigma_multiple * row["bias_sigma"])
                atr = ma + parameters.atr_multiple * row["reference_atr"]
                for name, enabled, active, level in [("BIAS_EXTREME", modules.bias, s.get("bias_extreme_active"), bias), ("ATR_EXTREME", modules.atr, s.get("atr_extreme_active"), atr)]:
                    if enabled and not active and h >= level:
                        profits.append((name, level))
        for name, level, _ in risks:
            result["conditions"].append({"name": name, "level": level, "activation": "post-entry" if buy else "open"})
        for name, level in profits:
            result["conditions"].append({"name": name, "level": level, "activation": "first-tp-dependent" if "EXTREME" in name and first_hit else "active"})
        if buy and risks:
            name, stop, strict = risks[0]
            result["stop_threshold"] = stop
            result["entry_stop_candidate"] = o < upper and h >= upper and l <= stop
            if o >= upper - max(abs(upper), 1) * 1e-12:
                result["evidence"].append("Entry is at OPEN: all subsequent lows are post-entry; no entry-order ambiguity.")
            elif c < stop or (not strict and c <= stop):
                result["evidence"].append("Close is through the stop: after reaching Entry the price must cross the stop again, even if Low was earlier.")
            else:
                result["classes"].append(ENTRY)
                result["evidence"].append("O<Entry, H>=Entry, L<=Stop, C>Stop: both low-before-entry and entry-before-low continuous paths fit OHLC. O<Entry alone proves neither.")
        for name, stop, strict in risks:
            for favorable, target in profits:
                # Extreme thresholds below a new First TP cannot precede its activation.
                effective_target = max(target, first) if first_hit and "EXTREME" in favorable else target
                if row["quantity_open"] and (o < stop or (not strict and o <= stop)):
                    result["evidence"].append(f"{name} is already hit at OPEN; range TP cannot precede that opening stop.")
                elif row["quantity_open"] and o >= effective_target and (first_active or favorable == "FIRST_TP"):
                    result["evidence"].append(f"{favorable} is already hit at OPEN; this pair is not an unknown high/low ordering.")
                elif l <= stop < effective_target <= h:
                    result["classes"].append(TP_STOP)
                    result["evidence"].append(f"Both {favorable}-before-{name} and {name}-before-{favorable} paths are feasible; regime/quantity can differ.")
        if first_hit and modules.protective:
            stop = max(p0, ma * (1 - parameters.ma_risk_pct / 100))
            if l <= stop:
                result["conditions"].append({"name": "NEW_PROTECTIVE_STOP", "level": stop, "activation": "after-first-tp"})
                if o >= first:
                    result["evidence"].append("First TP signal is known at OPEN, so its new protective level is active before later Low.")
                elif c <= stop:
                    result["evidence"].append("High guarantees First TP reach; Close through new protective guarantees a later protective crossing. Activation order is identifiable.")
                else:
                    result["classes"].append(TP_STOP)
                    result["evidence"].append("Low may precede First TP activation or follow it; Close above protective does not force a later stop. Both feasible paths exist.")
        result["classes"] = list(dict.fromkeys(result["classes"]))
        if result["classes"] and len({x["name"] for x in result["conditions"]}) >= 3:
            result["classes"].append(MULTI)
    if not result["classes"]:
        result["classes"] = [NONE]
    result["genuine"] = result["classes"] != [NONE]
    return result


def inspect(result, parameters, modules, simple=False):
    days = []
    for row in result["timeline"]:
        if not row["quantity_open"] and not row["executions"]:
            continue
        item = classify(row, parameters, modules, simple)
        pos = next((p for p in result["positions"] if p["entry_date"][:10] <= row["date"] <= p["final_exit_date"][:10]), None)
        item["position_id"] = pos["position_id"] if pos else None
        days.append(item)
    genuine = [d for d in days if d["genuine"]]
    return {"ambiguous_days": len(genuine), "ambiguous_positions": len({d["position_id"] for d in genuine}),
            "engine_flagged_days": sum(d["engine_flagged"] for d in days),
            "flagged_but_identifiable_days": [d for d in days if d["engine_flagged"] and not d["genuine"]],
            "days": days}
