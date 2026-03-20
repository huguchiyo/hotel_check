# -*- coding: utf-8 -*-
"""
監視対象（WebUIで選択したプラン＋部屋）の保存/読み込み。

基本方針:
  - 永続化はローカルの JSON ファイル（WATCH_FILE でパス上書き可）
  - 同一検索条件（ホテル/泊数/人数/子ども区分）ごとに watch record をまとめる
  - 各 watch record 内で、planId+roomClass+mealText を監視キーとして管理する
"""

import os
import json
import uuid
import datetime


def _watch_file_path():
    default_path = os.path.join(os.path.dirname(__file__), "watch_selections.json")
    return (os.environ.get("WATCH_FILE") or default_path).strip()


def _now_iso():
    # UTC で保存（環境差異を避ける）
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _json_load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_save(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_watch_state():
    path = _watch_file_path()
    if not os.path.exists(path):
        return {"version": 1, "records": []}
    try:
        data = _json_load(path)
        if not isinstance(data, dict) or data.get("version") != 1:
            return {"version": 1, "records": []}
        if not isinstance(data.get("records"), list):
            return {"version": 1, "records": []}
        return data
    except Exception:
        # 壊れた場合でも監視不能にしない
        return {"version": 1, "records": []}


def save_watch_state(state):
    path = _watch_file_path()
    _json_save(path, state)


def watch_search_signature(search):
    """
    「同一の検索条件」と見なすための署名。
    JSONのキー順ブレを吸収するため、sorted_keys でダンプした文字列を使う。
    """
    if not isinstance(search, dict):
        search = {}
    normalized = {
        "hotel_no": str(search.get("hotel_no") or ""),
        "mode": str(search.get("mode") or ""),
        "primaryStartOffsetDays": search.get("primaryStartOffsetDays"),
        "primaryEndOffsetDays": search.get("primaryEndOffsetDays"),
        "fallbackStartOffsetDays": search.get("fallbackStartOffsetDays"),
        "fallbackEndOffsetDays": search.get("fallbackEndOffsetDays"),
        "stay_nights": int(search.get("stay_nights") or 1),
        "room_num": int(search.get("room_num") or 1),
        "adult_num": int(search.get("adult_num") or 2),
        "up_class_num": int(search.get("up_class_num") or 0),
        "low_class_num": int(search.get("low_class_num") or 0),
        "infant_with_mb_num": int(search.get("infant_with_mb_num") or 0),
        "infant_with_m_num": int(search.get("infant_with_m_num") or 0),
        "infant_with_b_num": int(search.get("infant_with_b_num") or 0),
        "infant_without_mb_num": int(search.get("infant_without_mb_num") or 0),
        # 入力仕様: 文字列で渡す（例: "2026-06-17,2026-06-18"）
        "preferred_checkin_dates": str(search.get("preferred_checkin_dates") or ""),
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def watch_entry_key(hotel_no, plan_id, room_class, meal_text):
    return f"{hotel_no}|{plan_id}|{room_class}|{meal_text}"


def save_watch_items(search, items):
    """
    search: WebUIから渡される検索条件（宿泊数/人数/ホテルなど）
    items: 監視対象（planId+roomClass+mealText を含む）
    """
    state = load_watch_state()
    signature = watch_search_signature(search)

    # 既存 record を探す
    record = None
    for r in state.get("records") or []:
        if r.get("signature") == signature:
            record = r
            break

    if record is None:
        record = {
            "id": uuid.uuid4().hex,
            "signature": signature,
            "created_at": _now_iso(),
            "search": search,
            "entries": {},
        }
        state["records"].append(record)

    for it in items or []:
        hotel_no = str(it.get("hotelNo") or search.get("hotel_no") or "")
        plan_id = str(it.get("planId") or "")
        room_class = str(it.get("roomClass") or "")
        meal_text = it.get("mealText") or ""

        if not (hotel_no and plan_id and room_class and meal_text):
            continue

        k = watch_entry_key(hotel_no, plan_id, room_class, meal_text)
        entry = record["entries"].get(k) or {
            "key": k,
            "hotelNo": hotel_no,
            "planId": plan_id,
            "roomClass": room_class,
            "mealText": meal_text,
            "display": {},
            "planListUrl": "",
            "state": {"last_found_at": None, "last_notified_at": None},
        }

        entry["display"] = {
            "planName": it.get("planName") or it.get("planNameText") or "",
            "roomName": it.get("roomName") or "",
        }
        entry["planListUrl"] = it.get("planListUrl") or entry.get("planListUrl") or ""

        record["entries"][k] = entry

    save_watch_state(state)
    return {"ok": True, "record_id": record.get("id"), "entries": len(record.get("entries") or {})}


def iter_watch_records():
    state = load_watch_state()
    for r in state.get("records") or []:
        yield r

