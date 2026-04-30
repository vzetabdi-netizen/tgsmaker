"""
Plans Module
Defines Free and Pro plan limits, pricing, and Telegram Stars integration.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    name: str           # display name
    plan_id: str        # internal key: 'free' | 'pro'
    daily_limit: int    # max conversions per day  (-1 = unlimited)
    batch_limit: int    # max files per batch
    price_stars: int    # Telegram Stars price per month (0 = free)
    emoji: str


FREE_PLAN = Plan(
    name        = "Free",
    plan_id     = "free",
    daily_limit = 5,
    batch_limit = 5,
    price_stars = 0,
    emoji       = "🆓",
)

PRO_PLAN = Plan(
    name        = "Pro",
    plan_id     = "pro",
    daily_limit = -1,       # unlimited
    batch_limit = 15,
    price_stars = 150,      # 150 Telegram Stars / month
    emoji       = "⭐",
)

ALL_PLANS: dict[str, Plan] = {
    FREE_PLAN.plan_id: FREE_PLAN,
    PRO_PLAN.plan_id:  PRO_PLAN,
}


def get_plan(plan_id: str) -> Plan:
    """Return Plan object for the given plan_id, defaulting to Free."""
    return ALL_PLANS.get(plan_id, FREE_PLAN)


# ---------------------------------------------------------------------------
# Upgrade message helpers
# ---------------------------------------------------------------------------

def format_plan_card(plan: Plan) -> str:
    limit_str = "Unlimited" if plan.daily_limit == -1 else str(plan.daily_limit)
    price_str = f"{plan.price_stars} ⭐ Stars/month" if plan.price_stars > 0 else "Free"
    return (
        f"{plan.emoji} <b>{plan.name} Plan</b>\n"
        f"   • Daily conversions : {limit_str}\n"
        f"   • Batch size        : up to {plan.batch_limit} files\n"
        f"   • Price             : {price_str}"
    )


def format_upgrade_message(current_plan: Plan) -> str:
    lines = [
        "💎 <b>Upgrade to Pro</b>\n",
        format_plan_card(FREE_PLAN),
        "",
        format_plan_card(PRO_PLAN),
        "",
        f"👉 Pro costs only <b>{PRO_PLAN.price_stars} Telegram Stars</b> per month.",
        "Stars are bought directly inside Telegram — no credit card needed.",
        "",
        "Tap /upgrade to pay and activate Pro instantly.",
    ]
    if current_plan.plan_id == "pro":
        lines = ["✅ You are already on the <b>Pro</b> plan! Enjoy unlimited conversions."]
    return "\n".join(lines)
