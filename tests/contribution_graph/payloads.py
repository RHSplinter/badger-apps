"""Builds .contribs replies in the same shape github.com sends.

Dates come from the standard datetime module so the tests do not depend on
the calendar code inside the app.
"""

import datetime

TODAY = datetime.date(2026, 10, 27)          # a Tuesday
FIRST_SUNDAY = datetime.date(2025, 10, 26)   # the Sunday 52 weeks earlier


def level_for(count):
    if count <= 0:
        return 0
    return min(4, 1 + count // 4)


def default_count(index):
    """A spread of counts that includes zeros and a few busy days."""
    return (index * 7 + index // 5) % 13 if index % 3 else 0


def build(first_sunday=FIRST_SUNDAY, weeks=53, last_week_days=3, count_for=default_count,
          first_week_start=0):
    """Return a dict shaped like the .contribs JSON.

    last_week_days is how many days the final week has (1 to 7).
    first_week_start is the weekday (0 = Sunday) the first week begins on.
    """
    week_list = []
    for week in range(weeks):
        sunday = first_sunday + datetime.timedelta(weeks=week)
        start = first_week_start if week == 0 else 0
        stop = last_week_days if week == weeks - 1 else 7
        days = []
        for weekday in range(start, stop):
            count = count_for(week * 7 + weekday)
            days.append({"weekday": weekday, "count": count, "level": level_for(count)})
        first_day = sunday + datetime.timedelta(days=start)
        week_list.append({"index": week, "first_day": first_day.isoformat(), "contribution_days": days})
    last = first_sunday + datetime.timedelta(weeks=weeks - 1, days=last_week_days - 1)
    first = first_sunday + datetime.timedelta(days=first_week_start)
    total = sum(d["count"] for w in week_list for d in w["contribution_days"])
    return {
        "schema": "v2",
        "generated_at": last.isoformat() + "T22:15:01Z",
        "from": first.isoformat(),
        "to": last.isoformat(),
        "range_days": (last - first).days + 1,
        "total_contributions": total,
        "private_contributions_included": True,
        "colors_full": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "weeks": week_list,
        "months": [{"month": "2025-10", "total_weeks": 1}],
    }


def flat_counts(payload):
    """Every day's count in date order."""
    return [d["count"] for w in payload["weeks"] for d in w["contribution_days"]]
