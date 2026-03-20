# -*- coding: utf-8 -*-
"""
ローカル用 Web UI（127.0.0.1 のみバインド）
  pip install -r requirements.txt
  python webapp.py
ブラウザで http://127.0.0.1:5000/
"""
import os
import sys
import datetime
from collections import OrderedDict
import uuid
import threading
import time

from flask import Flask, jsonify, render_template, request

from config import get_notify_settings, get_rakuten_credentials, get_search_conditions
from rakuten_api import parse_keyword_hotel_list, search_hotels_by_keyword
from notify import notify_availability
from vacancy_check import run_vacancy_check
from vacancy_check import run_vacancy_check_date_range
from watch_storage import save_watch_items

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

_JOB_LOCK = threading.Lock()
_JOBS = {}


def _append_job_log(job_id, msg, max_lines=200):
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["logs"].append(str(msg))
        if len(job["logs"]) > max_lines:
            job["logs"] = job["logs"][-max_lines:]


def _start_vacancy_search_job(job_id, parsed):
    form_values = parsed.get("form_values") or {}

    def log_fn(msg):
        _append_job_log(job_id, msg)

    def worker():
        try:
            with _JOB_LOCK:
                if job_id not in _JOBS:
                    return
                _JOBS[job_id]["status"] = "running"

            checkin_label = parsed["checkin"]
            checkout_label = parsed["checkout"]
            send_notify = parsed.get("send_notify", False)

            if parsed.get("checkin_was_blank"):
                # 通知は対象外（日付範囲のユニオンのため）
                send_notify = False
                parsed["send_notify"] = False

                today = datetime.date.today()
                # 最初は平日だけで探索し、空だったら週末も含める
                start_date = today + datetime.timedelta(days=75)
                end_date = today + datetime.timedelta(days=90)

                _append_job_log(job_id, f"date_range primary: {start_date}..{end_date}")
                r = run_vacancy_check_date_range(
                    application_id=parsed["cred"]["application_id"],
                    access_key=parsed["cred"]["access_key"],
                    hotel_no=parsed["hotel_no"],
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    stay_nights=parsed["stay_nights"],
                    adult_num=parsed["adult_num"],
                    up_class_num=parsed["up_class_num"],
                    low_class_num=parsed["low_class_num"],
                    infant_with_mb_num=parsed["infant_with_mb_num"],
                    infant_with_m_num=parsed["infant_with_m_num"],
                    infant_with_b_num=parsed["infant_with_b_num"],
                    infant_without_mb_num=parsed["infant_without_mb_num"],
                    room_num=parsed["room_num"],
                    plan_keyword=parsed["plan_keyword"],
                    weekdays_only=True,
                    max_plans_total=120,
                    max_plans_per_date=10,
                    sleep_between_requests_sec=0.6,
                    max_retries_per_date=2,
                    log_callback=log_fn,
                )
                checkin_label = f"{start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
                checkout_label = (start_date + datetime.timedelta(days=parsed["stay_nights"])).strftime("%Y-%m-%d")

                if r.get("ok") and not r.get("plans"):
                    # フォールバック（週末も含める）
                    fb_start = today + datetime.timedelta(days=60)
                    fb_end = today + datetime.timedelta(days=90)
                    _append_job_log(job_id, f"date_range fallback: {fb_start}..{fb_end}")
                    r = run_vacancy_check_date_range(
                        application_id=parsed["cred"]["application_id"],
                        access_key=parsed["cred"]["access_key"],
                        hotel_no=parsed["hotel_no"],
                        start_date=fb_start.strftime("%Y-%m-%d"),
                        end_date=fb_end.strftime("%Y-%m-%d"),
                        stay_nights=parsed["stay_nights"],
                        adult_num=parsed["adult_num"],
                        up_class_num=parsed["up_class_num"],
                        low_class_num=parsed["low_class_num"],
                        infant_with_mb_num=parsed["infant_with_mb_num"],
                        infant_with_m_num=parsed["infant_with_m_num"],
                        infant_with_b_num=parsed["infant_with_b_num"],
                        infant_without_mb_num=parsed["infant_without_mb_num"],
                        room_num=parsed["room_num"],
                        plan_keyword=parsed["plan_keyword"],
                        weekdays_only=False,
                        max_plans_total=120,
                        max_plans_per_date=10,
                        sleep_between_requests_sec=0.6,
                        max_retries_per_date=2,
                        log_callback=log_fn,
                    )
                    checkin_label = f"{fb_start.strftime('%Y-%m-%d')} 〜 {fb_end.strftime('%Y-%m-%d')}"
                    checkout_label = (fb_start + datetime.timedelta(days=parsed["stay_nights"])).strftime("%Y-%m-%d")
            else:
                _append_job_log(job_id, f"vacancy_check: checkin={parsed['checkin']} checkout={parsed['checkout']}")
                r = run_vacancy_check(
                    application_id=parsed["cred"]["application_id"],
                    access_key=parsed["cred"]["access_key"],
                    hotel_no=parsed["hotel_no"],
                    checkin_date=parsed["checkin"],
                    checkout_date=parsed["checkout"],
                    adult_num=parsed["adult_num"],
                    up_class_num=parsed["up_class_num"],
                    low_class_num=parsed["low_class_num"],
                    infant_with_mb_num=parsed["infant_with_mb_num"],
                    infant_with_m_num=parsed["infant_with_m_num"],
                    infant_with_b_num=parsed["infant_with_b_num"],
                    infant_without_mb_num=parsed["infant_without_mb_num"],
                    room_num=parsed["room_num"],
                    plan_keyword=parsed["plan_keyword"],
                    log_callback=log_fn,
                )

            notify_info = None
            if r.get("ok") and r.get("plans") and send_notify:
                notify = get_notify_settings()
                if notify.get("line_token") or notify.get("notify_email"):
                    hotel_name = r["plans"][0].get("hotelName", "（施設名不明）")
                    plan_list_url = r["plans"][0].get("planListUrl", "")
                    sent = notify_availability(
                        notify,
                        hotel_name=hotel_name,
                        checkin=parsed.get("checkin"),
                        checkout=parsed.get("checkout"),
                        plans_list=r["plans"],
                        plan_list_url=plan_list_url,
                    )
                    notify_info = {"sent": sent}
                else:
                    notify_info = {"sent": False, "reason": "LINE またはメールが .env に未設定です。"}

            result = {
                "ok": r["ok"],
                "error": r["error"],
                "plans": r["plans"],
                "plan_groups": _group_plans_for_display(r["plans"]),
                "notify": notify_info,
                "checkin_was_blank": parsed.get("checkin_was_blank", False),
                "checkin": checkin_label,
                "checkout": checkout_label,
            }

            with _JOB_LOCK:
                job = _JOBS.get(job_id)
                if not job:
                    return
                job["status"] = "done"
                job["result"] = result
                job["done"] = True
        except Exception as e:
            with _JOB_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["status"] = "failed"
                    job["error"] = str(e)
                    job["done"] = True
            _append_job_log(job_id, f"job failed: {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()


@app.route("/api/vacancy-search-start", methods=["POST"])
def vacancy_search_start():
    # フォームと同じ body（application/x-www-form-urlencoded も form-data も）を想定
    parsed, form_error = _parse_form()
    if parsed is None:
        return jsonify({"ok": False, "error": form_error})

    job_id = uuid.uuid4().hex
    with _JOB_LOCK:
        _JOBS[job_id] = {"status": "queued", "logs": [], "done": False, "result": None, "error": None, "form_values": parsed.get("form_values") or {}}

    _append_job_log(job_id, "job started.")
    _start_vacancy_search_job(job_id, parsed)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/vacancy-search-status")
def vacancy_search_status():
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"ok": False, "error": "job_id is required"})

    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "job not found"})
        return jsonify(
            {
                "ok": True,
                "status": job.get("status"),
                "done": job.get("done"),
                "logs": job.get("logs")[-200:],
                "error": job.get("error"),
            }
        )


