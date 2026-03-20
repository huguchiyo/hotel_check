# -*- coding: utf-8 -*-
"""
監視条件の設定。
環境変数または config.yaml で上書き可能にすることもできるが、
ここでは環境変数とデフォルトでシンプルに実装する。
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name, default):
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def get_rakuten_credentials():
    return {
        "application_id": os.environ.get("RAKUTEN_APPLICATION_ID", "").strip(),
        "access_key": os.environ.get("RAKUTEN_ACCESS_KEY", "").strip(),
    }


def get_search_conditions():
    """
    検索条件を返す。
    環境変数 SEARCH_* で指定。未設定の場合は .env や実行時オプションに依存させるため、
    ここではデフォルトは空で、main で必須チェックする。
    """
    return {
        "hotel_no": os.environ.get("SEARCH_HOTEL_NO", "").strip(),  # 施設番号（カンマ区切りで複数可）
        "checkin_date": os.environ.get("SEARCH_CHECKIN_DATE", "").strip(),  # YYYY-MM-DD
        "checkout_date": os.environ.get("SEARCH_CHECKOUT_DATE", "").strip(),  # YYYY-MM-DD
        "adult_num": _int_env("SEARCH_ADULT_NUM", 2),
        "room_num": _int_env("SEARCH_ROOM_NUM", 1),
        "plan_keyword": os.environ.get("SEARCH_PLAN_KEYWORD", "").strip(),  # プラン名で絞り込み（部分一致）
        "max_charge": os.environ.get("SEARCH_MAX_CHARGE", "").strip() or None,  # 上限金額（任意）
    }


def get_notify_settings():
    return {
        # LINE Notify（終了済み）
        "line_token": os.environ.get("LINE_NOTIFY_TOKEN", "").strip(),
        # LINE Messaging API（推奨）
        "line_channel_access_token": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip(),
        # Push の送信先（ユーザーID / グループID は要件により変わる）
        "line_to_user_id": os.environ.get("LINE_TO_USER_ID", "").strip(),
        "smtp_host": os.environ.get("SMTP_HOST", "").strip() or None,
        "smtp_port": os.environ.get("SMTP_PORT", "").strip() or None,
        "smtp_user": os.environ.get("SMTP_USER", "").strip() or None,
        "smtp_password": os.environ.get("SMTP_PASSWORD", "").strip() or None,
        "notify_email": os.environ.get("NOTIFY_EMAIL", "").strip() or None,
    }
