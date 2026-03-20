# -*- coding: utf-8 -*-
"""
空室検索の共通処理（CLI / Web UI から利用）
"""
import os

from rakuten_api import parse_vacant_results, search_vacant_hotels


def run_vacancy_check(
    application_id,
    access_key,
    hotel_no,
    checkin_date,
    checkout_date,
    adult_num=2,
    up_class_num=0,
    low_class_num=0,
    infant_with_mb_num=0,
    infant_with_m_num=0,
    infant_with_b_num=0,
    infant_without_mb_num=0,
    room_num=1,
    plan_keyword=None,
    max_charge=None,
    search_pattern=1,
    max_plans=None,
    log_callback=None,
):
    """
    空室検索を実行し、結果を dict で返す。
    戻り値: ok, error, plans
    """
    if max_plans is None:
        max_plans_raw = os.environ.get("VACANCY_MAX_PLANS", "100")
        try:
            max_plans = int(max_plans_raw)
        except ValueError:
            max_plans = 30

    max_plans = max(1, int(max_plans))

    kw = (plan_keyword or "").strip() or None
    hits_per_page = 30  # VacantHotelSearch は hits 上限が 30

    all_plans = []

    def _log(msg):
        if callable(log_callback):
            try:
                log_callback(str(msg))
            except Exception:
                pass

    _log(f"vacancy_check: checkin={checkin_date} checkout={checkout_date} hits={hits_per_page}")

    # まず 1 ページ目を取り、pageCount を見て以降を取得する
    _log("  fetch page=1")
    ok, data, err = search_vacant_hotels(
        application_id=application_id,
        access_key=access_key,
        hotel_no=hotel_no,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adult_num=adult_num,
        up_class_num=up_class_num,
        low_class_num=low_class_num,
        infant_with_mb_num=infant_with_mb_num,
        infant_with_m_num=infant_with_m_num,
        infant_with_b_num=infant_with_b_num,
        infant_without_mb_num=infant_without_mb_num,
        room_num=room_num,
        max_charge=max_charge,
        search_pattern=search_pattern,
        hits=hits_per_page,
        page=1,
    )
    if not ok:
        return {"ok": False, "error": err, "plans": []}

    if not data:
        return {"ok": True, "error": None, "plans": []}

    paging = data.get("pagingInfo") or {}
    page_count = int(paging.get("pageCount") or 1)

    all_plans.extend(parse_vacant_results(data, plan_keyword=kw))
    _log(f"  page=1 done. pageCount={page_count} merged_plans={len(all_plans)}")

    # 残りページを順に取り切る（max_plans に到達したら打ち切る）
    for page in range(2, page_count + 1):
        if len(all_plans) >= max_plans:
            break

        _log(f"  fetch page={page}")
        before = len(all_plans)
        ok, data, err = search_vacant_hotels(
            application_id=application_id,
            access_key=access_key,
            hotel_no=hotel_no,
            checkin_date=checkin_date,
            checkout_date=checkout_date,
            adult_num=adult_num,
            up_class_num=up_class_num,
            low_class_num=low_class_num,
            infant_with_mb_num=infant_with_mb_num,
            infant_with_m_num=infant_with_m_num,
            infant_with_b_num=infant_with_b_num,
            infant_without_mb_num=infant_without_mb_num,
            room_num=room_num,
            max_charge=max_charge,
            search_pattern=search_pattern,
            hits=hits_per_page,
            page=page,
        )
        if not ok:
            return {"ok": False, "error": err, "plans": []}

        if not data:
            break

        all_plans.extend(parse_vacant_results(data, plan_keyword=kw))
        _log(f"  page={page} done. +{len(all_plans)-before} merged_plans={len(all_plans)}")

    all_plans = all_plans[:max_plans]
    return {"ok": True, "error": None, "plans": all_plans}