@app.route("/api/watch/save", methods=["POST"])
def watch_save():
    """
    WebUIで選択した「監視したいプラン＋部屋」を JSON ファイルへ保存する。
    """
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    search = payload.get("search") or {}

    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "items is required"})
    if not isinstance(search, dict) or not search:
        return jsonify({"ok": False, "error": "search is required"})

    # WebUIでは checkin_date 未入力（= flexible）を想定
    # watch_main 側の検索ロジックに合わせ、mode/fallback を埋める
    mode = str(search.get("mode") or "")
    if not mode:
        mode = "flexible_default"

    search.setdefault("mode", mode)
    search.setdefault("primaryStartOffsetDays", 75)
    search.setdefault("primaryEndOffsetDays", 90)
    search.setdefault("fallbackStartOffsetDays", 60)
    search.setdefault("fallbackEndOffsetDays", 90)

    # hotel_no は items の hotelNo を優先するが、無い場合は search から補完
    if not search.get("hotel_no"):
        # WebUI送信は hotelNo/hotel_no の揺れがありうるので吸収
        search["hotel_no"] = search.get("hotelNo") or ""

    # monitoring の目的は「未来に空いたら通知」なので、
    # 希望日で“いま空いているか”を見て保存を落とすのはしません。
    # 保存はユーザーの選択意図（planId+部屋+食事）をそのまま永続化し、
    # 空き判定は watch_main.py 側で希望日ごとに行います。
    res = save_watch_items(search=search, items=items)
    res["saved_items_count"] = len(items)
    res["original_items_count"] = len(items)
    return jsonify(res)


