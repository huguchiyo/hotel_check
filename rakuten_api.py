# -*- coding: utf-8 -*-
"""
楽天トラベル API クライアント
- 空室検索: https://webservice.rakuten.co.jp/documentation/vacant-hotel-search
- キーワード検索（施設名）: https://webservice.rakuten.co.jp/documentation/keyword-hotel-search
"""
import requests
import time
import os
import json

API_BASE = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
KEYWORD_HOTEL_API = (
    "https://openapi.rakuten.co.jp/engine/api/Travel/KeywordHotelSearch/20170426"
)


def _get_rakuten_referer():
    """
    楽天API側が HTTP Referrer を要求する場合があるため、許可されたサイトに合わせて付与する。
    未設定なら webservice.rakuten.co.jp をデフォルトにする。
    """
    # KeywordHotelSearch 側の判定で webservices.rakuten.co.jp が要求されることがある
    return os.environ.get("RAKUTEN_REFERER", "https://webservices.rakuten.co.jp/")


def _get_rakuten_origin():
    """
    楽天APIが Origin を必須にするケースがあるため用意。
    未設定なら https://webservice.rakuten.co.jp を使う。
    """
    return os.environ.get("RAKUTEN_ORIGIN", "https://webservices.rakuten.co.jp")


def search_vacant_hotels(
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
    max_charge=None,
    search_pattern=1,
    format_version=2,
    hits=30,
    page=1,
):
    """
    空室検索APIを呼び出す。
    hotel_no: 施設番号（int または "12345,67890" のようにカンマ区切り文字列）
    search_pattern: 0=施設ごと, 1=宿泊プランごと（プラン名で絞るなら1推奨）
    戻り値: (success: bool, data: dict or None, error_message: str)
    """
    if not application_id or not access_key:
        return False, None, "RAKUTEN_APPLICATION_ID と RAKUTEN_ACCESS_KEY を設定してください"

    # VacantHotelSearch は hits 上限が 30 のため、超過を避ける
    try:
        hits = int(hits)
    except (TypeError, ValueError):
        hits = 30
    hits = max(1, min(hits, 30))

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    params = {
        "applicationId": application_id,
        # VacantHotelSearch は accessKey を query parameter かヘッダで要求する。
        "accessKey": access_key,
        "format": "json",
        "formatVersion": format_version,
        "checkinDate": checkin_date,
        "checkoutDate": checkout_date,
        "adultNum": adult_num,
        "upClassNum": up_class_num,
        "lowClassNum": low_class_num,
        "infantWithMBNum": infant_with_mb_num,
        "infantWithMNum": infant_with_m_num,
        "infantWithBNum": infant_with_b_num,
        "infantWithoutMBNum": infant_without_mb_num,
        "roomNum": room_num,
        "searchPattern": search_pattern,
        "hits": hits,
        "page": page,
    }

    # 施設番号（複数はカンマ区切りでそのまま渡せる）
    if isinstance(hotel_no, (list, tuple)):
        hotel_no = ",".join(str(x) for x in hotel_no)
    params["hotelNo"] = str(hotel_no).strip()

    if max_charge is not None and str(max_charge).strip():
        try:
            params["maxCharge"] = int(max_charge)
        except ValueError:
            pass

    headers = {
        "Referer": _get_rakuten_referer(),
        "Origin": _get_rakuten_origin(),
    }

    try:
        r = requests.get(API_BASE, params=params, headers=headers, timeout=30)
        try:
            data = r.json()
        except ValueError:
            data = None

        if r.status_code >= 400:
            # 404 は「該当データなし」のことがあるため UI 上は空扱いに寄せる
            if isinstance(data, dict):
                err_code = data.get("error")
                err_desc = data.get("error_description")
                if err_code == "not_found" or str(err_desc).lower() == "data not found":
                    return True, {}, ""
                if "errors" in data and isinstance(data["errors"], dict):
                    err_payload = data["errors"]
                    msg = (
                        err_payload.get("errorMessage")
                        or err_payload.get("errorCode")
                        or err_payload.get("message")
                        or json.dumps(err_payload, ensure_ascii=False)
                    )
                    return False, None, msg
                # error / error_description どちらも無い場合はレスポンスを丸ごと出す
                msg = err_desc or err_code or json.dumps(data, ensure_ascii=False)
                return False, None, msg

            return False, None, f"APIリクエストエラー（HTTP {r.status_code}）"
    except requests.exceptions.Timeout:
        return False, None, "APIがタイムアウトしました"
    except requests.exceptions.RequestException as e:
        return False, None, f"APIリクエストエラー: {e}"

    # エラーレスポンス（status_code が 200 でも error フィールドが返るケースに備える）
    if isinstance(data, dict) and "error" in data:
        if data.get("error") == "not_found":
            return True, {}, ""
        msg = data.get("error_description") or data.get("error") or json.dumps(data, ensure_ascii=False)
        return False, None, msg

    # レート制限対策
    time.sleep(0.5)

    return True, data, ""


