from fastapi import APIRouter, Depends
from app.core.auth import get_current_user
from app.core.supabase import supabase_admin as supabase
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_period_dates(period: str):
    """Returns (start_date, prev_start_date) for the given period string."""
    now = datetime.now(timezone.utc)
    if period == "7d":
        delta = timedelta(days=7)
    elif period == "30d":
        delta = timedelta(days=30)
    elif period == "90d":
        delta = timedelta(days=90)
    else:
        delta = timedelta(days=7)

    current_start = now - delta
    prev_start = current_start - delta
    return current_start, prev_start, now


def pct_change(current: float, previous: float) -> float:
    """Calculates percentage change between two values."""
    if previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


@router.get("/summary")
async def get_summary(
    business_id: str,
    period: str = "7d",
    current_user: dict = Depends(get_current_user),
):
    current_start, prev_start, now = get_period_dates(period)

    # Current period calls
    current = (
        supabase.table("calls")
        .select("id, status, duration_seconds, sentiment, created_at")
        .eq("business_id", business_id)
        .gte("created_at", current_start.isoformat())
        .execute()
    )

    # Previous period calls (for % change)
    previous = (
        supabase.table("calls")
        .select("id, status, duration_seconds")
        .eq("business_id", business_id)
        .gte("created_at", prev_start.isoformat())
        .lt("created_at", current_start.isoformat())
        .execute()
    )

    curr_calls = current.data or []
    prev_calls = previous.data or []

    # Totals
    total_curr = len(curr_calls)
    total_prev = len(prev_calls)

    # Avg duration
    curr_durations = [c["duration_seconds"] for c in curr_calls if c.get("duration_seconds")]
    prev_durations = [c["duration_seconds"] for c in prev_calls if c.get("duration_seconds")]
    avg_curr = sum(curr_durations) / len(curr_durations) if curr_durations else 0
    avg_prev = sum(prev_durations) / len(prev_durations) if prev_durations else 0

    # Success rate (completed / total)
    curr_completed = len([c for c in curr_calls if c["status"] == "completed"])
    prev_completed = len([c for c in prev_calls if c["status"] == "completed"])
    success_curr = (curr_completed / total_curr * 100) if total_curr else 0
    success_prev = (prev_completed / total_prev * 100) if total_prev else 0

    # Status breakdown
    missed = len([c for c in curr_calls if c["status"] == "missed"])
    forwarded = len([c for c in curr_calls if c["status"] == "forwarded"])

    return {
        "period": period,
        "total_calls": total_curr,
        "total_calls_change_pct": pct_change(total_curr, total_prev),
        "avg_call_duration_seconds": round(avg_curr),
        "avg_duration_change_pct": pct_change(avg_curr, avg_prev),
        "success_rate_pct": round(success_curr, 1),
        "success_rate_change_pct": pct_change(success_curr, success_prev),
        "completed_calls": curr_completed,
        "missed_calls": missed,
        "forwarded_calls": forwarded,
    }


@router.get("/call-volume-trends")
async def call_volume_trends(
    business_id: str,
    period: str = "daily",
    current_user: dict = Depends(get_current_user),
):
    """Returns time-series inbound/outbound data for the chart."""
    now = datetime.now(timezone.utc)

    if period == "daily":
        start = now - timedelta(days=7)
    elif period == "weekly":
        start = now - timedelta(weeks=8)
    else:
        start = now - timedelta(days=90)

    result = (
        supabase.table("calls")
        .select("direction, status, created_at")
        .eq("business_id", business_id)
        .gte("created_at", start.isoformat())
        .execute()
    )

    calls = result.data or []

    # Group by date
    from collections import defaultdict
    buckets = defaultdict(lambda: {"inbound": 0, "outbound": 0})

    for call in calls:
        dt = datetime.fromisoformat(call["created_at"].replace("Z", "+00:00"))
        if period == "daily":
            key = dt.strftime("%a")        # Mon, Tue...
        elif period == "weekly":
            key = dt.strftime("W%W")       # W01, W02...
        else:
            key = dt.strftime("%b")        # Jan, Feb...

        direction = call.get("direction", "inbound")
        buckets[key][direction] += 1

    return {
        "period": period,
        "data": [
            {"label": k, "inbound": v["inbound"], "outbound": v["outbound"]}
            for k, v in sorted(buckets.items())
        ]
    }


@router.get("/call-distribution")
async def call_distribution(
    business_id: str,
    period: str = "7d",
    current_user: dict = Depends(get_current_user),
):
    """Returns breakdown by call status for donut chart."""
    current_start, _, _ = get_period_dates(period)

    result = (
        supabase.table("calls")
        .select("status")
        .eq("business_id", business_id)
        .gte("created_at", current_start.isoformat())
        .execute()
    )

    calls = result.data or []
    from collections import Counter
    counts = Counter(c["status"] for c in calls)
    total = len(calls)

    distribution = []
    for status, count in counts.items():
        distribution.append({
            "status": status,
            "count": count,
            "percentage": round(count / total * 100, 1) if total else 0,
        })

    return {"total": total, "distribution": distribution}
