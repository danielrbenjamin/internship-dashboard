import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .catalog import DISCIPLINES

MILESTONES = ("applied", "interview", "offer", "closed")
ROLE_FAMILIES = tuple(
    (name, re.compile(DISCIPLINES[name], re.IGNORECASE))
    for name in ("Robotics", "Aerospace", "Mechanical", "Hardware", "Manufacturing", "Data & AI", "Software")
)


def local_timezone(zone, offset_minutes):
    if zone:
        try:
            return ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return timezone(timedelta(minutes=offset_minutes))


def local_day(timestamp, zone):
    value = datetime.fromisoformat(timestamp)
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(zone).date()


def histories(db, owner):
    rows = db.all("""SELECT a.id,a.status,a.updated_at,a.job_id,j.title,j.company,j.location,j.source
        FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.owner=?""", (owner,))
    events = defaultdict(list)
    for event in db.all("""SELECT application_id,event,at FROM history
        WHERE owner=? AND event LIKE 'Saved as %' ORDER BY id""", (owner,)):
        stage, _, reason = event["event"].removeprefix("Saved as ").partition(" · ")
        track = events[event["application_id"]]
        if reason == "Undid reply outcome":
            if track:
                track.pop()
        else:
            track.append((stage, event["at"]))
    return rows, events


def first_milestones(row, events):
    first = {}
    for stage, stamp in events:
        if stage in MILESTONES:
            first.setdefault(stage, stamp)
    if row["status"] in MILESTONES:
        first.setdefault(row["status"], row["updated_at"])
    return first


def interview_history(db, owner):
    rows, events = histories(db, owner)
    replies = defaultdict(list)
    for reply in db.all("""SELECT id,application_id,subject,created,due,link,done FROM replies
        WHERE owner=? AND kind='Interview' AND application_id<>'' ORDER BY created DESC""", (owner,)):
        replies[reply["application_id"]].append(reply)
    records = []
    for row in rows:
        first = first_milestones(row, events[row["id"]])
        invitations = replies[row["id"]]
        interview = first.get("interview") or (invitations[-1]["created"] if invitations else None)
        if interview:
            records.append({**row, "interviewed_at": interview, "invitations": invitations})
    return sorted(records, key=lambda item: (item["status"] != "offer", -datetime.fromisoformat(
        item["interviewed_at"]
    ).timestamp()))


def application_analytics(db, owner, zone, end, days):
    rows, events = histories(db, owner)
    start = end - timedelta(days=days - 1)
    previous = start - timedelta(days=days)
    interval = 1 if days <= 28 else 7
    buckets = {}
    for index in range(0, days, interval):
        day = start + timedelta(days=index)
        buckets[day] = {"date": day.isoformat(), **dict.fromkeys(MILESTONES, 0), "assessment": 0, "active": 0}
    current, prior = Counter(), Counter()
    families = defaultdict(Counter)
    family_activity = defaultdict(lambda: defaultdict(Counter))
    employers, sources = Counter(), Counter()
    responses = []
    cohort_interviews = cohort_offers = 0

    def activity(metric, day, family):
        if start <= day <= end:
            current[metric] += 1
            bucket = start + timedelta(days=((day - start).days // interval) * interval)
            buckets[bucket][metric] += 1
            families[family][metric] += 1
            family_activity[family][bucket][metric] += 1
        elif previous <= day < start:
            prior[metric] += 1

    family_by_id = {}
    for row in rows:
        track = events[row["id"]]
        milestones = first_milestones(row, track)
        dates = {stage: local_day(stamp, zone) for stage, stamp in milestones.items()}
        family = next((name for name, pattern in ROLE_FAMILIES if pattern.search(row["title"])), "Other")
        family_by_id[row["id"]] = family
        for stage, day in dates.items():
            activity(stage, day, family)
        submission = dates.get("applied")
        if submission and start <= submission <= end:
            employers[row["company"]] += 1
            sources[row["source"]] += 1
            cohort_interviews += "interview" in dates and submission <= dates["interview"] <= end
            cohort_offers += "offer" in dates and submission <= dates["offer"] <= end
            elapsed = [(day - submission).days for stage, day in dates.items()
                       if stage != "applied" and submission <= day <= end]
            if elapsed:
                responses.append(min(elapsed))
        if submission or any(stage in dates for stage in ("interview", "offer")):
            stages = [(local_day(stamp, zone), stage) for stage, stamp in track]
            if not stages:
                stages = [(day, stage) for stage, day in dates.items()]
            index, status = 0, None
            for bucket, values in buckets.items():
                through = min(bucket + timedelta(days=interval - 1), end)
                while index < len(stages) and stages[index][0] <= through:
                    status = stages[index][1]
                    index += 1
                if status in {"applied", "interview", "offer"}:
                    values["active"] += 1
                    family_activity[family][bucket]["active"] += 1

    seen = set()
    for row in db.all("SELECT id,application_id,created FROM replies WHERE owner=? AND kind='Assessment' ORDER BY created",
                      (owner,)):
        key = row["application_id"] or row["id"]
        day = local_day(row["created"], zone)
        if day > end or key in seen:
            continue
        seen.add(key)
        activity("assessment", day, family_by_id.get(row["application_id"], "Unassigned"))

    return {"start": start, "end": end, "interval": interval, "series": list(buckets.values()),
            "current": current, "previous": prior, "pipeline": Counter(row["status"] for row in rows),
            "families": [{"name": name, **counts} for name, counts in sorted(
                families.items(), key=lambda item: (-item[1]["applied"], item[0])
            )],
            "family_series": {name: [{"date": day.isoformat(), **activity.get(day, {})} for day in buckets]
                              for name, activity in sorted(family_activity.items())},
            "employers": employers.most_common(8), "sources": sources.most_common(8),
            "cohort_interviews": cohort_interviews, "cohort_offers": cohort_offers,
            "median_response_days": median(responses) if responses else None}


def ai_analytics(db, owner, zone, end, days):
    start = end - timedelta(days=days - 1)
    interval = 1 if days <= 28 else 7
    series = {start + timedelta(days=i): Counter() for i in range(0, days, interval)}
    totals, kinds = Counter(), defaultdict(Counter)
    for call in db.all("""SELECT kind,status,at,duration_ms,input_tokens,cached_input_tokens,output_tokens
        FROM codex_calls WHERE owner=? AND at>=? AND at<?""",
                       (owner, (start - timedelta(days=1)).isoformat(), (end + timedelta(days=2)).isoformat())):
        day = local_day(call["at"], zone)
        if not start <= day <= end:
            continue
        metrics = Counter({"requests": 1, call["status"]: 1, "duration_ms": call["duration_ms"]})
        if call["input_tokens"] is not None or call["output_tokens"] is not None:
            metrics["reported"] = 1
            for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
                metrics[key] = call[key] or 0
        bucket = start + timedelta(days=(day - start).days // interval * interval)
        series[bucket].update(metrics)
        totals.update(metrics)
        kinds[call["kind"]].update(metrics)
    return {"totals": totals, "kinds": [{"name": key, **value} for key, value in sorted(kinds.items())],
            "series": [{"date": day.isoformat(), **counts} for day, counts in series.items()]}
