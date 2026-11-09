# -*- coding: utf-8 -*-
"""Xuất danh sách giọng Vbee COMMUNITY từ phiên đăng nhập của CHÍNH BẠN.

- Chỉ lấy METADATA và URL mẫu, KHÔNG tải MP3/WAV.
- Nhập Bearer token bằng bàn phím; token KHÔNG ghi ra file/log.
- Tự đi qua các trang qua next_cursor cho đến khi hết.
- Dừng khi gặp giới hạn truy cập/429 và giữ lại dữ liệu đã lấy.

Chỉ sử dụng khi tài khoản của bạn được phép truy cập và tuân thủ điều khoản Vbee.
"""
import argparse
import getpass
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://vbee.vn/api/v3/voices"


def clean_voice(v):
    """Chỉ xuất trường cần thiết để duyệt/nghe thử, không xuất dữ liệu chủ tài khoản."""
    sample_audios = []
    for s in v.get("sample_audios") or []:
        if isinstance(s, dict) and s.get("audio_link"):
            sample_audios.append({
                "title": s.get("title") or "Mẫu nghe thử",
                "text": s.get("text") or "",
                "audio_link": s["audio_link"],
            })
    return {
        "id": v.get("id"),
        "code": v.get("code"),
        "name": v.get("name"),
        "gender": v.get("gender"),
        "locale": v.get("locale"),
        "province": v.get("province"),
        "age_group": v.get("age_group"),
        "category": v.get("category"),
        "language_code": v.get("language_code"),
        "description": v.get("description"),
        "status": v.get("status"),
        "active": v.get("active"),
        "has_dubbing": v.get("has_dubbing"),
        "demo": v.get("demo"),
        "image": v.get("image"),
        "sample_audios": sample_audios,
    }


def fetch_page(token, cursor=None, limit=20, timeout=30):
    params = {"limit": limit, "voiceOwnership": "COMMUNITY", "sort": "publishAt_desc"}
    if cursor:
        params["cursor"] = cursor
    url = API_URL + "?" + urlencode(params)
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": "Bearer " + token,
        "origin": "https://studio.vbee.vn",
        "referer": "https://studio.vbee.vn/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155.0.0.0 Safari/537.36",
    }
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    if payload.get("status") != 1 or not isinstance(payload.get("result"), dict):
        raise RuntimeError("Response API khong bao thanh cong: " + str(payload.get("status")))
    return payload


def export_all(token, destination, page_limit=20, max_pages=500, delay=1.5, fetch_fn=fetch_page):
    unique = {}
    cursor = None  # Bắt đầu từ trang đầu; KHÔNG dùng cursor của trang giữa.
    seen_cursors = set()
    completed = False
    page_count = 0

    try:
        for page_idx in range(max_pages):
            payload = fetch_fn(token, cursor, page_limit)
            result = payload["result"]
            rows = result.get("voices") or []
            for voice in rows:
                if not isinstance(voice, dict):
                    continue
                key = str(voice.get("id") or voice.get("code") or "").strip()
                if key:
                    unique[key] = clean_voice(voice)
            page_count += 1
            pagination = result.get("pagination") or {}
            has_more = bool(pagination.get("has_next_page"))
            print(f"Trang {page_count}: {len(rows)} giong, tong khong trung {len(unique)}.")
            # Cứ qua 1 trang lại lưu; tránh mất dữ liệu nếu mất mạng hoặc token hết hạn.
            save_catalog(destination, list(unique.values()), page_count, complete=not has_more)
            if not has_more:
                completed = True
                break
            next_cursor = pagination.get("next_cursor")
            if not next_cursor or next_cursor in seen_cursors:
                print("API bao con trang nhung cursor bi thieu / lap. Dung de tranh lap vo han.")
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if delay > 0:
                time.sleep(delay)
        else:
            print(f"Da den gioi han an toan {max_pages} trang, can kiem tra truoc khi tiep tuc.")
    except HTTPError as e:
        if e.code in (401, 403):
            print(f"HTTP {e.code}: Token het han / khong co quyen. Khong thu lai bang token khac tu dong.")
        elif e.code == 429:
            print("HTTP 429: Qua gioi han tan suat. Dung va giu file da thu thap.")
        else:
            print(f"HTTP {e.code}: Dung, giu du lieu da lay.")
    except (URLError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as e:
        print(f"Loi khi doc API: {type(e).__name__}. Dung, giu file da thu thap.")
    finally:
        save_catalog(destination, list(unique.values()), page_count, completed)

    print(f"Xong: {len(unique)} giong, {page_count} trang. Trang thai: {'DU' if completed else 'CHUA DU'}.")
    print("File:", destination.resolve())
    return unique, completed


def save_catalog(path, voices, page_count, complete):
    payload = {
        "source": "vbee.vn/api/v3/voices",
        "voice_ownership": "COMMUNITY",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages_collected": page_count,
        "complete": complete,
        "voice_count": len(voices),
        "voices": voices,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Lấy danh sách giọng COMMUNITY Vbee qua cursor, không tải audio.")
    parser.add_argument("--limit", type=int, default=20, help="Số giọng mỗi trang (mặc định 20)")
    parser.add_argument("--max-pages", type=int, default=500, help="Số trang tối đa để tránh lặp")
    parser.add_argument("--delay", type=float, default=1.5, help="Giây nghỉ giữa các request")
    parser.add_argument("--output", default="vbee_community_all.json", help="File JSON xuất")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit phải từ 1 đến 100 (chỉ thử cao hơn 20 nếu API hỗ trợ)")
    if args.max_pages <= 0 or args.delay < 0:
        parser.error("--max-pages phải > 0 và --delay >= 0")
    print("Chi nhap token tu PHIEN DANG NHAP CUA CHINH BAN. Token khong duoc luu.")
    token = getpass.getpass("Bearer JWT (co the dan 'Bearer ...'): ").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print("Chua co token.")
        return 2
    export_all(token, Path(args.output), page_limit=args.limit, max_pages=args.max_pages, delay=args.delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