def _charge_sort_key(charge):
    try:
        return int(charge)
    except (TypeError, ValueError):
        return 10**18


def _group_plans_for_display(plans):
    """
    同一の planName を束ねて表示用の階層構造にする。
    各要素は「食事・部屋名・料金」に加えて、監視用の ID 情報も保持する。
    """
    groups = OrderedDict()
    for p in plans or []:
        plan_name = p.get("planName") or "(プラン名なし)"
        key = str(plan_name)
        if key not in groups:
            groups[key] = {
                "planName": plan_name,
                "items": [],
            }

        groups[key]["items"].append(
            {
                "hotelNo": p.get("hotelNo"),
                "planId": p.get("planId"),
                "roomClass": p.get("roomClass"),
                "mealText": p.get("mealText"),
                "roomName": p.get("roomName"),
                "charge": p.get("charge"),
                "planListUrl": p.get("planListUrl") or "",
            }
        )

    # 各グループ内は「部屋名」でソート
    for g in groups.values():
        g["items"].sort(
            key=lambda it: (
                (it.get("roomName") or ""),
                _charge_sort_key(it.get("charge")),
            )
        )

    # グループ（プラン名）もソート
    group_list = list(groups.values())
    group_list.sort(key=lambda g: (g.get("planName") or ""))
    return group_list


def _defaults_from_env():
    c = get_search_conditions()
    default_checkin = c["checkin_date"] or ""
    default_checkout = c["checkout_date"] or ""
    stay_nights = 1
    if default_checkin and default_checkout:
        try:
            d1 = datetime.datetime.strptime(default_checkin, "%Y-%m-%d").date()
            d2 = datetime.datetime.strptime(default_checkout, "%Y-%m-%d").date()
            delta = (d2 - d1).days
            if delta >= 1:
                stay_nights = delta
        except ValueError:
            pass
    return {
        "hotel_no": c["hotel_no"],
        "hotel_label": "",
        "checkin_date": c["checkin_date"],
        "stay_nights": stay_nights,
        "adult_num": c["adult_num"],
        "room_num": c["room_num"],
        "plan_keyword": c["plan_keyword"] or "",
        "max_charge": c["max_charge"] or "",
        "up_class_num": 0,
        "low_class_num": 0,
        "infant_with_mb_num": 0,
        "infant_with_m_num": 0,
        "infant_with_b_num": 0,
        "infant_without_mb_num": 0,
    }


