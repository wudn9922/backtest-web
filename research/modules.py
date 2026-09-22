from dataclasses import dataclass, asdict, replace


@dataclass(frozen=True)
class Modules:
    volume: bool = True
    day2: bool = True
    ma_break: bool = True
    first_tp: bool = True
    protective: bool = True
    bias: bool = True
    atr: bool = True
    first_tp_partial: bool = True

    def __post_init__(self):
        if not self.first_tp and (self.protective or self.bias or self.atr):
            raise ValueError("Protective/Bias/ATR require the First TP regime")

    def as_dict(self):
        return asdict(self)


FULL = Modules()
CORE = Modules(False, False, False, False, False, False, False)
VARIANTS = {
    "ADVANCED_FULL": FULL,
    "ADVANCED_MINUS_VOLUME": replace(FULL, volume=False),
    "ADVANCED_MINUS_DAY2": replace(FULL, day2=False),
    "ADVANCED_MINUS_MA_BREAK": replace(FULL, ma_break=False),
    "ADVANCED_MINUS_FIRST_TP_FAMILY": replace(FULL, first_tp=False, protective=False, bias=False, atr=False),
    "ADVANCED_MINUS_PROTECTIVE_STOP": replace(FULL, protective=False),
    "ADVANCED_MINUS_BIAS_EXTREME": replace(FULL, bias=False),
    "ADVANCED_MINUS_ATR_EXTREME": replace(FULL, atr=False),
    "ADVANCED_MINUS_ALL_EXTREME_TP": replace(FULL, bias=False, atr=False),
}
BRIDGE = {"ADVANCED_CORE": CORE}
_stage = CORE
for _name, _field in [("PLUS_VOLUME", "volume"), ("PLUS_DAY2", "day2"), ("PLUS_MA_BREAK", "ma_break"), ("PLUS_FIRST_TP", "first_tp"), ("PLUS_PROTECTIVE", "protective"), ("PLUS_BIAS", "bias"), ("PLUS_ATR_FULL", "atr")]:
    _stage = replace(_stage, **{_field: True})
    BRIDGE[_name] = _stage
