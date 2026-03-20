# -*- coding: utf-8 -*-
"""
WebUIで保存した監視リスト（watch_selections.json）を定期的にチェックし、
該当プランが見つかった場合に LINE / メール通知します。
"""

import datetime
import os
import time
import re

from config import get_rakuten_credentials, get_notify_settings
from notify import notify_availability
from vacancy_check import run_vacancy_check_date_range
from watch_storage import load_watch_state, watch_entry_key, save_watch_state


def _normalize_str(v):
    return str(v or "").strip()


def _entry_match_key(entry, hotel_no_fallback=""):
    # entries 側の部屋識別は、表示用の roomName より roomClass（コード）の方が安定する
    plan_id = _normalize_str(entry.get("planId"))
    meal_text = _normalize_str(entry.get("mealText"))
    # roomClass は日付で変動し得るため、暫定的に planId + mealText のみで判定する
    return (plan_id, meal_text)


def _is_rate_limit_error(err):
    s = str(err or "")
    return ("429" in s) or ("Rate limit" in s) or ("リクエストが多すぎ" in s) or ("Try again in" in s)


def _extract_retry_after_seconds(err, default=1.0):
    s = str(err or "")
    m = re.search(r"Try again in\s*(\d+(?:\.\d+)?)\s*seconds", s, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return float(default)


def _parse_iso_datetime(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def _cooldown_eligible(last_notified_iso, cooldown_hours, now):
    if not last_notified_iso:
        return True
    dt = _parse_iso_datetime(last_notified_iso)
    if not dt:
        return True
    return (now - dt).total_seconds() >= float(cooldown_hours) * 3600


def _date_range_search_with_fallback(application_id, access_key, hotel_no, search, occupancy, max_plans_per_date, max_plans_total, sleep_between_requests_sec, max_retries_per_date):
    today = datetime.date.today()

    primary_start = today + datetime.timedelta(days=int(search.get("primaryStartOffsetDays") or 75))
    primary_end = today + datetime.timedelta(days=int(search.get("primaryEndOffsetDays") or 90))
    fallback_start = today + datetime.timedelta(days=int(search.get("fallbackStartOffsetDays") or 60))
    fallback_end = today + datetime.timedelta(days=int(search.get("fallbackEndOffsetDays") or 90))

    stay_nights = int(search.get("stay_nights") or 1)

    def call(weekdays_only, sd, ed):
        return run_vacancy_check_date_range(
            application_id=application_id,
            access_key=access_key,
            hotel_no=hotel_no,
            start_date=sd.strftime("%Y-%m-%d"),
            end_date=ed.strftime("%Y-%m-%d"),
            stay_nights=stay_nights,
            adult_num=occupancy["adult_num"],
            up_class_num=occupancy["up_class_num"],
            low_class_num=occupancy["low_class_num"],
            infant_with_mb_num=occupancy["infant_with_mb_num"],
            infant_with_m_num=occupancy["infant_with_m_num"],
            infant_with_b_num=occupancy["infant_with_b_num"],
            infant_without_mb_num=occupancy["infant_without_mb_num"],
            room_num=occupancy["room_num"],
            plan_keyword=None,
            weekdays_only=weekdays_only,
            max_plans_per_date=max_plans_per_date,
            max_plans_total=max_plans_total,
            sleep_between_requests_sec=sleep_between_requests_sec,
            max_retries_per_date=max_retries_per_date,
        )

    r = call(True, primary_start, primary_end)
    if (not (r.get("plans") or [])) and r.get("ok"):
        r = call(False, fallback_start, fallback_end)
        return r, fallback_start, fallback_end
    return r, primary_start, primary_end


def main():
    cred = get_rakuten_credentials()
    notify = get_notify_settings()
    if not cred["application_id"] or not cred["access_key"]:
        raise SystemExit(".env に RAKUTEN_APPLICATION_ID と RAKUTEN_ACCESS_KEY を設定してください。")

    cooldown_hours = float(os.environ.get("WATCH_NOTIFY_COOLDOWN_HOURS", "24"))

    # API 負荷を制御する上限（WebUIより保守的に）
    max_plans_per_date = int(os.environ.get("WATCH_MAX_PLANS_PER_DATE", "10"))
    max_plans_total = int(os.environ.get("WATCH_MAX_PLANS_TOTAL", "120"))
    sleep_between_requests_sec = float(os.environ.get("WATCH_SLEEP_BETWEEN_REQUESTS_SEC", "0.8"))
    max_retries_per_date = int(os.environ.get("WATCH_MAX_RETRIES_PER_DATE", "2"))

    state = load_watch_state()
    records = state.get("records") or []
    if not records:
        print("watch_main: 監視リストが空です。")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    changed = False

    for rec in records:
        search = rec.get("search") or {}
        hotel_no = str(search.get("hotel_no") or "")
        if not hotel_no:
            continue

        preferred_raw = str(search.get("preferred_checkin_dates") or "").strip()
        preferred_dates = []
        if preferred_raw:
            # "YYYY-MM-DD,YYYY-MM-DD" を想定
            for part in preferred_raw.split(","):
                s = (part or "").strip()
                if not s:
                    continue
                preferred_dates.append(s)

        occupancy = {
            "adult_num": int(search.get("adult_num") or 2),
            "room_num": int(search.get("room_num") or 1),
            "up_class_num": int(search.get("up_class_num") or 0),
            "low_class_num": int(search.get("low_class_num") or 0),
            "infant_with_mb_num": int(search.get("infant_with_mb_num") or 0),
            "infant_with_m_num": int(search.get("infant_with_m_num") or 0),
            "infant_with_b_num": int(search.get("infant_with_b_num") or 0),
            "infant_without_mb_num": int(search.get("infant_without_mb_num") or 0),
        }

        entries = rec.get("entries") or {}
        if not entries:
            continue

        def check_once_for_checkin(ci_str):
            # ci_str: YYYY-MM-DD
            try:
                ci = datetime.datetime.strptime(ci_str, "%Y-%m-%d").date()
            except ValueError:
                return {"ok": True, "plans": [], "sd_used": None, "ed_used": None}

            stay_nights = int(search.get("stay_nights") or 1)
            co = (ci + datetime.timedelta(days=stay_nights)).strftime("%Y-%m-%d")
            r = run_vacancy_check_date_range(
                application_id=cred["application_id"],
                access_key=cred["access_key"],
                hotel_no=hotel_no,
                start_date=ci.strftime("%Y-%m-%d"),
                end_date=ci.strftime("%Y-%m-%d"),
                stay_nights=stay_nights,
                adult_num=occupancy["adult_num"],
                up_class_num=occupancy["up_class_num"],
                low_class_num=occupancy["low_class_num"],
                infant_with_mb_num=occupancy["infant_with_mb_num"],
                infant_with_m_num=occupancy["infant_with_m_num"],
                infant_with_b_num=occupancy["infant_with_b_num"],
                infant_without_mb_num=occupancy["infant_without_mb_num"],
                room_num=occupancy["room_num"],
                plan_keyword=None,
                weekdays_only=False,
                max_plans_per_date=max_plans_per_date,
                max_plans_total=max_plans_total,
                sleep_between_requests_sec=sleep_between_requests_sec,
                max_retries_per_date=max_retries_per_date,
            )
            return r

        if preferred_dates:
            # 希望日指定の場合は、その日付に絞って判定する
            for ci_str in preferred_dates:
                r = None
                last_err = None
                # 429 の追加リトライ（run_vacancy_check_date_range の内部 retry より保険）
                outer_retries = int(os.environ.get("WATCH_OUTER_RETRIES", "3"))
                for _ in range(outer_retries):
                    r = check_once_for_checkin(ci_str)
                    if r.get("ok"):
                        last_err = None
                        break
                    last_err = r.get("error")
                    if not _is_rate_limit_error(last_err):
                        break
                    wait_sec = _extract_retry_after_seconds(last_err, default=1.0)
                    time.sleep(max(0.5, wait_sec))

                if not r or not r.get("ok"):
                    print(f"watch_main: API error hotel_no={hotel_no} date={ci_str} err={last_err}")
                    continue

                found_plans = r.get("plans") or []
                found_index = {}
                for p in found_plans:
                    k = (
                        _normalize_str(p.get("planId")),
                        _normalize_str(p.get("mealText")),
                    )
                    if k not in found_index:
                        found_index[k] = p

                eligible_keys = []
                # まず found_index に一致する entries を拾う
                for entry_key, entry in (entries or {}).items():
                    mk = _entry_match_key(entry)
                    if mk not in found_index:
                        continue
                    last_notified = (entry.get("state") or {}).get("last_notified_at")
                    if _cooldown_eligible(last_notified, cooldown_hours=cooldown_hours, now=now):
                        eligible_keys.append(entry_key)

                # 見つかった（ただし通知は cooldown で制御）
                if eligible_keys:
                    for entry_key in eligible_keys:
                        entry = entries.get(entry_key) or {}
                        entry.setdefault("state", {})
                        if entry["state"].get("last_found_at") != now_iso:
                            entry["state"]["last_found_at"] = now_iso
                            changed = True
                else:
                    # eligible_keys が無くても見つかっていた可能性はあるので last_found_at は更新する
                    for entry_key, entry in (entries or {}).items():
                        mk = _entry_match_key(entry)
                        if mk in found_index:
                            entry.setdefault("state", {})
                            if entry["state"].get("last_found_at") != now_iso:
                                entry["state"]["last_found_at"] = now_iso
                                changed = True

                if not eligible_keys:
                    continue

                eligible_plans = [found_index[_entry_match_key(entries.get(k) or {})] for k in eligible_keys]
                eligible_plans.sort(key=lambda p: (p.get("planName") or "", p.get("roomName") or "", p.get("charge") or 0))
                eligible_plans = eligible_plans[:10]

                hotel_name = eligible_plans[0].get("hotelName", "（施設名不明）") if eligible_plans else "（施設名不明）"
                plan_list_url = eligible_plans[0].get("planListUrl", "") if eligible_plans else ""

                stay_nights = int(search.get("stay_nights") or 1)
                try:
                    ci = datetime.datetime.strptime(ci_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                co_date = ci + datetime.timedelta(days=stay_nights)

                ok = notify_availability(
                    notify,
                    hotel_name=hotel_name,
                    checkin=ci.strftime("%Y-%m-%d"),
                    checkout=co_date.strftime("%Y-%m-%d"),
                    plans_list=eligible_plans,
                    plan_list_url=plan_list_url,
                )

                if ok:
                    for k in eligible_keys:
                        entry = entries.get(k) or {}
                        entry.setdefault("state", {})
                        entry["state"]["last_notified_at"] = now_iso
                    changed = True
        else:
            r, sd_used, ed_used = _date_range_search_with_fallback(
                application_id=cred["application_id"],
                access_key=cred["access_key"],
                hotel_no=hotel_no,
                search=search,
                occupancy=occupancy,
                max_plans_per_date=max_plans_per_date,
                max_plans_total=max_plans_total,
                sleep_between_requests_sec=sleep_between_requests_sec,
                max_retries_per_date=max_retries_per_date,
            )

            if not r.get("ok"):
                print(f"watch_main: API error hotel_no={hotel_no} err={r.get('error')}")
                continue

            found_plans = r.get("plans") or []
            found_index = {}
            for p in found_plans:
                k = (
                    _normalize_str(p.get("planId")),
                    _normalize_str(p.get("mealText")),
                )
                if k not in found_index:
                    found_index[k] = p

            found_keys = []
            for entry_key, entry in (entries or {}).items():
                mk = _entry_match_key(entry)
                if mk in found_index:
                    found_keys.append(entry_key)

            eligible_keys = []
            for k in found_keys:
                entry = entries.get(k) or {}
                last_notified = (entry.get("state") or {}).get("last_notified_at")
                if _cooldown_eligible(last_notified, cooldown_hours=cooldown_hours, now=now):
                    eligible_keys.append(k)

            # 見つかった（通知前）だけ last_found_at を更新
            for k in found_keys:
                entry = entries.get(k) or {}
                entry.setdefault("state", {})
                if entry["state"].get("last_found_at") != now_iso:
                    entry["state"]["last_found_at"] = now_iso
                    changed = True

            if not eligible_keys:
                continue

            eligible_plans = [found_index[_entry_match_key(entries.get(k) or {})] for k in eligible_keys]
            eligible_plans.sort(key=lambda p: (p.get("planName") or "", p.get("roomName") or "", p.get("charge") or 0))
            eligible_plans = eligible_plans[:10]

            hotel_name = eligible_plans[0].get("hotelName", "（施設名不明）") if eligible_plans else "（施設名不明）"
            plan_list_url = eligible_plans[0].get("planListUrl", "") if eligible_plans else ""

            stay_nights = int(search.get("stay_nights") or 1)
            checkin_label = f"{sd_used.strftime('%Y-%m-%d')} 〜 {ed_used.strftime('%Y-%m-%d')}"
            checkout_label = f"{(sd_used + datetime.timedelta(days=stay_nights)).strftime('%Y-%m-%d')} 〜 {(ed_used + datetime.timedelta(days=stay_nights)).strftime('%Y-%m-%d')}"

            ok = notify_availability(
                notify,
                hotel_name=hotel_name,
                checkin=checkin_label,
                checkout=checkout_label,
                plans_list=eligible_plans,
                plan_list_url=plan_list_url,
            )

            if ok:
                for k in eligible_keys:
                    entry = entries.get(k) or {}
                    entry.setdefault("state", {})
                    entry["state"]["last_notified_at"] = now_iso
                changed = True

        time.sleep(0.1)

    if changed:
        save_watch_state(state)
        print("watch_main: watch_selections.json を更新しました。")
    else:
        print("watch_main: 更新なし。")


if __name__ == "__main__":
    main()