def _parse_form():
    hotel_no = (request.form.get("hotel_no") or "").strip()
    checkin_raw = (request.form.get("checkin_date") or "").strip()
    stay_nights_raw = (request.form.get("stay_nights") or "").strip()
    plan_keyword = (request.form.get("plan_keyword") or "").strip()

    try:
        adult_num = int(request.form.get("adult_num") or 2)
    except ValueError:
        adult_num = 2
    try:
        room_num = int(request.form.get("room_num") or 1)
    except ValueError:
        room_num = 1

    # チェックイン日未定でもプラン一覧を出したいので、
    # 未入力時は「暫定日（今日+1日）」で API を呼び出す。
    checkin_was_blank = not checkin_raw
    if checkin_was_blank:
        checkin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        checkin = checkin_raw

    send_notify = request.form.get("send_notify") == "1"

    def _int_form(name, default=0):
        v = (request.form.get(name) or "").strip()
        if not v:
            return default
        try:
            return int(v)
        except ValueError:
            return default

    hotel_label = (request.form.get("hotel_label") or "").strip()

    form_values = {
        "hotel_no": hotel_no,
        "hotel_label": hotel_label,
        "checkin_date": checkin_raw,
        "stay_nights": stay_nights_raw,
        "adult_num": adult_num,
        "room_num": room_num,
        "plan_keyword": plan_keyword,
        "up_class_num": _int_form("up_class_num", 0),
        "low_class_num": _int_form("low_class_num", 0),
        "infant_with_mb_num": _int_form("infant_with_mb_num", 0),
        "infant_with_m_num": _int_form("infant_with_m_num", 0),
        "infant_with_b_num": _int_form("infant_with_b_num", 0),
        "infant_without_mb_num": _int_form("infant_without_mb_num", 0),
    }

    if not hotel_no or not stay_nights_raw:
        return None, "施設（施設番号）・宿泊数は必須です。候補から施設を選んでください。"

    try:
        stay_nights = int(stay_nights_raw)
    except ValueError:
        return None, "宿泊数は整数で入力してください。"
    if stay_nights < 1:
        return None, "宿泊数は1以上で入力してください。"

    try:
        d1 = datetime.datetime.strptime(checkin, "%Y-%m-%d").date()
        d2 = d1 + datetime.timedelta(days=stay_nights)
        checkout = d2.strftime("%Y-%m-%d")
    except ValueError:
        return None, "チェックイン日は YYYY-MM-DD 形式で入力してください。"

    cred = get_rakuten_credentials()
    if not cred["application_id"] or not cred["access_key"]:
        return None, ".env に RAKUTEN_APPLICATION_ID と RAKUTEN_ACCESS_KEY を設定してください。"

    up_class_num = _int_form("up_class_num", 0)
    low_class_num = _int_form("low_class_num", 0)
    infant_with_mb_num = _int_form("infant_with_mb_num", 0)
    infant_with_m_num = _int_form("infant_with_m_num", 0)
    infant_with_b_num = _int_form("infant_with_b_num", 0)
    infant_without_mb_num = _int_form("infant_without_mb_num", 0)

    return {
        "cred": cred,
        "hotel_no": hotel_no,
        "checkin": checkin,
        "checkout": checkout,
        "adult_num": adult_num,
        "up_class_num": up_class_num,
        "low_class_num": low_class_num,
        "infant_with_mb_num": infant_with_mb_num,
        "infant_with_m_num": infant_with_m_num,
        "infant_with_b_num": infant_with_b_num,
        "infant_without_mb_num": infant_without_mb_num,
        "room_num": room_num,
        "plan_keyword": plan_keyword or None,
        "checkin_was_blank": checkin_was_blank,
        "stay_nights": stay_nights,
        "send_notify": send_notify,
        "form_values": form_values,
    }, None


