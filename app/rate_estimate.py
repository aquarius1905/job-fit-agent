"""判定履歴の単価データから、適正と思われる時給レンジを推定する。"""
from __future__ import annotations

MIN_FIT_SCORE = 70
MIN_SAMPLES = 3
HOURS_PER_MONTH = 160  # 週5日 x 1日8時間 x 4週として概算


def estimate_hourly_rate(
    entries: list[dict], min_fit_score: int = MIN_FIT_SCORE
) -> dict:
    """fit_scoreがmin_fit_score以上、かつ求人票に単価記載がある履歴から時給レンジを推定する。

    自分と近い適合度の案件に絞ることで、推定を実際に応募し得た案件の相場に近づける。
    サンプル数がMIN_SAMPLES未満の場合はavailable=Falseを返す（憶測で数字を出さない）。
    """
    hourly_mins = []
    hourly_maxs = []
    for entry in entries:
        evaluation = entry.get("evaluation") or {}
        if (evaluation.get("fit_score") or 0) < min_fit_score:
            continue
        posted_rate = evaluation.get("posted_rate") or {}
        hourly_min = posted_rate.get("hourly_min")
        hourly_max = posted_rate.get("hourly_max")
        if hourly_min is None or hourly_max is None:
            continue
        hourly_mins.append(hourly_min)
        hourly_maxs.append(hourly_max)

    sample_count = len(hourly_mins)
    if sample_count < MIN_SAMPLES:
        return {"available": False, "sample_count": sample_count}

    hourly_min = round(_median(hourly_mins))
    hourly_max = round(_median(hourly_maxs))
    return {
        "available": True,
        "sample_count": sample_count,
        "hourly_min": hourly_min,
        "hourly_max": hourly_max,
        "monthly_min": round(hourly_min * HOURS_PER_MONTH),
        "monthly_max": round(hourly_max * HOURS_PER_MONTH),
    }


def _median(values: list[float]) -> float:
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