def run_vacancy_check_date_range(
    application_id,
    access_key,
    hotel_no,
    start_date,
    end_date,
    stay_nights,
    adult_num=2,
    up_class_num=0,
    low_class_num=0,
    infant_with_mb_num=0,
    infant_with_m_num=0,
    infant_with_b_num=0,
    infant_without_mb_num=0,
    room_num=1,
    plan_keyword=None,
    max_plans_per_date=100,
    max_plans_total=200,
    search_pattern=1,
    sleep_between_requests_sec=0.9,
    weekdays_only=True,
    max_retries_per_date=3,
    log_callback=None,
    rate_limit_retry_min_wait_sec=0.3,
):
    """
    checkin_date 未定のとき用: 日付レンジで空き室を探索し、ユニークなプラン一覧を返す。
    """
    import datetime
    import re
    import time

    if isinstance(start_date, str):
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    if not isinstance(stay_nights, int):
        stay_nights = int(stay_nights)
    if stay_nights < 1:
        return {"ok": False, "error": "stay_nights が不正です", "plans": []}

    kw = (plan_keyword or "").strip() or None

    all_plans = []
    seen = set()

    days = (end_date - start_date).days
    if days < 0:
        return {"ok": True, "error": None, "plans": []}

    def _log(msg):
        if callable(log_callback):
            try:
                log_callback(str(msg))
            except Exception:
                pass

    _log(
        f"date_range: hotelNo={hotel_no} range={start_date}..{end_date} nights={stay_nights} "
        f"adult={adult_num} up={up_class_num} low={low_class_num} infantNM={infant_without_mb_num} roomNum={room_num}"
    )

    # 日ごとに探索（各日で hits=30, page を跨いで最大 pageCount）
    # レート制限回避のため、平日だけ等を指定できる
    for d in range(0, days + 1):
        if len(all_plans) >= max_plans_total:
            break

        checkin_d = start_date + datetime.timedelta(days=d)
        if weekdays_only and checkin_d.weekday() >= 5:
            continue

        ci = checkin_d.strftime("%Y-%m-%d")
        co = (checkin_d + datetime.timedelta(days=stay_nights)).strftime("%Y-%m-%d")
        _log(f"[{d+1}/{days+1}] checkin={ci} checkout={co} ...")

        # 429（レート制限）等に備えてリトライ
        last_err = None
        for _retry in range(max_retries_per_date):
            res = run_vacancy_check(
                application_id=application_id,
                access_key=access_key,
                hotel_no=hotel_no,
                checkin_date=ci,
                checkout_date=co,
                adult_num=adult_num,
                up_class_num=up_class_num,
                low_class_num=low_class_num,
                infant_with_mb_num=infant_with_mb_num,
                infant_with_m_num=infant_with_m_num,
                infant_with_b_num=infant_with_b_num,
                infant_without_mb_num=infant_without_mb_num,
                room_num=room_num,
                plan_keyword=kw,
                max_charge=None,
                search_pattern=search_pattern,
                max_plans=max_plans_per_date,
                log_callback=log_callback,
            )

            if res.get("ok"):
                last_err = None
                break

            last_err = res.get("error")
            msg = str(last_err or "")
            is_rate_limit = ("429" in msg) or ("Rate limit" in msg) or ("リクエストが多すぎ" in msg)
            if not is_rate_limit:
                break

            # "Try again in X seconds" を可能な限り抽出
            # Rakuten側の推奨が取れない場合でも、必要以上に待ち続けないための下限を設ける
            wait_sec = float(rate_limit_retry_min_wait_sec or 0.3)
            m = re.search(r"Try again in\s*(\d+(?:\.\d+)?)\s*seconds", msg, flags=re.IGNORECASE)
            if m:
                try:
                    wait_sec = float(m.group(1))
                except Exception:
                    pass
            _log(
                f"  rate limited. wait {max(float(rate_limit_retry_min_wait_sec or 0.3), wait_sec):.1f}s "
                f"and retry ({_retry+1}/{max_retries_per_date})"
            )
            time.sleep(max(float(rate_limit_retry_min_wait_sec or 0.3), wait_sec))

        if not res.get("ok"):
            _log(f"  failed: {last_err}")
            return {"ok": False, "error": last_err or "Unknown error", "plans": []}

        for p in res.get("plans") or []:
            # 日付レンジ（複数日）を横断するので、曜日違いによる「料金だけの差」で
            # 同一要素が分裂しないように、charge をキーから外す。
            # 監視は UI 上の部屋名で選ぶため、roomName をキーに含める。
            plan_id = p.get("planId")
            room_name = p.get("roomName")
            meal_text = p.get("mealText")
            if plan_id and room_name and meal_text is not None:
                key = (str(plan_id), str(room_name).strip(), meal_text)
            else:
                # 念のためフォールバック（欠損時の安全策）
                key = (str(plan_id or ""), meal_text, p.get("roomName") or p.get("roomClass") or "")
            if key in seen:
                continue
            seen.add(key)
            all_plans.append(p)
            if len(all_plans) >= max_plans_total:
                break

        if sleep_between_requests_sec > 0:
            time.sleep(sleep_between_requests_sec)
        _log(f"  merged_plans_so_far={len(all_plans)}")

    all_plans = all_plans[:max_plans_total]
    _log(f"done. total_plans={len(all_plans)}")
    return {"ok": True, "error": None, "plans": all_plans}
