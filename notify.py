# -*- coding: utf-8 -*-
"""
通知送信: LINE Notify / メール
"""
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, parse_qs, urlencode


LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"
LINE_MESSAGING_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line_notify(token, message):
    """LINE Notify でメッセージ送信。成功で True、失敗で False。"""
    if not token:
        return False
    try:
        r = requests.post(
            LINE_NOTIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_line_messaging_push(channel_access_token, to_user_id, message):
    """
    LINE Messaging API で Push メッセージ送信。
    - channel_access_token: Channel access token
    - to_user_id: 送信先 userId（個人）またはグループID（groupId 等）
    """
    if not channel_access_token or not to_user_id:
        return False
    try:
        payload = {
            "to": to_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": message,
                }
            ],
        }
        r = requests.post(
            LINE_MESSAGING_PUSH_URL,
            headers={
                "Authorization": f"Bearer {channel_access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def send_email(smtp_host, smtp_port, user, password, to_email, subject, body):
    """SMTPでメール送信。"""
    if not all([smtp_host, smtp_port, user, password, to_email]):
        return False
    try:
        port = int(smtp_port)
    except (TypeError, ValueError):
        port = 587
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(smtp_host, port, timeout=10) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, [to_email], msg.as_string())
        return True
    except Exception:
        return False


def build_availability_message(hotel_name, checkin, checkout, plans_list, plan_list_url):
    """空室あり通知用のメッセージ文を組み立てる。"""
    lines = [
        "🏨 楽天トラベルで空室が見つかりました",
        "",
        f"施設: {hotel_name}",
        f"チェックイン: {checkin}",
        f"チェックアウト: {checkout}",
        "",
        "【該当プラン】",
    ]

    def to_reservation_input_url(reserve_url: str) -> str:
        """
        Rakuten VacantHotelSearch の reserveUrl は img API の形式の場合があるため、
        クエリパラメータを流用して予約入力画面（rsv/RsvInput.do）へ組み立てる。
        """
        if not reserve_url:
            return ""

        if "rsvh.travel.rakuten.co.jp/rsv/RsvInput.do" in reserve_url:
            return reserve_url

        try:
            u = urlparse(reserve_url)
            q = parse_qs(u.query)
            # parse_qs は値をリストで返すので1件目に潰す
            flat = {k: (v[0] if isinstance(v, list) and v else "") for k, v in q.items()}

            # 予約入力画面に必要な固定パラメータ
            fixed = {
                "f_dhr_rsv_pgm": "ry_kensaku",
                "f_isRaccoLite": "false",
                "f_make_pbox_flg": "false",
                "f_omni_quick_login": "1",
                "cyoyaku": "plan",
            }
            fixed.update(flat)

            return "https://rsvh.travel.rakuten.co.jp/rsv/RsvInput.do?" + urlencode(fixed, doseq=False)
        except Exception:
            return ""
    for p in plans_list[:10]:  # 最大10件
        charge = p.get("charge")
        charge_str = f" ～ {charge}円" if charge else ""
        room_name = p.get("roomName")
        room_part = f" / {room_name}" if room_name else ""
        plan_name = p.get("planName", "")
        lines.append(f"・{plan_name}{room_part}{charge_str}")

        # 予約できるURL（プラン＋部屋単位）
        reserve_url = p.get("reserveUrl") or ""
        booking_url = to_reservation_input_url(reserve_url)
        if booking_url:
            lines.append(f" 予約: {booking_url}")
    if len(plans_list) > 10:
        lines.append(f"  …他 {len(plans_list) - 10} 件")
    # planListUrl は不要（予約入力画面URLを各プラン行に出す）
    return "\n".join(lines)


def notify_availability(notify_settings, hotel_name, checkin, checkout, plans_list, plan_list_url=None):
    """
    空室ありを LINE / メールで通知する。
    plan_list_url: 1件目のプランリストURL（省略時は plans_list[0].planListUrl）
    """
    plan_list_url = plan_list_url or (plans_list[0].get("planListUrl") if plans_list else "")
    message = build_availability_message(hotel_name, checkin, checkout, plans_list, plan_list_url)
    subject = f"[楽天トラベル] 空室あり: {hotel_name} ({checkin})"

    sent = False

    # まず Messaging API を優先（LINE Notify 終了後の代替）
    if notify_settings.get("line_channel_access_token") and notify_settings.get("line_to_user_id"):
        sent = (
            send_line_messaging_push(
                notify_settings["line_channel_access_token"],
                notify_settings["line_to_user_id"],
                message,
            )
            or sent
        )
    # 互換: 旧 LINE Notify トークンが残っていれば併用
    if notify_settings.get("line_token"):
        sent = send_line_notify(notify_settings["line_token"], message) or sent
    if notify_settings.get("smtp_host") and notify_settings.get("notify_email"):
        sent = send_email(
            notify_settings["smtp_host"],
            notify_settings["smtp_port"],
            notify_settings["smtp_user"],
            notify_settings["smtp_password"],
            notify_settings["notify_email"],
            subject,
            message,
        ) or sent
    return sent