@app.route("/api/hotel-suggest")
def hotel_suggest():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": False, "error": "キーワードは2文字以上で入力してください。", "hotels": []})

    cred = get_rakuten_credentials()
    if not cred["application_id"] or not cred["access_key"]:
        return jsonify(
            {"ok": False, "error": ".env に楽天 API の認証情報を設定してください。", "hotels": []}
        )

    affiliate = (os.environ.get("RAKUTEN_AFFILIATE_ID") or "").strip() or None
    ok, data, err = search_hotels_by_keyword(
        cred["application_id"],
        cred["access_key"],
        q,
        hits=30,
        page=1,
        affiliate_id=affiliate,
    )
    if not ok:
        return jsonify({"ok": False, "error": err, "hotels": []})

    hotels = parse_keyword_hotel_list(data)
    paging = data.get("pagingInfo") or {}
    return jsonify(
        {
            "ok": True,
            "hotels": hotels,
            "recordCount": paging.get("recordCount"),
            "pageCount": paging.get("pageCount"),
        }
    )


@app.route("/", methods=["GET", "POST"])
def index():
    # バックグラウンドジョブ完了後に結果を表示する
    job_id = (request.args.get("job_id") or "").strip()
    if request.method == "GET" and job_id:
        with _JOB_LOCK:
            job = _JOBS.get(job_id)
        if job and job.get("done") and job.get("result"):
            defaults = _defaults_from_env()
            return render_template(
                "index.html",
                defaults=defaults,
                form_values=job.get("form_values") or defaults,
                result=job.get("result"),
                form_error=None,
            )

    defaults = _defaults_from_env()
    result = None
    form_error = None

    if request.method == "POST":
        parsed, form_error = _parse_form()
        if parsed is None:
            return render_template(
                "index.html",
                defaults=defaults,
                form_values=_form_values_from_request(),
                result=None,
                form_error=form_error,
            )

        if parsed.get("checkin_was_blank"):
            # チェックイン未定の場合: 今日+60〜今日+90の範囲で空室を探索する
            import datetime

            today = datetime.date.today()
            start_date = today + datetime.timedelta(days=75)
            end_date = today + datetime.timedelta(days=90)

            r = run_vacancy_check_date_range(
                application_id=parsed["cred"]["application_id"],
                access_key=parsed["cred"]["access_key"],
                hotel_no=parsed["hotel_no"],
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                stay_nights=parsed["stay_nights"],
                adult_num=parsed["adult_num"],
                up_class_num=parsed["up_class_num"],
                low_class_num=parsed["low_class_num"],
                infant_with_mb_num=parsed["infant_with_mb_num"],
                infant_with_m_num=parsed["infant_with_m_num"],
                infant_with_b_num=parsed["infant_with_b_num"],
                infant_without_mb_num=parsed["infant_without_mb_num"],
                room_num=parsed["room_num"],
                plan_keyword=parsed["plan_keyword"],
                weekdays_only=True,
                max_plans_total=120,
                max_plans_per_date=10,
                sleep_between_requests_sec=0.6,
                max_retries_per_date=2,
            )

            checkin_label = f"{start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
            checkout_label = (start_date + datetime.timedelta(days=parsed["stay_nights"])).strftime("%Y-%m-%d")

            # 平日だけで空だった場合に備えて、週末も含めて探索範囲を広げる
            if r.get("ok") and not r.get("plans"):
                fb_start = today + datetime.timedelta(days=60)
                fb_end = today + datetime.timedelta(days=90)
                r = run_vacancy_check_date_range(
                    application_id=parsed["cred"]["application_id"],
                    access_key=parsed["cred"]["access_key"],
                    hotel_no=parsed["hotel_no"],
                    start_date=fb_start.strftime("%Y-%m-%d"),
                    end_date=fb_end.strftime("%Y-%m-%d"),
                    stay_nights=parsed["stay_nights"],
                    adult_num=parsed["adult_num"],
                    up_class_num=parsed["up_class_num"],
                    low_class_num=parsed["low_class_num"],
                    infant_with_mb_num=parsed["infant_with_mb_num"],
                    infant_with_m_num=parsed["infant_with_m_num"],
                    infant_with_b_num=parsed["infant_with_b_num"],
                    infant_without_mb_num=parsed["infant_without_mb_num"],
                    room_num=parsed["room_num"],
                    plan_keyword=parsed["plan_keyword"],
                    weekdays_only=False,
                    max_plans_total=120,
                    max_plans_per_date=10,
                    sleep_between_requests_sec=0.6,
                    max_retries_per_date=2,
                )
                checkin_label = f"{fb_start.strftime('%Y-%m-%d')} 〜 {fb_end.strftime('%Y-%m-%d')}"
                checkout_label = (fb_start + datetime.timedelta(days=parsed["stay_nights"])).strftime("%Y-%m-%d")
        else:
            r = run_vacancy_check(
                application_id=parsed["cred"]["application_id"],
                access_key=parsed["cred"]["access_key"],
                hotel_no=parsed["hotel_no"],
                checkin_date=parsed["checkin"],
                checkout_date=parsed["checkout"],
                adult_num=parsed["adult_num"],
                up_class_num=parsed["up_class_num"],
                low_class_num=parsed["low_class_num"],
                infant_with_mb_num=parsed["infant_with_mb_num"],
                infant_with_m_num=parsed["infant_with_m_num"],
                infant_with_b_num=parsed["infant_with_b_num"],
                infant_without_mb_num=parsed["infant_without_mb_num"],
                room_num=parsed["room_num"],
                plan_keyword=parsed["plan_keyword"],
            )
            checkin_label = parsed["checkin"]
            checkout_label = parsed["checkout"]

        # チェックイン未定時は、日付が確定しないため通知対象外にする
        if parsed.get("checkin_was_blank"):
            parsed["send_notify"] = False

        notify_info = None
        if r["ok"] and r["plans"] and parsed["send_notify"]:
            notify = get_notify_settings()
            if notify.get("line_token") or notify.get("notify_email"):
                hotel_name = r["plans"][0].get("hotelName", "（施設名不明）")
                plan_list_url = r["plans"][0].get("planListUrl", "")
                sent = notify_availability(
                    notify,
                    hotel_name=hotel_name,
                    checkin=parsed["checkin"],
                    checkout=parsed["checkout"],
                    plans_list=r["plans"],
                    plan_list_url=plan_list_url,
                )
                notify_info = {"sent": sent}
            else:
                notify_info = {"sent": False, "reason": "LINE またはメールが .env に未設定です。"}

        result = {
            "ok": r["ok"],
            "error": r["error"],
            "plans": r["plans"],
            "plan_groups": _group_plans_for_display(r["plans"]),
            "notify": notify_info,
            "checkin_was_blank": parsed.get("checkin_was_blank", False),
            "checkin": checkin_label,
            "checkout": checkout_label,
        }

        return render_template(
            "index.html",
            defaults=defaults,
            form_values=parsed["form_values"],
            result=result,
            form_error=None,
        )

    return render_template(
        "index.html",
        defaults=defaults,
        form_values=defaults.copy(),
        result=None,
        form_error=None,
    )


