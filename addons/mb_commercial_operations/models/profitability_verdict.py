from odoo import models

# Planned volume must clear break-even by this share before an engagement is called
# worth it; anything thinner is one rained-out afternoon away from a loss.
BREAK_EVEN_HEADROOM_RATIO = 0.15

VERDICT_SELECTION = [
    ("unknown", "Not assessable"),
    ("no_go", "Not worth it"),
    ("marginal", "Marginal"),
    ("go", "Worth it"),
]


class MbProfitabilityVerdict(models.AbstractModel):
    """One decision tree for "is this worth doing", shared by markets and depots.

    Only the thresholds live here. Each model words its own note, because a market
    talks in units sold on one day and a depot in turnover over a six-month term,
    and a shared sentence would fit neither. The reason returned alongside the
    verdict is what each model keys its wording on, so the branches cannot drift
    apart from the wording that explains them.
    """

    _name = "mb.profitability.verdict.mixin"
    _description = "Profitability Verdict Rules"

    def _verdict(
        self,
        *,
        blocked,
        judgeable,
        margin,
        below_break_even,
        effort_hours,
        margin_per_hour,
        target_per_hour,
        headroom_ratio,
    ):
        """Return (verdict, reason) from the figures every engagement can produce."""
        if blocked:
            return "unknown", "blocked"
        if not judgeable:
            return "unknown", "not_judgeable"
        if margin <= 0 or below_break_even:
            return "no_go", "below_break_even"
        if effort_hours <= 0:
            return "marginal", "no_hours"
        if target_per_hour and margin_per_hour < target_per_hour:
            return "marginal", "below_target"
        if headroom_ratio < BREAK_EVEN_HEADROOM_RATIO:
            return "marginal", "thin_headroom"
        return "go", "clear"
