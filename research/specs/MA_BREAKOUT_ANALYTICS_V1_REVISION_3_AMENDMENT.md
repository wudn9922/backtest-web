【模型】

模式：
Sol High — MA_BREAKOUT_ANALYTICS_V1 SPEC AMENDMENT REVIEW

Gemini：
不用

Grok：
不用

目前 Master Specification Revision 2
整體接受，

但 implementation 前
修正以下三項。

不要改 code。
不要 implementation。

==================================================
AMENDMENT 1 — SIDEWAYS ≠ ENTANGLEMENT
==================================================

目前規格將 SIDEWAYS
直接定義為：

MA_BOX_LONG_V1 Rev3
VisualBox / entanglement。

這會過度限縮 sideways。

使用者的：

「橫盤整理」

不要求價格一定：

圍繞 MA

穿越 MA

或 Close 在 MA 兩側切換。

例如價格：

在 MA 上方
形成明顯窄幅水平整理

也應可以是 SIDEWAYS。

因此：

ENTANGLEMENT

與：

SIDEWAYS

正式拆開。

--------------------------------------------------
ENTANGLEMENT
--------------------------------------------------

繼續 reuse：

MA_BOX_LONG_V1 Rev3
causal entanglement / box semantics。

只用於：

ALL

EXCLUDE_ENTANGLED

ONLY_ENTANGLED

SPLIT_ENTANGLED_CLEAN

cohort filter。

不得當作 SIDEWAYS
唯一判定方式。

--------------------------------------------------
SIDEWAYS
--------------------------------------------------

請 Sol 比較並 freeze
獨立 causal price-consolidation rule。

至少比較：

Minimum confirmation structure：

4 completed bars

vs

5 completed bars

以及：

Rolling range：

max(High)-min(Low)

normalized by ATR14。

Candidate thresholds：

<=1.0 ATR

<=1.5 ATR

<=2.0 ATR。

ATR snapshot / rolling ATR
也必須明確 freeze。

重點：

這裡的4/5 bars
只是 SIDEWAYS minimum confirmation，

不是：

maximum follow-up horizon。

Day2 failure仍然：

沒有固定 observation timeout。

--------------------------------------------------
SIDEWAYS REQUIREMENT
--------------------------------------------------

SIDEWAYS 可以：

發生於 MA 上方

靠近 MA

或其他尚未觸發：

Return
Retest
Trend Away

的價格區域。

不要要求：

K線一定穿 MA。

==================================================
AMENDMENT 2 — TREND CONTINUATION MUST SHOW NEW ADVANCE
==================================================

目前：

Long:

Close(u) >= MA(u)*1.002

Short:

Close(u) <= MA(u)*0.998

過度寬鬆。

因為 Day2 failure後：

價格可能仍在 MA+0.2%以上

但其實持續下跌。

這不能叫：

明確脫離均線／繼續上漲。

V1 修改為：

Long TREND_CONTINUATION_AWAY：

Close(u) >= MA(u)*1.002

AND

Close(u) > Close(D1)。

Short mirror：

Close(u) <= MA(u)*0.998

AND

Close(u) < Close(D1)。

也就是：

除了在 clear side，

還必須重新超越
原 Day1 completed Close。

請 Sol確認：

這是否為最簡潔、
causal 且符合人工語意的定義。

如 Sol認為更合理的是：

突破 Day1 High/Low

或：

distance-from-MA expansion

請比較後 freeze，

但不得只保留：

MA±0.2%

單一條件。

==================================================
AMENDMENT 3 — CONDITION-AWARE TARGET OBSERVATION ORIGIN
==================================================

Reference Entry維持：

Long:

MA(D1-1)*1.01

Short:

MA(D1-1)*0.99。

Reference Entry仍只是：

統計基準進場價。

不是actual execution。

--------------------------------------------------
BREAKOUT / VOLUME CONDITIONS
--------------------------------------------------

D1 close後已知的條件：

Breakout

Volume >=10%

Volume >=20%

Volume >=30%

Target-vs-stop observation：

從：

D2 Open

開始。

--------------------------------------------------
DAY2-CONDITIONED ANALYTICS
--------------------------------------------------

下列條件：

Day2 success

Day2 + Volume>=10%

Day2 + Volume>=20%

Day2 + Volume>=30%

只有：

D2 completed close後

才知道成立。

因此使用者要求：

「二日法則成立後」
的 target analytics

從：

D3 Open

開始觀察。

Reference price
仍然使用：

MA(D1-1)×1.01 / 0.99。

Dynamic stop：

D3開始使用
當日 canonical previous-day MA stop。

--------------------------------------------------
DO NOT BACKFILL
--------------------------------------------------

Day2-conditioned target result：

不得使用：

D2 intraday High/Low

去判：

target first
或 stop first。

因為當時
Day2 success尚未確認。

==================================================
OUTPUT
==================================================

請只輸出：

1.

Revised Sideways definition

2.

Sideways parameter comparison
and frozen choice

3.

Revised Trend Continuation definition

4.

Condition-aware target observation origins

5.

受影響 event schema

6.

受影響 aggregate schema

7.

受影響 test matrix

8.

是否仍有 ambiguity

若沒有：

輸出：

MA_BREAKOUT_ANALYTICS_V1
SPEC AMENDMENT ACCEPTED

MA_BREAKOUT_ANALYTICS_V1
SPEC FROZEN REVISION 3

不要 implementation。
