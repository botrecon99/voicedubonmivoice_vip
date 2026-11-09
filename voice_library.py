# -*- coding: utf-8 -*-
"""SYNC V3.1 - Vbee preview importer and live local voice manager.

Voice list is the real voices/ directory. The Vbee library is the OFFICIAL site
opened in a dedicated Chrome window; there is no fabricated voice catalogue or
undocumented Vbee API. Selenium may observe public sample MP3 URLs loaded while
playing previews. Users can paste their own sample URL if browser capture fails.

This module does not log in to Vbee or bypass authentication, and downloading a
sample is not a license to clone another person's voice. Import only samples
whose reuse you are authorized to make.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import wave
import webbrowser

import customtkinter as ctk
from tkinter import messagebox

try:
    import requests
except ImportError:
    requests = None

VOICE_LIBRARY_URL = 'https://studio.vbee.vn/studio/voice-library'
SAMPLE_HOST = 'vbee-studio-tmp.s3.ap-southeast-1.amazonaws.com'
MAX_SAMPLE_SIZE = 30 * 1024 * 1024
AUDIO_EXTENSIONS = ('.wav', '.mp3', '.m4a')


def list_local_voices(voices_dir):
    os.makedirs(voices_dir, exist_ok=True)
    seen = set()
    result = []
    for filename in sorted(os.listdir(voices_dir), key=str.casefold):
        path = os.path.join(voices_dir, filename)
        if not os.path.isfile(path):
            continue
        name, ext = os.path.splitext(filename)
        if ext.lower() not in AUDIO_EXTENSIONS:
            continue
        if name.casefold() not in seen:
            result.append(name)
            seen.add(name.casefold())
    return result


def voice_name_safe(name):
    name = (name or '').strip()
    if '/' in name or '\\' in name or '..' in name:
        raise ValueError('Tên giọng không được chứa dấu gạch thư mục hoặc ..')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip(' .')[:64].strip(' .')
    if not name or name.upper() in {'CON','PRN','AUX','NUL','COM1','COM2','LPT1','LPT2'}:
        raise ValueError('Hãy nhập tên giọng hợp lệ, không có ký tự đặc biệt của Windows.')
    return name


def is_vbee_sample_url(url):
    try:
        parsed = urllib.parse.urlsplit((url or '').strip())
        return (parsed.scheme == 'https'
                and parsed.hostname == SAMPLE_HOST
                and parsed.port in (None, 443)
                and parsed.path.startswith('/voice-cloning/samples/')
                and re.search(r'\.(?:mp3|wav)(?:\.mp3)?$', parsed.path, re.I) is not None
                and not parsed.username and not parsed.password)
    except (ValueError, AttributeError):
        return False


def sample_id_from_url(url):
    match = re.search(r'/samples/(voice-[a-zA-Z0-9_-]+)/', url or '')
    if match:
        return match.group(1)
    return os.path.basename(urllib.parse.urlsplit(url).path)[:30]


def _find_ffmpeg(base_dir):
    local = os.path.join(base_dir, 'ffmpeg.exe')
    if os.path.isfile(local):
        return local
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError):
        return None


def download_and_prepare_sample(url, voice_name, voices_dir, ffmpeg_exe, *, overwrite=False,
                                http_get=None):
    """Fetch a preview in a bounded stream, decode clean mono WAV, commit atomically.

    The original preview is stored in voices/_vbee_originals; the converted WAV
    goes directly in voices for the existing OmniVoice lookup and cache logic.
    No credentials/cookies, redirects, or undocumented endpoints are used.
    """
    if not is_vbee_sample_url(url):
        raise ValueError('Chỉ nhận link HTTPS MP3 mẫu từ vbee-studio-tmp.s3.../voice-cloning/samples/.')
    name = voice_name_safe(voice_name)
    if not ffmpeg_exe:
        raise RuntimeError('Cần ffmpeg.exe trong thư mục tool hoặc ffmpeg trong PATH.')
    if requests is None and http_get is None:
        raise RuntimeError('Thiếu requests. Chạy: pip install requests')
    os.makedirs(voices_dir, exist_ok=True)
    dest = os.path.join(voices_dir, name + '.wav')
    if os.path.isfile(dest) and not overwrite:
        raise FileExistsError('Giọng này đã có. Hãy đổi tên hoặc xác nhận ghi đè.')

    get = http_get or requests.get
    with tempfile.TemporaryDirectory(prefix='vbee_preview_') as tmp:
        mp3 = os.path.join(tmp, 'sample.mp3')
        wav = os.path.join(tmp, 'reference.wav')
        resp = get(url, stream=True, timeout=(12, 45), allow_redirects=False)
        try:
            if not (200 <= resp.status_code < 300):
                raise RuntimeError(f'Vbee/S3 trả HTTP {resp.status_code}; mẫu có thể hết hạn hoặc không còn công khai.')
            total = 0
            with open(mp3, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SAMPLE_SIZE:
                        raise RuntimeError('File mẫu lớn hơn 30 MB, đã dừng tải để bảo vệ máy.')
                    f.write(chunk)
        finally:
            resp.close()
        if total < 1024:
            raise ValueError('Mẫu tải về quá nhỏ, không phải file âm thanh hợp lệ.')
        with open(mp3, 'rb') as f:
            prefix = f.read(48).lstrip().lower()
        if prefix.startswith((b'<html', b'<!doctype', b'{', b'<?xml')):
            raise ValueError('Server trả HTML/JSON thay vì âm thanh, không thể nhập mẫu.')
        cmd = [ffmpeg_exe, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', mp3, '-t', '30', '-vn', '-ac', '1', '-ar', '24000',
               '-c:a', 'pcm_s16le', wav]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
        if run.returncode or not os.path.isfile(wav):
            raise ValueError('Không giải mã được mẫu âm thanh: ' + (run.stderr or '')[-500:])
        with wave.open(wav, 'rb') as w:
            seconds = w.getnframes() / max(1, w.getframerate())
            if seconds < 1.5:
                raise ValueError(f'Giọng mẫu chỉ {seconds:.2f}s, quá ngắn để dùng ổn định.')
        originals = os.path.join(voices_dir, '_vbee_originals')
        os.makedirs(originals, exist_ok=True)
        copy_mp3 = os.path.join(originals, name + '.mp3')
        if os.path.exists(copy_mp3) and not overwrite:
            raise FileExistsError('Bản MP3 của giọng cùng tên đã tồn tại.')
        # The validated WAV is the actual voice reference consumed by OmniVoice.
        os.replace(wav, dest)
        # An archival copy; if it cannot be saved, the usable WAV remains safe.
        shutil.copy2(mp3, copy_mp3)
        return {'name': name, 'wav_path': dest, 'sample_path': copy_mp3,
                'duration': round(seconds, 2), 'bytes': total}


class VbeeLibraryWindow(ctk.CTkToplevel):
    """Preview on official Vbee browser and choose the last captured audio sample."""

    def __init__(self, parent, base_dir, on_imported):
        super().__init__(parent)
        self.base_dir = base_dir
        self.voices_dir = os.path.join(base_dir, 'voices')
        self.on_imported = on_imported
        self.title('Thư viện giọng Vbee | SYNC V3.1')
        self.geometry('740x630')
        self.minsize(640, 550)
        self.configure(fg_color='#151515')
        self._queue = queue.Queue()
        self._browser_thread = None
        self._stop_browser = threading.Event()
        self._seen = set()
        self._recent = []
        self._downloading = False
        self._auto_name = None
        self._last_preview_at = 0
        self._build()
        self.after(180, self._process_queue)
        self.protocol('WM_DELETE_WINDOW', self._close)

    def _build(self):
        ctk.CTkLabel(self, text='THƯ VIỆN GIỌNG VBEE', font=ctk.CTkFont(size=19, weight='bold'),
                     text_color='#d4af37').pack(anchor='w', padx=22, pady=(18, 5))
        ctk.CTkLabel(self, text=('Mở thư viện thật của Vbee, chọn giọng và nhấn Nghe thử trên trang. '
                                 'App sẽ tự bắt URL MP3 mẫu nếu Chrome/Selenium hỗ trợ.'),
                     wraplength=690, justify='left').pack(anchor='w', padx=22, pady=(0, 12))

        top = ctk.CTkFrame(self, fg_color='transparent')
        top.pack(fill='x', padx=22)
        self.browser_button = ctk.CTkButton(top, text='🌐 MỞ THƯ VIỆN GIỌNG VBEE',
                                              command=self._open_browser, width=290)
        self.browser_button.pack(side='left', padx=(0, 8))
        ctk.CTkButton(top, text='Mở bằng trình duyệt mặc định',
                      command=lambda: webbrowser.open(VOICE_LIBRARY_URL),
                      fg_color='#3b3b3b').pack(side='left')
        self.status = ctk.CTkLabel(self, text='Chưa mở trình duyệt. Có thể dán link F12 thủ công bên dưới.',
                                   wraplength=690, text_color='#a9bdc7')
        self.status.pack(anchor='w', padx=22, pady=(10, 9))

        ctk.CTkLabel(self, text='MẪU VỪA NGHE THỬ (MỚI NHẤT Ở TRÊN)',
                     font=ctk.CTkFont(weight='bold', size=12)).pack(anchor='w', padx=22)
        self.recent_scroll = ctk.CTkScrollableFrame(self, height=155, fg_color='#202020')
        self.recent_scroll.pack(fill='x', padx=22, pady=(6, 8))
        self._render_recent()

        ctk.CTkLabel(self, text='Link mẫu MP3 (tự bắt từ Chrome hoặc dán link Network/F12):',
                     font=ctk.CTkFont(size=12)).pack(anchor='w', padx=22)
        self.url_entry = ctk.CTkEntry(self, placeholder_text='https://vbee-studio-tmp.s3.ap-southeast-1.amazonaws.com/voice-cloning/samples/...', height=36)
        self.url_entry.pack(fill='x', padx=22, pady=(4, 10))

        ctk.CTkLabel(self, text='Tên giọng sẽ hiện trong app:',
                     font=ctk.CTkFont(size=12)).pack(anchor='w', padx=22)
        self.name_entry = ctk.CTkEntry(self, placeholder_text='Ví dụ: Vbee Nu mien Bac 01', height=36)
        self.name_entry.pack(fill='x', padx=22, pady=(4, 12))
        controls = ctk.CTkFrame(self, fg_color='transparent')
        controls.pack(fill='x', padx=22)
        self.import_button = ctk.CTkButton(controls, text='✓ CHỌN GIỌNG NÀY • TẢI VÀO voices',
                                            fg_color='#ca9f2a', text_color='black',
                                            command=self._start_download, height=42)
        self.import_button.pack(side='left', fill='x', expand=True, padx=(0, 10))
        ctk.CTkButton(controls, text='📂 Mở thư mục voices', fg_color='#414141',
                      command=self._open_voices_folder, height=42).pack(side='left')
        self.note = ctk.CTkLabel(self, text=('Ghi chú: Mẫu nghe thử có thể bị giới hạn quyền sử dụng. '
                  'Chỉ nhập để tạo giọng khi bạn có quyền dùng/nhân bản giọng đó.'),
                  text_color='#bfb8a7', wraplength=675, justify='left')
        self.note.pack(anchor='w', padx=22, pady=(13, 8))

    def _open_voices_folder(self):
        os.makedirs(self.voices_dir, exist_ok=True)
        if os.name == 'nt':
            os.startfile(self.voices_dir)
        else:
            webbrowser.open('file://' + self.voices_dir)

    def _open_browser(self):
        if self._browser_thread and self._browser_thread.is_alive():
            self.status.configure(text='Chrome thư viện đang mở. Hãy nghe thử trên trang Vbee.')
            return
        self._stop_browser.clear()
        self.browser_button.configure(state='disabled')
        self.status.configure(text='Đang mở Chrome riêng để nghe thử và tự bắt link MP3...')
        self._browser_thread = threading.Thread(target=self._browser_worker, daemon=True)
        self._browser_thread.start()

    def _browser_worker(self):
        driver = None
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            opts.add_argument('--user-data-dir=' + os.path.join(self.base_dir, 'vbee_chrome_profile'))
            opts.add_argument('--window-size=1240,850')
            opts.add_argument('--no-first-run')
            opts.add_argument('--disable-notifications')
            opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            driver = webdriver.Chrome(options=opts)
            driver.execute_cdp_cmd('Network.enable', {})
            driver.get(VOICE_LIBRARY_URL)
            self._queue.put(('status', 'Đã mở thư viện Vbee. Nhấn Nghe thử trên website để bắt mẫu MP3.'))
            while not self._stop_browser.is_set():
                try:
                    for item in driver.get_log('performance'):
                        try:
                            event = json.loads(item['message'])['message']
                            method = event.get('method', '')
                            params = event.get('params', {})
                            if method == 'Network.responseReceived':
                                resp = params.get('response', {})
                                url = resp.get('url', '')
                                if int(resp.get('status', 0)) >= 300:
                                    continue
                            elif method == 'Network.requestWillBeSent':
                                url = params.get('request', {}).get('url', '')
                            else:
                                continue
                            if is_vbee_sample_url(url):
                                self._queue.put(('preview', url))
                        except (ValueError, KeyError, TypeError):
                            continue
                except Exception as e:
                    self._queue.put(('status', 'Chrome đã đóng hoặc không đọc được Network: ' + str(e)[:100]))
                    break
                time.sleep(0.6)
        except Exception as e:
            self._queue.put(('browser_error', str(e)))
            webbrowser.open(VOICE_LIBRARY_URL)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self._queue.put(('browser_closed', None))

    def _process_queue(self):
        try:
            while True:
                typ, data = self._queue.get_nowait()
                if typ == 'preview':
                    if (self._recent and data == self._recent[0]
                            and time.monotonic() - self._last_preview_at < 1.5):
                        continue
                    self._last_preview_at = time.monotonic()
                    if data in self._seen:
                        # If they replay an earlier voice, move it to the top.
                        self._recent = [u for u in self._recent if u != data]
                    self._seen.add(data)
                    self._recent.insert(0, data)
                    self._recent = self._recent[:10]
                    self.url_entry.delete(0, 'end')
                    self.url_entry.insert(0, data)
                    if (not self.name_entry.get().strip()
                            or self.name_entry.get() == self._auto_name):
                        vid = sample_id_from_url(data).replace('voice-', '')[:12]
                        new_name = 'Vbee_' + vid
                        self.name_entry.delete(0, 'end')
                        self.name_entry.insert(0, new_name)
                        self._auto_name = new_name
                    self.status.configure(text='✓ Đã bắt được mẫu từ Vbee: ' + sample_id_from_url(data))
                    self._render_recent()
                elif typ == 'status':
                    self.status.configure(text=data)
                elif typ == 'browser_error':
                    self.status.configure(text='Không thể tự bắt link (Selenium/Chrome): ' + data[:130] +
                                          '. Đã mở trang thường; có thể dán link F12 thủ công.')
                elif typ == 'browser_closed':
                    self.browser_button.configure(state='normal')
                elif typ == 'saved':
                    self._downloading = False
                    self.import_button.configure(state='normal')
                    self.status.configure(text='✓ Đã lưu ' + data['wav_path'])
                    self.on_imported(data['name'])
                    messagebox.showinfo('Đã thêm giọng',
                                        f"Đã chọn giọng: {data['name']}\n" 
                                        f"WAV: {data['wav_path']}\nMẫu dài: {data['duration']} giây\n"
                                        'Giọng đã có ngay trong danh sách, không cần khởi động lại app.')
                elif typ == 'save_error':
                    self._downloading = False
                    self.import_button.configure(state='normal')
                    messagebox.showerror('Không tải được mẫu', data)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(180, self._process_queue)

    def _render_recent(self):
        for child in self.recent_scroll.winfo_children():
            child.destroy()
        if not self._recent:
            ctk.CTkLabel(self.recent_scroll,
                         text='Chưa có mẫu. Trên Chrome Vbee, chọn một giọng → Nghe thử.',
                         text_color='#aaa').pack(anchor='w', padx=10, pady=10)
            return
        for ix, link in enumerate(self._recent):
            vid = sample_id_from_url(link)
            label = ('Mới nhất • ' if ix == 0 else '') + vid
            ctk.CTkButton(self.recent_scroll, text=label, anchor='w', fg_color='#303030',
                          command=lambda u=link: self._choose_url(u)).pack(fill='x', padx=6, pady=3)

    def _choose_url(self, url):
        self.url_entry.delete(0, 'end')
        self.url_entry.insert(0, url)
        if not self.name_entry.get().strip() or self.name_entry.get() == self._auto_name:
            new_name = 'Vbee_' + sample_id_from_url(url).replace('voice-', '')[:12]
            self.name_entry.delete(0, 'end')
            self.name_entry.insert(0, new_name)
            self._auto_name = new_name
        self.status.configure(text='Đã chọn mẫu: ' + sample_id_from_url(url))

    def _start_download(self):
        if self._downloading:
            return
        url = self.url_entry.get().strip()
        name = self.name_entry.get().strip()
        try:
            if not is_vbee_sample_url(url):
                raise ValueError('Chưa có link MP3 mẫu hợp lệ. Hãy nghe thử ở Vbee hoặc dán URL F12.')
            name = voice_name_safe(name)
        except ValueError as e:
            messagebox.showwarning('Thiếu dữ liệu', str(e))
            return
        dest = os.path.join(self.voices_dir, name + '.wav')
        overwrite = os.path.isfile(dest)
        if overwrite and not messagebox.askyesno('Trùng tên giọng',
                        f'Đã có giọng {name}. Ghi đè mẫu mới và tạo lại cache TTS ở lượt render sau?'):
            return
        if not messagebox.askyesno('Xác nhận quyền sử dụng',
                        'Bạn có quyền sử dụng bản mẫu này làm tham chiếu để nhân bản giọng ngoài Vbee không?\n'
                        'Chỉ tiếp tục khi bạn có quyền hoặc sự đồng ý cần thiết.'):
            return
        ffmpeg = _find_ffmpeg(self.base_dir)
        if not ffmpeg:
            messagebox.showerror('Thiếu ffmpeg', 'Đặt ffmpeg.exe cạnh core.py hoặc cài FFmpeg vào PATH.')
            return
        self._downloading = True
        self.import_button.configure(state='disabled')
        self.status.configure(text='Đang tải và chuyển mẫu sang WAV để dùng cho OmniVoice...')
        threading.Thread(target=self._download_worker, args=(url, name, ffmpeg, overwrite), daemon=True).start()

    def _download_worker(self, url, name, ffmpeg, overwrite):
        try:
            result = download_and_prepare_sample(url, name, self.voices_dir, ffmpeg,
                                                 overwrite=overwrite)
            self._queue.put(('saved', result))
        except Exception as e:
            self._queue.put(('save_error', str(e)))

    def _close(self):
        self._stop_browser.set()
        self.destroy()