def search_hotels_by_keyword(
    application_id,
    access_key,
    keyword,
    hits=30,
    page=1,
    affiliate_id=None,
    format_version=2,
):
    """
    楽天トラベル キーワード検索API（施設名など）
    https://webservice.rakuten.co.jp/documentation/keyword-hotel-search
    keyword: 2文字以上（API仕様）
    searchField=1: 施設名のみ
    戻り値: (success, data, error_message)
    """
    if not application_id or not access_key:
        return False, None, "RAKUTEN_APPLICATION_ID と RAKUTEN_ACCESS_KEY を設定してください"

    kw = (keyword or "").strip()
    if len(kw) < 2:
        return False, None, "キーワードは2文字以上で入力してください"

    params = {
        "applicationId": application_id,
        "format": "json",
        "formatVersion": format_version,
        "keyword": kw,
        "hits": max(1, min(int(hits), 30)),
        "page": max(1, min(int(page), 100)),
        "searchField": 1,
        "responseType": "middle",
        "carrier": 0,
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    # KeywordHotelSearch は accessKey をパラメータで渡す方式が安定（Referrer も要求されることがある）
    params["accessKey"] = access_key
    headers = {
        "Referer": _get_rakuten_referer(),
        "Origin": _get_rakuten_origin(),
    }

    try:
        r = requests.get(KEYWORD_HOTEL_API, params=params, headers=headers, timeout=30)
        try:
            data = r.json()
        except ValueError:
            data = None

        if r.status_code >= 400:
            # 403 のような場合、エラー本文を優先して返す
            if isinstance(data, dict):
                if "errors" in data and isinstance(data["errors"], dict):
                    return False, None, data["errors"].get("errorMessage", "Unknown error")
                if "error" in data:
                    return False, None, data.get("error_description") or data.get("error", "Unknown error")
            return False, None, f"APIリクエストエラー（HTTP {r.status_code}）"

    except requests.exceptions.Timeout:
        return False, None, "APIがタイムアウトしました"
    except requests.exceptions.RequestException as e:
        return False, None, f"APIリクエストエラー: {e}"

    # 共通エラー
    if isinstance(data, dict) and "error" in data:
        return False, None, data.get("error_description", data.get("error", "Unknown error"))
    if isinstance(data, dict) and "errors" in data:
        # errors: { errorCode, errorMessage } の形が多い
        err = data.get("errors") or {}
        return False, None, err.get("errorMessage", "Unknown error")

    time.sleep(0.35)
    return True, data, ""


def parse_keyword_hotel_list(data):
    """
    キーワード検索APIの JSON から施設一覧を抽出。
    hotels[].hotel[] 内の hotelBasicInfo を想定。
    """
    out = []
    seen = set()
    hotels_raw = data.get("hotels")
    if not hotels_raw and "items" in data:
        for it in data.get("items") or []:
            item = it.get("item") if isinstance(it, dict) else None
            if isinstance(item, dict) and item.get("hotelNo") is not None:
                key = str(item.get("hotelNo"))
                if key in seen:
                    continue
                seen.add(key)
                name = (item.get("hotelName") or "").strip()
                addr = (item.get("address1") or "").strip()
                addr2 = (item.get("address2") or "").strip()
                out.append({
                    "hotelNo": key,
                    "hotelName": name,
                    "address": (addr + addr2).strip() or None,
                })
        return out

    if not isinstance(hotels_raw, list):
        return out

    for ent in hotels_raw:
        # API応答: hotels は [ [ {hotelBasicInfo...}, {...} ], ... ] のように list-of-list になることがある
        if isinstance(ent, list):
            blocks = ent
        elif isinstance(ent, dict):
            blocks = ent.get("hotel") if isinstance(ent.get("hotel"), list) else None
            if blocks is None:
                blocks = [ent]
        else:
            continue

        basic = {}
        for blk in blocks:
            if not isinstance(blk, dict):
                continue
            hb = blk.get("hotelBasicInfo")
            if isinstance(hb, dict):
                basic = hb
                break

        if not basic:
            # 念のためのフォールバック
            if isinstance(ent, dict):
                basic = ent.get("hotelBasicInfo") or {}

        no = basic.get("hotelNo")
        if no is None:
            continue
        key = str(no).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        name = (basic.get("hotelName") or "").strip()
        addr = (basic.get("address1") or "").strip()
        addr2 = (basic.get("address2") or "").strip()
        out.append(
            {
                "hotelNo": key,
                "hotelName": name,
                "address": (addr + addr2).strip() or None,
            }
        )

    return out


def parse_vacant_results(data, plan_keyword=None):
    """
    APIレスポンスから「空室あり」の施設・プラン一覧を整理する。
    楽天APIは hotels[].hotel[] で、hotel 配列内に hotelBasicInfo と roomInfo 等が入る形式。
    plan_keyword: 指定時はプラン名にこの文字列が含まれるものだけ返す。
    戻り値: list of dict
      [{ "hotelNo", "hotelName", "planName", "planId", "charge", "reserveUrl", "planListUrl" }, ...]
    """
    results = []
    hotels_raw = data.get("hotels") or data.get("items") or []

    for ent in hotels_raw:
        # VacantHotelSearch は、レスポンス内の hotels が
        #   - list の list（例: hotels[0] が [ {hotelBasicInfo}, {roomInfo}, ... ]）
        #   - dict（例: { "hotel": [ {...}, {...} ] }）
        # のどちらで返ることがあるため、両対応する。
        if isinstance(ent, list):
            hotel_blocks = ent
        elif isinstance(ent, dict):
            hotel_blocks = ent.get("hotel") or [ent]
        else:
            continue

        basic = {}
        reserve_info = {}
        rooms_direct = None  # hotelReserveInfo が無い場合に blk 直下の roomInfo を拾う

        for blk in hotel_blocks:
            if not isinstance(blk, dict):
                continue
            if isinstance(blk.get("hotelBasicInfo"), dict):
                basic = blk.get("hotelBasicInfo") or basic
            if isinstance(blk.get("hotelReserveInfo"), dict):
                reserve_info = blk.get("hotelReserveInfo") or reserve_info

            # 例: hotelBlocks[1] が { "roomInfo": [...] } のように返ってくることがある
            if rooms_direct is None:
                for k in ("roomInfo", "reserveRecords", "roomBasicInfo"):
                    if blk.get(k) is not None:
                        rooms_direct = blk.get(k)
                        break

        hotel_no = basic.get("hotelNo")
        hotel_name = basic.get("hotelName", "")
        plan_list_url = basic.get("planListUrl") or ""

        # 部屋・プラン一覧（roomInfo / reserveRecords / roomBasicInfo）
        rooms = None
        if isinstance(reserve_info, dict) and reserve_info:
            # API応答によって、同じ情報が `roomInfo` と `reserveRecords` のどちらに入っていることがある。
            # その際、`roomInfo` 側が「料金（日別）だけ」になっていて planName / roomName が欠けるケースがあるため、
            # plan/部屋情報がより揃いやすい `reserveRecords` を優先する。
            rooms = (
                reserve_info.get("reserveRecords")
                or reserve_info.get("roomInfo")
                or reserve_info.get("roomBasicInfo")
            )
        if rooms is None:
            rooms = rooms_direct or []

        if isinstance(rooms, dict):
            rooms = [rooms]

        if not isinstance(rooms, list):
            continue

        # VacantHotelSearch の roomInfo は「プラン/部屋情報」要素と「料金（日別）」要素が分かれて返ることがある。
        # その場合、要素0( roomBasicInfoあり / chargeなし ) と要素1( chargeあり / roomBasicInfoなし ) をペアで結合する。
        pending = None  # roomBasicInfo 由来の情報（料金が来たら確定して append）

        for room in rooms:
            if not isinstance(room, dict):
                continue

            rb = room.get("roomBasicInfo") if isinstance(room.get("roomBasicInfo"), dict) else {}

            plan_name = (room.get("planName") or rb.get("planName") or "").strip()
            plan_id = room.get("planId") or rb.get("planId")
            reserve_url = room.get("reserveUrl") or rb.get("reserveUrl") or plan_list_url

            room_name = (room.get("roomName") or rb.get("roomName") or "").strip()
            # VacantHotelSearch では、部屋の種類を表すコード（roomClass）は出てくることが多いが、
            # 念のため roomId が返ってくる場合も拾う
            room_id = room.get("roomId") or rb.get("roomId")
            room_class = (room.get("roomClass") or rb.get("roomClass") or "").strip()

            with_breakfast = room.get("withBreakfastFlag")
            with_dinner = room.get("withDinnerFlag")
            if with_breakfast is None:
                with_breakfast = rb.get("withBreakfastFlag")
            if with_dinner is None:
                with_dinner = rb.get("withDinnerFlag")

            breakfast_text = "朝食あり" if str(with_breakfast) == "1" else "朝食なし"
            dinner_text = "夕食あり" if str(with_dinner) == "1" else "夕食なし"
            meal_text = f"{breakfast_text}　{dinner_text}"

            # charge は dailyCharge / total / rakutenCharge のどこに来るかが揺れるため段階的に取得
            charge = None
            charge_info = room.get("dailyCharge") or rb.get("dailyCharge")
            if isinstance(charge_info, dict):
                first_day = charge_info
                charge = first_day.get("total") or first_day.get("rakutenCharge")
            elif isinstance(charge_info, list) and charge_info:
                first_day = charge_info[0] if isinstance(charge_info[0], dict) else {}
                charge = first_day.get("total") or first_day.get("rakutenCharge")

            if charge is None:
                charge = (
                    room.get("total")
                    or rb.get("total")
                    or room.get("rakutenCharge")
                    or rb.get("rakutenCharge")
                )

            has_plan_info = bool(plan_name) or bool(plan_id) or bool(room_name) or bool(room_class)
            has_charge = charge is not None

            # (1) プラン/部屋情報だけ: 料金が来るまで保留
            if has_plan_info and not has_charge:
                if plan_keyword and plan_keyword not in plan_name:
                    pending = None
                else:
                    pending = {
                        "hotelNo": hotel_no,
                        "hotelName": hotel_name,
                        "planName": plan_name or "(プラン名なし)",
                        "planId": plan_id,
                        "mealText": meal_text,
                        "roomName": room_name,
                        "roomId": room_id,
                        "roomClass": room_class,
                        "reserveUrl": reserve_url,
                        "planListUrl": plan_list_url,
                    }
                continue

            # (2) 料金だけ: pending と結合して 1件として出す
            if has_charge and not has_plan_info:
                if pending:
                    pending["charge"] = charge
                    results.append(pending)
                    pending = None
                continue

            # (3) プランも料金も揃っている: 通常出力
            if has_plan_info:
                if plan_keyword and plan_keyword not in plan_name:
                    continue
                results.append(
                    {
                        "hotelNo": hotel_no,
                        "hotelName": hotel_name,
                        "planName": plan_name or "(プラン名なし)",
                        "planId": plan_id,
                        "mealText": meal_text,
                        "roomName": room_name,
                        "roomId": room_id,
                        "roomClass": room_class,
                        "charge": charge,
                        "reserveUrl": reserve_url,
                        "planListUrl": plan_list_url,
                    }
                )

        pending = None

    # formatVersion=1 の items[].item 形式
    if not results and "items" in data:
        for it in data["items"]:
            item = it.get("item") or it
            hotel_no = item.get("hotelNo")
            hotel_name = item.get("hotelName", "")
            plan_name = (item.get("planName") or "").strip()
            if plan_keyword and plan_keyword not in plan_name:
                continue
            results.append({
                "hotelNo": hotel_no,
                "hotelName": hotel_name,
                "planName": plan_name or "(プラン名なし)",
                "planId": item.get("planId"),
                "mealText": None,
                "roomName": None,
                "roomId": item.get("roomId"),
                "roomClass": None,
                "charge": item.get("total") or item.get("rakutenCharge"),
                "reserveUrl": item.get("reserveUrl") or item.get("planListUrl", ""),
                "planListUrl": item.get("planListUrl", ""),
            })

    return results