def _form_values_from_request():
    return {
        "hotel_no": (request.form.get("hotel_no") or "").strip(),
        "hotel_label": (request.form.get("hotel_label") or "").strip(),
        "checkin_date": (request.form.get("checkin_date") or "").strip(),
        "stay_nights": (request.form.get("stay_nights") or "").strip(),
        "adult_num": request.form.get("adult_num") or "2",
        "room_num": request.form.get("room_num") or "1",
        "plan_keyword": (request.form.get("plan_keyword") or "").strip(),
        "max_charge": (request.form.get("max_charge") or "").strip(),
        "up_class_num": request.form.get("up_class_num") or "0",
        "low_class_num": request.form.get("low_class_num") or "0",
        "infant_with_mb_num": request.form.get("infant_with_mb_num") or "0",
        "infant_with_m_num": request.form.get("infant_with_m_num") or "0",
        "infant_with_b_num": request.form.get("infant_with_b_num") or "0",
        "infant_without_mb_num": request.form.get("infant_without_mb_num") or "0",
    }


def main():
    host = os.environ.get("WEBAPP_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBAPP_PORT", "5000"))
    if host == "0.0.0.0":
        print(
            "警告: 0.0.0.0 で公開しています。ローカル専用でない場合は認証を検討してください。",
            file=sys.stderr,
        )
    print(f"ブラウザで http://{host}:{port}/ を開いてください（終了は Ctrl+C）")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
