# -*- coding: utf-8 -*-
"""
楽天トラベル ホテル空室監視 & 通知

使い方:
  1. .env に RAKUTEN_APPLICATION_ID, RAKUTEN_ACCESS_KEY, LINE_NOTIFY_TOKEN 等を設定
  2. 環境変数で検索条件を指定（SEARCH_HOTEL_NO, SEARCH_CHECKIN_DATE など）
  3. python main.py

GitHub Actions で定期実行する場合は、リポジトリの Secrets に上記を登録し、
ワークフロー内で env に渡してください。
"""
import os
import sys
from config import get_rakuten_credentials, get_search_conditions, get_notify_settings
from vacancy_check import run_vacancy_check
from notify import notify_availability


def main():
    cred = get_rakuten_credentials()
    cond = get_search_conditions()
    notify = get_notify_settings()

    hotel_no = cond["hotel_no"]
    checkin = cond["checkin_date"]
    checkout = cond["checkout_date"]
    adult_num = cond["adult_num"]
    room_num = cond["room_num"]
    plan_keyword = cond["plan_keyword"] or None
    max_charge = cond["max_charge"]

    if not hotel_no or not checkin or not checkout:
        print(
            "検索条件を設定してください。環境変数: "
            "SEARCH_HOTEL_NO, SEARCH_CHECKIN_DATE, SEARCH_CHECKOUT_DATE",
            file=sys.stderr,
        )
        sys.exit(1)

    result = run_vacancy_check(
        application_id=cred["application_id"],
        access_key=cred["access_key"],
        hotel_no=hotel_no,
        checkin_date=checkin,
        checkout_date=checkout,
        adult_num=adult_num,
        room_num=room_num,
        plan_keyword=plan_keyword,
        max_charge=max_charge,
        search_pattern=1,
    )

    if not result["ok"]:
        print(f"APIエラー: {result['error']}", file=sys.stderr)
        sys.exit(1)

    plans = result["plans"]

    if not plans:
        print("指定条件では空室は見つかりませんでした。")
        return

    # 施設名は1件目から（同一施設のみ指定なら1種類）
    hotel_name = plans[0].get("hotelName", "（施設名不明）")
    plan_list_url = plans[0].get("planListUrl", "")

    if not (notify.get("line_token") or notify.get("notify_email")):
        print("通知先（LINE_NOTIFY_TOKEN または NOTIFY_EMAIL）が未設定です。")
        print(f"空室あり: {hotel_name} — {len(plans)} プラン")
        for p in plans[:5]:
            print(f"  - {p.get('planName')} {p.get('charge')}円")
        return

    sent = notify_availability(
        notify,
        hotel_name=hotel_name,
        checkin=checkin,
        checkout=checkout,
        plans_list=plans,
        plan_list_url=plan_list_url,
    )
    if sent:
        print(f"通知を送信しました: {hotel_name} ({len(plans)} プラン)")
    else:
        print("通知の送信に失敗しました。トークン・メール設定を確認してください。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
