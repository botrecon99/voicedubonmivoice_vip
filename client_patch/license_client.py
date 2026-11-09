# -*- coding: utf-8 -*-
"""Online license client for AI Dubbing Studio. No HWID / no device binding.

IMPORTANT: A Python-only client is not tamper-proof DRM. This validates online
before opening the UI and before each pipeline request. Keep server secrets on
Cloudflare Worker only; never ship ADMIN_TOKEN with the app.
"""
import hashlib
import json
import os
import platform
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP_VERSION = '3.4.6'
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'license_config.json'
USER_DIR = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AI_Dubbing_Studio')
SAVED_PATH = USER_DIR / 'license.json'
MAX_RESPONSE = 128 * 1024
MAX_DOWNLOAD = 2 * 1024 ** 3  # 2GiB cap


class LicenseError(RuntimeError):
    pass


def _load_json_file(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return default


def api_base():
    raw = str(_load_json_file(CONFIG_PATH, {}).get('api_url', '')).strip().rstrip('/')
    p = urllib.parse.urlsplit(raw)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise LicenseError('Chưa cấu hình URL HTTPS của Cloudflare Worker trong license_config.json.')
    return raw


def saved_key():
    return str(_load_json_file(SAVED_PATH, {}).get('key', '')).strip().upper()


def save_key(key):
    USER_DIR.mkdir(parents=True, exist_ok=True)
    data = {'key': str(key).strip().upper()}
    fd, temp = tempfile.mkstemp(prefix='license_', suffix='.tmp', dir=str(USER_DIR))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(temp, SAVED_PATH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def clear_key():
    try:
        SAVED_PATH.unlink()
    except FileNotFoundError:
        pass


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != 'https':
            raise LicenseError('Chuyển hướng tải không an toàn (không dùng HTTPS).')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(HttpsOnlyRedirect())


def _post(path, data, timeout=12):
    url = api_base() + path
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=raw, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'AI-Dubbing-Studio/' + APP_VERSION,
    }, method='POST')
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            content = resp.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read(MAX_RESPONSE).decode('utf-8'))
            message = detail.get('error') or 'HTTP ' + str(e.code)
        except (ValueError, UnicodeError):
            message = 'HTTP ' + str(e.code)
        raise LicenseError(str(message)) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LicenseError('Không kết nối được máy chủ license. Kiểm tra Internet rồi thử lại.') from e
    if len(content) > MAX_RESPONSE:
        raise LicenseError('Phản hồi máy chủ quá lớn.')
    try:
        payload = json.loads(content.decode('utf-8'))
    except (UnicodeError, ValueError) as e:
        raise LicenseError('Máy chủ license trả dữ liệu không hợp lệ.') from e
    if not isinstance(payload, dict) or not payload.get('ok'):
        raise LicenseError(str(payload.get('error', 'License không hợp lệ')) if isinstance(payload, dict) else 'Phản hồi không hợp lệ')
    return payload


def validate_license(key=None, timeout=12):
    val = (key or saved_key()).strip().upper()
    if not re.fullmatch(r'ADS(?:-[A-HJ-NP-Z2-9]{6}){4}', val):
        raise LicenseError('Chưa có license key hoặc mã sai định dạng.')
    # Deliberately do not transmit MAC address, disk ID, IP-derived HWID or fingerprint.
    return _post('/api/validate', {'key': val, 'client_version': APP_VERSION}, timeout)


def require_active_license():
    """Online check before each extract/render/TTS operation (fail closed)."""
    payload = validate_license()
    if payload.get('update_required'):
        ver = (payload.get('latest_version') or {}).get('version', '?')
        raise LicenseError('Cần cập nhật bản ' + ver + ' trước khi xử lý video. Mở mục License & Phiên bản.')
    return payload


def short_key(key):
    if len(key) < 16:
        return 'Chưa có key'
    return key[:4] + '-******-******-******-' + key[-6:]


def download_update(release, progress=None, download_dir=None):
    """Download verified ZIP, never execute or extract an update automatically."""
    if not isinstance(release, dict):
        raise LicenseError('Chưa có thông tin bản cập nhật.')
    version = str(release.get('version', ''))
    url = str(release.get('download_url', ''))
    expected = str(release.get('sha256', '')).lower()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise LicenseError('Số phiên bản không hợp lệ.')
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise LicenseError('Bản cập nhật thiếu SHA256 hợp lệ.')
    uri = urllib.parse.urlsplit(url)
    if uri.scheme != 'https' or not uri.hostname:
        raise LicenseError('URL cập nhật phải dùng HTTPS.')
    dest_dir = Path(download_dir) if download_dir else Path.home() / 'Downloads'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ('AI_Dubbing_Studio_Update_v' + version + '.zip')
    part = dest.with_suffix('.zip.part')
    h = hashlib.sha256()
    received = 0
    req = urllib.request.Request(url, headers={'User-Agent': 'AI-Dubbing-Studio/' + APP_VERSION})
    try:
        with _OPENER.open(req, timeout=40) as source, part.open('wb') as f:
            # Avoid redirects to unsafe schemes or URLs without TLS.
            if urllib.parse.urlsplit(source.geturl()).scheme.lower() != 'https':
                raise LicenseError('Đường dẫn cập nhật không an toàn.')
            length_str = source.headers.get('Content-Length', '0')
            total = int(length_str) if length_str.isdigit() else 0
            if total > MAX_DOWNLOAD:
                raise LicenseError('File cập nhật lớn hơn giới hạn 2GB.')
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk: break
                received += len(chunk)
                if received > MAX_DOWNLOAD:
                    raise LicenseError('File cập nhật vượt giới hạn 2GB.')
                f.write(chunk)
                h.update(chunk)
                if progress: progress(received, total)
        if h.hexdigest() != expected:
            raise LicenseError('SHA256 KHÔNG KHỚP. Đã hủy file tải để bảo vệ phần mềm.')
        # Check ZIP signature but do not extract/execute (avoids accidental overwrite).
        with part.open('rb') as check:
            if check.read(4) != b'PK\x03\x04':
                raise LicenseError('File cập nhật không phải ZIP hợp lệ.')
        os.replace(part, dest)
    except Exception:
        try: part.unlink()
        except OSError: pass
        raise
    return dest
