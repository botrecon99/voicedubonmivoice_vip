# -*- coding: utf-8 -*-
import io
import os
import sys
import json
import time
import queue
import ctypes
import shutil
import tempfile
import threading
import math
import tkinter as tk
import subprocess
import platform
import webbrowser
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

import requests
import customtkinter as ctk
from PIL import Image, ImageOps, ImageDraw
from tkinter import filedialog, messagebox

import whisper

if platform.system() == 'Windows':
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from core import run_process, cancel_event, extract_video_id, YouTubeProExtractor
from role_review_ui import RoleReviewDialog

if sys.version_info >= (3, 8):
    from importlib import metadata
    def mock_version(name):
        return "2.37.3"
    metadata.version = mock_version

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ===== Theme =====
APP_BG = "#0d1117"
PANEL_BG = "#161b22"
CARD_BG = "#1f2630"
CARD_BG_2 = "#242d38"
BORDER = "#30363d"
TEXT = "#f0f6fc"
TEXT_DIM = "#8b949e"
ACCENT = "#f2b94b"
ACCENT_2 = "#2f81f7"
SUCCESS = "#2ea043"
DANGER = "#da3633"

WINDOW_TITLE = "AI Dubbing Studio • V3.4.6 • License Manager"
VBEE_JSON_NAME = "vbee_community_all.json"
VOICES_DIR = os.path.join(BASE_DIR, "voices")

# ===== Helpers =====
def safe_startfile(path: str):
    try:
        os.startfile(path)
    except Exception:
        try:
            if platform.system() == 'Darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception:
            pass


def truncate_text(text, limit=120):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def sanitize_filename(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in (' ', '-', '_'):
            keep.append(ch)
        else:
            keep.append('_')
    cleaned = ''.join(keep).strip().replace(' ', '_')
    while '__' in cleaned:
        cleaned = cleaned.replace('__', '_')
    return cleaned[:80] or f"voice_{int(time.time())}"


def get_ffmpeg_path():
    local = os.path.join(BASE_DIR, "ffmpeg.exe")
    if os.path.exists(local):
        return local
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_ffplay_path():
    direct = os.path.join(BASE_DIR, "ffplay.exe")
    if os.path.exists(direct):
        return direct
    ffmpeg = get_ffmpeg_path()
    if ffmpeg:
        ffplay = os.path.join(os.path.dirname(ffmpeg), 'ffplay.exe')
        if os.path.exists(ffplay):
            return ffplay
    return None


class ImageCache:
    """Bounded cache and bounded image downloader; Tk never waits for images."""
    def __init__(self):
        self.cache = OrderedDict()
        self.pending = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='vbee_img')
        self.placeholder = self._make_placeholder(56, 56)

    def _make_placeholder(self, w, h):
        img = Image.new('RGB', (w, h), '#2d333b')
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, w-4, h-4), fill='#39424e')
        draw.ellipse((18, 12, 38, 32), fill='#768390')
        draw.rounded_rectangle((14, 31, 42, 46), radius=8, fill='#768390')
        return ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))

    def get_placeholder(self):
        return self.placeholder

    def fetch_async(self, url, callback, size=(56, 56)):
        if not url or urlparse(url).path.lower().endswith('.svg'):
            # Vbee's default avatars are SVG. Pillow doesn't decode SVG.
            callback(self.placeholder)
            return
        key = (url, size)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                img = self.cache[key]
                hit = True
            else:
                img = None
                hit = False
                if key in self.pending:
                    self.pending[key].append(callback)
                    return
                if len(self.pending) >= 40:
                    # Avoid queueing hundreds of off-screen images on fast scroll.
                    img = self.placeholder
                    hit = True
                else:
                    self.pending[key] = [callback]
        if hit:
            callback(img)
            return

        def worker():
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                if len(resp.content) > 5_000_000:
                    raise ValueError('Image too large')
                image = Image.open(io.BytesIO(resp.content)).convert('RGB')
                image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
                result = ctk.CTkImage(light_image=image, dark_image=image, size=size)
            except Exception:
                result = self.placeholder
            with self.lock:
                callbacks = self.pending.pop(key, [])
                self.cache[key] = result
                self.cache.move_to_end(key)
                if len(self.cache) > 160:
                    self.cache.popitem(last=False)
            for cb in callbacks:
                cb(result)
        self.executor.submit(worker)


class AudioPreviewPlayer:
    def __init__(self):
        self.proc = None
        self.temp_file = None
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def play_url(self, url: str):
        self.stop()
        if not url:
            raise RuntimeError("Giọng này không có link nghe thử.")

        tmp_dir = os.path.join(tempfile.gettempdir(), 'omnivoice_vbee_preview')
        os.makedirs(tmp_dir, exist_ok=True)
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1] or '.mp3'
        self.temp_file = os.path.join(tmp_dir, f'preview_{int(time.time()*1000)}{ext}')
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        with open(self.temp_file, 'wb') as f:
            f.write(r.content)

        ffplay = get_ffplay_path()
        if ffplay and os.path.exists(ffplay):
            self.proc = subprocess.Popen([ffplay, '-nodisp', '-autoexit', '-loglevel', 'quiet', self.temp_file])
        else:
            safe_startfile(self.temp_file)


class LanguageSearchDialog(ctk.CTkToplevel):
    def __init__(self, parent, map_data, callback_select, title_text="🔍 Bộ Tìm Kiếm Ngôn Ngữ"):
        super().__init__(parent)
        self.title(title_text)
        self.geometry("520x620")
        self.configure(fg_color=APP_BG)
        self.transient(parent)
        self.grab_set()

        self.map_data = map_data
        self.callback_select = callback_select
        self.all_keys = sorted(list(map_data.keys()))
        self.filtered = self.all_keys

        top = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16, border_color=BORDER, border_width=1)
        top.pack(fill='both', expand=True, padx=16, pady=16)

        ctk.CTkLabel(top, text=title_text, font=ctk.CTkFont(size=18, weight='bold'), text_color=TEXT).pack(anchor='w', padx=16, pady=(16, 8))
        self.search_entry = ctk.CTkEntry(top, height=40, placeholder_text="Nhập từ khóa, ví dụ: Vietnamese / English / Japanese")
        self.search_entry.pack(fill='x', padx=16, pady=(0, 12))
        self.search_entry.bind('<KeyRelease>', self.filter_languages)

        self.scroll = ctk.CTkScrollableFrame(top, fg_color='transparent')
        self.scroll.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.buttons = []
        self.populate(self.filtered)
        self.search_entry.focus()

    def populate(self, items):
        for btn in self.buttons:
            btn.destroy()
        self.buttons.clear()
        for name in items[:200]:
            btn = ctk.CTkButton(self.scroll, text=name, fg_color=CARD_BG, hover_color=CARD_BG_2, anchor='w',
                                command=lambda n=name: self.select_language(n))
            btn.pack(fill='x', padx=8, pady=4)
            self.buttons.append(btn)

    def filter_languages(self, _event=None):
        keyword = self.search_entry.get().strip().lower()
        if not keyword:
            self.filtered = self.all_keys
        else:
            self.filtered = [x for x in self.all_keys if keyword in x.lower()]
        self.populate(self.filtered)

    def select_language(self, name):
        self.callback_select(name)
        self.destroy()


class VbeeVoiceLibraryDialog(ctk.CTkToplevel):
    # Only render rows near the viewport. Even a 1,429-voice catalog
    # never creates more than ~10-12 live cards at once.
    ROW_HEIGHT = 136
    ROW_BUFFER = 2

    def __init__(self, parent, json_path, on_voice_imported):
        super().__init__(parent)
        self.parent = parent
        self.json_path = json_path
        self.on_voice_imported = on_voice_imported
        self.title("Thư viện giọng Vbee • Offline")
        self.geometry("1220x780")
        self.minsize(1100, 720)
        self.configure(fg_color=APP_BG)
        self.transient(parent)

        self.image_cache = ImageCache()
        self.audio_player = AudioPreviewPlayer()

        self.search_var = ctk.StringVar(value="")
        self.gender_var = ctk.StringVar(value="Tất cả")
        self.locale_var = ctk.StringVar(value="Tất cả")
        self.only_dubbing_var = ctk.BooleanVar(value=False)  # Show all voices, including records missing has_dubbing
        self.selected_preview_url = None
        self.visible_rows = {}
        self.row_pool = []
        self._render_job = None
        self._search_job = None
        self._wheel_job = None
        self._wheel_target = 0.0

        self.all_voices = self.load_json(json_path)
        self.filtered = []
        self.card_widgets = []
        self._build_ui()
        self.refresh_results()

    def load_json(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Không tìm thấy file thư viện: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        voices = data.get('voices', data if isinstance(data, list) else [])
        return voices

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=18, border_color=BORDER, border_width=1)
        header.pack(fill='x', padx=18, pady=(18, 12))
        ctk.CTkLabel(header, text="🎙️ Thư viện giọng Vbee", font=ctk.CTkFont(size=24, weight='bold'), text_color=TEXT).pack(anchor='w', padx=18, pady=(14, 2))
        ctk.CTkLabel(header, text="Có ảnh • có tên • nghe thử trước • tải về thư mục voices để dùng ngay trong OmniVoice.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(anchor='w', padx=18, pady=(0, 14))

        body = ctk.CTkFrame(self, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=18, pady=(0, 18))

        left = ctk.CTkFrame(body, fg_color=PANEL_BG, corner_radius=18, border_color=BORDER, border_width=1)
        left.pack(side='left', fill='both', expand=True, padx=(0, 10))
        right = ctk.CTkFrame(body, fg_color=PANEL_BG, width=320, corner_radius=18, border_color=BORDER, border_width=1)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)

        # filters
        filter_wrap = ctk.CTkFrame(left, fg_color='transparent')
        filter_wrap.pack(fill='x', padx=16, pady=(16, 10))

        self.search_entry = ctk.CTkEntry(filter_wrap, textvariable=self.search_var, height=40, placeholder_text='Tìm theo tên, tỉnh/thành, mô tả...')
        self.search_entry.grid(row=0, column=0, sticky='ew', padx=(0, 8), pady=(0, 10))
        self.search_entry.bind('<KeyRelease>', self._debounced_filter)
        ctk.CTkButton(filter_wrap, text='Làm mới', width=92, fg_color=ACCENT_2, command=self.refresh_results).grid(row=0, column=1, padx=(0, 0), pady=(0, 10))

        self.gender_segment = ctk.CTkSegmentedButton(filter_wrap, values=['Tất cả', 'male', 'female'], variable=self.gender_var,
                                                     command=lambda _v: self.refresh_results())
        self.gender_segment.grid(row=1, column=0, sticky='ew', padx=(0, 8), pady=(0, 10))
        self.locale_segment = ctk.CTkSegmentedButton(filter_wrap, values=['Tất cả', 'northern', 'central', 'southern'], variable=self.locale_var,
                                                     command=lambda _v: self.refresh_results())
        self.locale_segment.grid(row=1, column=1, sticky='ew', padx=(0, 0), pady=(0, 10))

        self.only_dubbing = ctk.CTkCheckBox(filter_wrap, text='Chỉ hiện giọng xác nhận có dubbing', variable=self.only_dubbing_var,
                                            command=self.refresh_results)
        self.only_dubbing.grid(row=2, column=0, sticky='w', pady=(0, 6))
        filter_wrap.grid_columnconfigure(0, weight=1)
        filter_wrap.grid_columnconfigure(1, weight=0)

        self.count_label = ctk.CTkLabel(left, text='0 kết quả', text_color=TEXT_DIM)
        self.count_label.pack(anchor='w', padx=18, pady=(0, 6))

        # Native Tk canvas + virtual rows: no CTkScrollableFrame and no pagination.
        scroll_wrap = ctk.CTkFrame(left, fg_color='transparent')
        scroll_wrap.pack(fill='both', expand=True, padx=(14, 12), pady=(0, 14))
        self.scroll_canvas = tk.Canvas(
            scroll_wrap, bg=PANEL_BG, highlightthickness=0,
            borderwidth=0, relief='flat', takefocus=1
        )
        self.scrollbar = ctk.CTkScrollbar(
            scroll_wrap, orientation='vertical', width=12,
            command=self._scrollbar_command,
            fg_color=PANEL_BG, button_color='#3a4554',
            button_hover_color='#59677a'
        )
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y', padx=(4, 0))
        self.scroll_canvas.pack(side='left', fill='both', expand=True)
        self.scroll_canvas.bind('<Configure>', self._canvas_resize)
        # Tk event propagation reaches this Toplevel even when mouse is above a card.
        # The pointer guard prevents stealing wheel scroll from the details pane.
        self.bind('<MouseWheel>', self._on_mousewheel, add='+')
        self.bind('<Button-4>', self._on_mousewheel, add='+')
        self.bind('<Button-5>', self._on_mousewheel, add='+')

        # right panel
        ctk.CTkLabel(right, text='🧾 Chi tiết giọng', font=ctk.CTkFont(size=18, weight='bold'), text_color=TEXT).pack(anchor='w', padx=16, pady=(16, 10))
        self.detail_image_label = ctk.CTkLabel(right, text='', image=self.image_cache.get_placeholder())
        self.detail_image_label.pack(anchor='center', pady=(4, 10))
        self.detail_name = ctk.CTkLabel(right, text='Chưa chọn giọng', wraplength=280, justify='left',
                                        font=ctk.CTkFont(size=18, weight='bold'), text_color=TEXT)
        self.detail_name.pack(anchor='w', padx=16)
        self.detail_meta = ctk.CTkLabel(right, text='Chọn một giọng ở bên trái để xem chi tiết.', wraplength=280,
                                        justify='left', text_color=TEXT_DIM)
        self.detail_meta.pack(anchor='w', padx=16, pady=(4, 12))
        self.detail_desc = ctk.CTkTextbox(right, height=180, fg_color=CARD_BG, border_color=BORDER, border_width=1)
        self.detail_desc.pack(fill='both', expand=False, padx=16, pady=(0, 12))
        self.detail_desc.insert('1.0', 'Mô tả giọng sẽ hiện ở đây.')
        self.detail_desc.configure(state='disabled')

        ctk.CTkLabel(right, text='Link nghe thử đang chọn', text_color=TEXT_DIM).pack(anchor='w', padx=16)
        self.preview_url_entry = ctk.CTkEntry(right, height=38)
        self.preview_url_entry.pack(fill='x', padx=16, pady=(4, 12))

        btns = ctk.CTkFrame(right, fg_color='transparent')
        btns.pack(fill='x', padx=16, pady=(0, 16))
        self.play_btn = ctk.CTkButton(btns, text='▶ Nghe thử', fg_color=SUCCESS, command=self.play_selected_preview, state='disabled')
        self.play_btn.pack(fill='x', pady=(0, 8))
        self.stop_btn = ctk.CTkButton(btns, text='⏹ Dừng nghe', fg_color='#30363d', command=self.audio_player.stop)
        self.stop_btn.pack(fill='x', pady=(0, 8))
        self.download_btn = ctk.CTkButton(btns, text='⬇ Tải giọng này vào voices', fg_color=ACCENT, text_color='#111', command=self.download_selected_voice, state='disabled')
        self.download_btn.pack(fill='x')

        ctk.CTkLabel(right, text='Mẹo: giọng được tải về sẽ xuất hiện ngay ở ô chọn giọng chính, không cần tắt app.', wraplength=280,
                     text_color=TEXT_DIM, justify='left').pack(anchor='w', padx=16, pady=(8, 0))

    def set_detail(self, voice):
        self.current_voice = voice
        self.detail_name.configure(text=voice.get('name') or 'Không tên')
        meta = [
            f"Giới tính: {voice.get('gender', 'n/a')}",
            f"Vùng: {voice.get('locale', 'n/a')}",
            f"Tỉnh/TP: {voice.get('province', 'n/a')}",
            f"Danh mục: {voice.get('category', 'n/a')}",
            f"Độ tuổi: {voice.get('age_group', 'n/a')}",
            f"Dubbing: {'Chưa rõ' if voice.get('has_dubbing') is None else ('Có' if voice.get('has_dubbing') else 'Không')}"
        ]
        self.detail_meta.configure(text='\n'.join(meta))
        desc = voice.get('description') or 'Không có mô tả.'
        if voice.get('sample_audios'):
            desc += "\n\nMẫu nghe thử:\n" + '\n'.join(f"• {x.get('title', 'Mẫu')}" for x in voice['sample_audios'][:5])
        self.detail_desc.configure(state='normal')
        self.detail_desc.delete('1.0', 'end')
        self.detail_desc.insert('1.0', desc)
        self.detail_desc.configure(state='disabled')

        preview = self.pick_preview_url(voice)
        self.selected_preview_url = preview
        self.preview_url_entry.delete(0, 'end')
        self.preview_url_entry.insert(0, preview or '')
        self.play_btn.configure(state='normal' if preview else 'disabled')
        self.download_btn.configure(state='normal' if preview else 'disabled')
        self.detail_image_label.configure(image=self.image_cache.get_placeholder())
        detail_id = voice.get('id')
        def set_detail_avatar(img):
            try:
                self.after(0, lambda: self.detail_image_label.configure(image=img)
                           if self.winfo_exists() and self.current_voice.get('id') == detail_id else None)
            except RuntimeError:
                pass
        self.image_cache.fetch_async(voice.get('image'), set_detail_avatar)

    def pick_preview_url(self, voice):
        if voice.get('demo'):
            return voice['demo']
        for item in voice.get('sample_audios', []):
            if item.get('audio_link'):
                return item['audio_link']
        return None

    def _debounced_filter(self, _event=None):
        # Search only after typing settles; never rebuild 1,429 entries per keystroke.
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(170, self.refresh_results)

    def refresh_results(self, reset_page=True):
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
            self._search_job = None
        keyword = self.search_var.get().strip().casefold()
        gender = self.gender_var.get()
        locale = self.locale_var.get()
        only_dubbing = self.only_dubbing_var.get()
        filtered = []
        for v in self.all_voices:
            if gender != 'Tất cả' and (v.get('gender') or '') != gender:
                continue
            if locale != 'Tất cả' and (v.get('locale') or '') != locale:
                continue
            if only_dubbing and not v.get('has_dubbing', False):
                continue
            if keyword:
                hay = ' '.join([
                    str(v.get('name') or ''), str(v.get('province') or ''),
                    str(v.get('locale') or ''), str(v.get('description') or ''),
                    str(v.get('category') or '')
                ]).casefold()
                if keyword not in hay:
                    continue
            filtered.append(v)

        self.filtered = filtered
        count = len(filtered)
        self.count_label.configure(text=f'{count:,} giọng • Cuộn chuột để xem toàn bộ • Không chia trang')
        self.scroll_canvas.configure(scrollregion=(0, 0, 1, max(1, count * self.ROW_HEIGHT)))
        if self._wheel_job is not None:
            self.after_cancel(self._wheel_job)
            self._wheel_job = None
        self._wheel_target = 0.0
        self.scroll_canvas.yview_moveto(0.0)
        self._update_virtual_rows()
        if count:
            self.set_detail(filtered[0])
        else:
            self.detail_name.configure(text='Không có kết quả')

    def _canvas_resize(self, _event=None):
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(40, self._update_virtual_rows)

    def _scrollbar_command(self, *args):
        if self._wheel_job is not None:
            self.after_cancel(self._wheel_job)
            self._wheel_job = None
        self.scroll_canvas.yview(*args)
        self._wheel_target = self.scroll_canvas.canvasy(0)
        self._schedule_virtual_rows()

    def _pointer_on_list(self, event):
        try:
            x, y = event.x_root, event.y_root
            c = self.scroll_canvas
            return (c.winfo_rootx() <= x < c.winfo_rootx() + c.winfo_width()
                    and c.winfo_rooty() <= y < c.winfo_rooty() + c.winfo_height())
        except tk.TclError:
            return False

    def _on_mousewheel(self, event):
        if not self._pointer_on_list(event) or not self.filtered:
            return None
        if getattr(event, 'num', 0) == 4:
            ticks = 1.0
        elif getattr(event, 'num', 0) == 5:
            ticks = -1.0
        else:
            ticks = event.delta / 120.0
        if not ticks:
            return 'break'
        total_height = len(self.filtered) * self.ROW_HEIGHT
        max_offset = max(0.0, total_height - self.scroll_canvas.winfo_height())
        if self._wheel_job is None:
            self._wheel_target = self.scroll_canvas.canvasy(0)
        # 1 wheel notch ~1.2 compact cards. Pixel-target scrolling is
        # independent of platform-specific Tk wheel "units".
        self._wheel_target = min(max_offset, max(0.0, self._wheel_target - ticks * 165.0))
        if self._wheel_job is None:
            self._animate_wheel()
        return 'break'

    def _animate_wheel(self):
        current = self.scroll_canvas.canvasy(0)
        difference = self._wheel_target - current
        if abs(difference) < 1.2:
            self._move_to_offset(self._wheel_target)
            self._wheel_job = None
            return
        # Exponential smoothing at roughly 60 fps.
        self._move_to_offset(current + difference * 0.42)
        self._wheel_job = self.after(16, self._animate_wheel)

    def _move_to_offset(self, pixels):
        total = max(1, len(self.filtered) * self.ROW_HEIGHT)
        self.scroll_canvas.yview_moveto(max(0.0, pixels / total))
        self._schedule_virtual_rows()

    def _schedule_virtual_rows(self):
        if self._render_job is None:
            self._render_job = self.after_idle(self._update_virtual_rows)

    def _update_virtual_rows(self):
        self._render_job = None
        canvas = self.scroll_canvas
        if not canvas.winfo_exists():
            return
        total = len(self.filtered)
        if not total:
            for idx in list(self.visible_rows):
                self._release_row(idx)
            return
        h = max(1, canvas.winfo_height())
        width = max(360, canvas.winfo_width() - 12)
        top = max(0.0, canvas.canvasy(0))
        start = max(0, int(top // self.ROW_HEIGHT) - self.ROW_BUFFER)
        end = min(total, int(math.ceil((top + h) / self.ROW_HEIGHT)) + self.ROW_BUFFER)
        wanted = set(range(start, end))
        for idx in list(self.visible_rows):
            if idx not in wanted:
                self._release_row(idx)
        for idx in range(start, end):
            if idx not in self.visible_rows:
                row = self._acquire_row()
                self.visible_rows[idx] = row
                self._populate_row(row, self.filtered[idx])
            row = self.visible_rows[idx]
            if row.get('visible_at') != idx or row.get('visible_width') != width:
                canvas.coords(row['window_id'], 6, idx * self.ROW_HEIGHT + 3)
                canvas.itemconfigure(row['window_id'], width=width, height=self.ROW_HEIGHT - 7, state='normal')
                row['visible_at'] = idx
                row['visible_width'] = width

    def _release_row(self, idx):
        row = self.visible_rows.pop(idx)
        self.scroll_canvas.itemconfigure(row['window_id'], state='hidden')
        row['visible_at'] = None
        self.row_pool.append(row)

    def _acquire_row(self):
        if self.row_pool:
            return self.row_pool.pop()
        c = self.scroll_canvas
        card = ctk.CTkFrame(c, fg_color=CARD_BG, corner_radius=14, border_color=BORDER, border_width=1,
                            height=self.ROW_HEIGHT - 7)
        card.pack_propagate(False)
        line = ctk.CTkFrame(card, fg_color='transparent')
        line.pack(fill='both', expand=True, padx=11, pady=9)
        avatar = ctk.CTkLabel(line, text='', image=self.image_cache.get_placeholder())
        avatar.pack(side='left', padx=(0, 11))
        buttons = ctk.CTkFrame(line, fg_color='transparent', width=111)
        buttons.pack(side='right', padx=(10, 0))
        buttons.pack_propagate(False)
        detail_button = ctk.CTkButton(buttons, text='Chi tiết', width=104, height=30, fg_color=ACCENT_2)
        detail_button.pack(pady=(0, 4))
        play_button = ctk.CTkButton(buttons, text='▶ Nghe thử', width=104, height=30, fg_color=SUCCESS)
        play_button.pack(pady=(0, 4))
        download_button = ctk.CTkButton(buttons, text='Tải về voices', width=104, height=30, fg_color=ACCENT, text_color='#111')
        download_button.pack()
        info = ctk.CTkFrame(line, fg_color='transparent')
        info.pack(side='left', fill='both', expand=True)
        name = ctk.CTkLabel(info, text='', font=ctk.CTkFont(size=16, weight='bold'), anchor='w', text_color=TEXT)
        name.pack(anchor='w')
        meta = ctk.CTkLabel(info, text='', text_color=TEXT_DIM, anchor='w', font=ctk.CTkFont(size=11))
        meta.pack(anchor='w', pady=(0, 3))
        desc = ctk.CTkLabel(info, text='', wraplength=410, justify='left', text_color='#c9d1d9', anchor='w', font=ctk.CTkFont(size=12))
        desc.pack(anchor='w')
        row = {'card': card, 'avatar': avatar, 'name': name, 'meta': meta, 'desc': desc, 'voice': None}
        detail_button.configure(command=lambda r=row: self.set_detail(r['voice']))
        play_button.configure(command=lambda r=row: self.play_voice(r['voice']))
        download_button.configure(command=lambda r=row: self.download_voice(r['voice']))
        row['window_id'] = c.create_window(6, 0, anchor='nw', window=card, width=400, height=self.ROW_HEIGHT - 7)
        return row

    def _populate_row(self, row, voice):
        row['voice'] = voice
        voice_id = voice.get('id')
        row['name'].configure(text=voice.get('name') or 'Không tên')
        gender_label = {'male': 'Nam', 'female': 'Nữ'}.get(voice.get('gender'), 'Khác')
        region_label = {'northern': 'Miền Bắc', 'central': 'Miền Trung', 'southern': 'Miền Nam'}.get(voice.get('locale'), 'Chưa rõ')
        row['meta'].configure(text=f"{voice.get('category') or 'Khác'}  •  {gender_label}  •  {region_label}  •  {voice.get('province') or ''}")
        row['desc'].configure(text=truncate_text(voice.get('description') or '', 115))
        row['avatar'].configure(image=self.image_cache.get_placeholder())

        def set_avatar(img, r=row, vid=voice_id):
            def ui_update():
                if (self.winfo_exists() and r['voice'] is not None and
                        r['voice'].get('id') == vid and r['avatar'].winfo_exists()):
                    r['avatar'].configure(image=img)
            try:
                self.after(0, ui_update)
            except RuntimeError:
                pass
        self.image_cache.fetch_async(voice.get('image'), set_avatar)

    def play_voice(self, voice):
        self.set_detail(voice)
        self.play_selected_preview()

    def play_selected_preview(self):
        url = self.preview_url_entry.get().strip() or self.selected_preview_url
        if not url:
            messagebox.showwarning('Thiếu link', 'Giọng này chưa có link nghe thử.')
            return

        def worker():
            try:
                self.parent.after(0, lambda: self.parent.set_status_text('Đang tải mẫu nghe thử từ Vbee...'))
                self.audio_player.play_url(url)
                self.parent.after(0, lambda: self.parent.set_status_text('Đang phát mẫu nghe thử.'))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror('Lỗi nghe thử', str(e)))
                self.parent.after(0, lambda: self.parent.set_status_text('Nghe thử thất bại.'))
        threading.Thread(target=worker, daemon=True).start()

    def download_voice(self, voice):
        self.set_detail(voice)
        self.download_selected_voice()

    def download_selected_voice(self):
        voice = getattr(self, 'current_voice', None)
        if not voice:
            messagebox.showwarning('Chưa chọn', 'Hãy chọn một giọng trước.')
            return
        url = self.preview_url_entry.get().strip() or self.selected_preview_url
        if not url:
            messagebox.showwarning('Thiếu link', 'Giọng này không có link tải mẫu.')
            return

        def worker():
            try:
                self.parent.after(0, lambda: self.parent.set_status_text('Đang tải giọng về thư mục voices...'))
                imported = import_vbee_voice_sample(voice, url)
                self.parent.after(0, lambda: self.on_voice_imported(imported))
                self.after(0, lambda: messagebox.showinfo('Thành công', f"Đã tải giọng vào voices:\n{imported}"))
                self.parent.after(0, lambda: self.parent.set_status_text('Đã thêm giọng vào voices.'))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror('Lỗi tải giọng', str(e)))
                self.parent.after(0, lambda: self.parent.set_status_text('Tải giọng thất bại.'))
        threading.Thread(target=worker, daemon=True).start()



def import_vbee_voice_sample(voice: dict, url: str) -> str:
    os.makedirs(VOICES_DIR, exist_ok=True)
    base_name = sanitize_filename(f"{voice.get('name', 'voice')}_{voice.get('id', '')[:8]}")
    temp_dir = tempfile.mkdtemp(prefix='vbee_voice_')
    raw_path = os.path.join(temp_dir, 'sample_audio')

    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    with open(raw_path, 'wb') as f:
        f.write(resp.content)

    out_path = os.path.join(VOICES_DIR, base_name + '.wav')
    ffmpeg = get_ffmpeg_path()
    if ffmpeg and os.path.exists(ffmpeg):
        cmd = [ffmpeg, '-y', '-i', raw_path, '-ac', '1', '-ar', '24000', out_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            mp3_fallback = os.path.join(VOICES_DIR, base_name + '.mp3')
            shutil.copy2(raw_path, mp3_fallback)
            return os.path.splitext(os.path.basename(mp3_fallback))[0]
        return os.path.splitext(os.path.basename(out_path))[0]
    else:
        mp3_fallback = os.path.join(VOICES_DIR, base_name + '.mp3')
        shutil.copy2(raw_path, mp3_fallback)
        return os.path.splitext(os.path.basename(mp3_fallback))[0]


class AIDubbingStudioGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry('1360x860')
        self.minsize(1260, 760)
        self.configure(fg_color=APP_BG)

        lang_json_path = os.path.join(BASE_DIR, 'languages.json')
        if os.path.exists(lang_json_path):
            with open(lang_json_path, 'r', encoding='utf-8') as f:
                self.full_lang_map = json.load(f)
        else:
            self.full_lang_map = {'Vietnamese': 'vi', 'English': 'en'}

        self.input_mode = 'youtube'
        self.available_subs_dict = {}
        self.selected_yt_sub_display = '(Hãy quét URL trước)'
        self.selected_local_lang = 'Vietnamese'
        self.selected_voice_name = None
        self.image_cache = ImageCache()
        self._build_ui()
        self.load_voice_profiles()
        self.switch_input_mode('youtube')

    # ---------- UI ----------
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, fg_color=PANEL_BG, corner_radius=0, border_color=BORDER, border_width=1)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky='nsew')
        self.sidebar.grid_propagate(False)

        self.header = ctk.CTkFrame(self, fg_color=APP_BG)
        self.header.grid(row=0, column=1, sticky='ew', padx=18, pady=(16, 6))
        self.header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.header, text='🎬 AI Dubbing Studio', font=ctk.CTkFont(size=28, weight='bold'), text_color=TEXT).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(self.header, text='SYNC V3 • OmniVoice • Thư viện giọng Vbee offline đẹp hơn, đỡ lỏ hơn.',
                     font=ctk.CTkFont(size=13), text_color=TEXT_DIM).grid(row=1, column=0, sticky='w', pady=(2, 0))

        container = ctk.CTkFrame(self, fg_color='transparent')
        container.grid(row=1, column=1, sticky='nsew', padx=18, pady=(6, 18))
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=0)
        container.grid_rowconfigure(0, weight=1)

        self.main_panel = ctk.CTkFrame(container, fg_color=PANEL_BG, corner_radius=20, border_color=BORDER, border_width=1)
        self.main_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.main_panel.grid_rowconfigure(3, weight=1)
        self.main_panel.grid_columnconfigure(0, weight=1)

        self.settings_panel = ctk.CTkFrame(container, fg_color=PANEL_BG, width=360, corner_radius=20, border_color=BORDER, border_width=1)
        self.settings_panel.grid(row=0, column=1, sticky='ns')
        self.settings_panel.grid_propagate(False)

        self._build_sidebar()
        self._build_main_panel()
        self._build_settings_panel()

    def _build_sidebar(self):
        ctk.CTkLabel(self.sidebar, text='OMNIVOICE', font=ctk.CTkFont(size=22, weight='bold'), text_color=ACCENT).pack(anchor='w', padx=18, pady=(20, 6))
        ctk.CTkLabel(self.sidebar, text='Chọn chế độ làm việc', text_color=TEXT_DIM).pack(anchor='w', padx=18, pady=(0, 18))

        self.btn_yt = ctk.CTkButton(self.sidebar, text='🔗 YouTube Dubbing', height=44, fg_color=ACCENT, text_color='#111', command=lambda: self.switch_input_mode('youtube'))
        self.btn_yt.pack(fill='x', padx=14, pady=6)
        self.btn_local = ctk.CTkButton(self.sidebar, text='📁 Video Local', height=44, fg_color=CARD_BG, hover_color=CARD_BG_2, command=lambda: self.switch_input_mode('local'))
        self.btn_local.pack(fill='x', padx=14, pady=6)
        self.btn_tts = ctk.CTkButton(self.sidebar, text='🗣️ Text To Speech', height=44, fg_color=CARD_BG, hover_color=CARD_BG_2, command=lambda: self.switch_input_mode('tts'))
        self.btn_tts.pack(fill='x', padx=14, pady=6)

        sep = ctk.CTkFrame(self.sidebar, height=1, fg_color=BORDER)
        sep.pack(fill='x', padx=14, pady=18)

        ctk.CTkLabel(self.sidebar, text='Lối tắt', text_color=TEXT, font=ctk.CTkFont(size=15, weight='bold')).pack(anchor='w', padx=18, pady=(0, 10))
        ctk.CTkButton(self.sidebar, text='🎙️ Mở thư mục voices', fg_color='#30363d', command=lambda: safe_startfile(VOICES_DIR)).pack(fill='x', padx=14, pady=6)
        ctk.CTkButton(self.sidebar, text='🧾 Mở thư viện Vbee JSON', fg_color='#30363d', command=self.open_vbee_json_location).pack(fill='x', padx=14, pady=6)
        ctk.CTkButton(self.sidebar, text='🔄 Refresh local voices', fg_color='#30363d', command=self.load_voice_profiles).pack(fill='x', padx=14, pady=6)
        ctk.CTkButton(self.sidebar, text='🎭 AI phân vai & duyệt', height=42, fg_color=ACCENT_2, command=self.open_role_review).pack(fill='x', padx=14, pady=12)

        self.sidebar_status = ctk.CTkLabel(self.sidebar, text='Sẵn sàng.', wraplength=180, justify='left', text_color=TEXT_DIM)
        self.sidebar_status.pack(side='bottom', anchor='w', padx=18, pady=16)

    def _card(self, parent, title, subtitle=None):
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=18, border_color=BORDER, border_width=1)
        title_lbl = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=17, weight='bold'), text_color=TEXT)
        title_lbl.pack(anchor='w', padx=16, pady=(14, 2))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, text_color=TEXT_DIM, wraplength=720, justify='left').pack(anchor='w', padx=16, pady=(0, 12))
        return card

    def _build_main_panel(self):
        self.mode_title = ctk.CTkLabel(self.main_panel, text='YouTube Dubbing', font=ctk.CTkFont(size=24, weight='bold'), text_color=TEXT)
        self.mode_title.grid(row=0, column=0, sticky='w', padx=18, pady=(18, 4))
        self.mode_desc = ctk.CTkLabel(self.main_panel, text='Dán link, quét sub, dịch bằng ChatGPT, rồi render.', text_color=TEXT_DIM)
        self.mode_desc.grid(row=1, column=0, sticky='w', padx=18, pady=(0, 14))

        self.input_card = self._card(self.main_panel, 'Nguồn đầu vào', 'Hỗ trợ link YouTube hoặc video local tùy chế độ.')
        self.input_card.grid(row=2, column=0, sticky='ew', padx=18, pady=(0, 12))
        self.input_card.grid_columnconfigure(0, weight=1)

        self.input_entry = ctk.CTkEntry(self.input_card, height=42, placeholder_text='Nhập link YouTube hoặc đường dẫn video...')
        self.input_entry.pack(fill='x', padx=16, pady=(0, 10))
        self.browse_btn = ctk.CTkButton(self.input_card, text='Duyệt video local', fg_color=ACCENT_2, command=self.browse_local_file)
        self.browse_btn.pack(anchor='w', padx=16, pady=(0, 14))

        self.middle_area = ctk.CTkFrame(self.main_panel, fg_color='transparent')
        self.middle_area.grid(row=3, column=0, sticky='nsew', padx=18, pady=(0, 12))
        self.middle_area.grid_columnconfigure(0, weight=1)
        self.middle_area.grid_rowconfigure(2, weight=1)

        self.scan_card = self._card(self.middle_area, 'Sub YouTube / Ngôn ngữ', 'Quét danh sách track phụ đề và chọn track cần khóa timeline.')
        self.scan_card.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        row = ctk.CTkFrame(self.scan_card, fg_color='transparent')
        row.pack(fill='x', padx=16, pady=(0, 14))
        self.btn_scan = ctk.CTkButton(row, text='🔍 Quét sub YouTube', fg_color=ACCENT_2, command=self.scan_youtube_subs)
        self.btn_scan.pack(side='left', padx=(0, 10))
        self.yt_sub_search_btn = ctk.CTkButton(row, text='📜 (Hãy quét URL trước)', fg_color='#30363d', border_color=BORDER, border_width=1,
                                               command=self.open_yt_sub_search)
        self.yt_sub_search_btn.pack(side='left', fill='x', expand=True)

        self.local_lang_card = self._card(self.middle_area, 'Ngôn ngữ đích / Whisper', 'Video local sẽ dùng Whisper để lấy transcript, sau đó render ra ngôn ngữ đích.')
        self.local_lang_card.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        top = ctk.CTkFrame(self.local_lang_card, fg_color='transparent')
        top.pack(fill='x', padx=16, pady=(0, 10))
        self.local_search_btn = ctk.CTkButton(top, text='🌐 Vietnamese', fg_color='#30363d', command=self.open_local_language_search)
        self.local_search_btn.pack(side='left', fill='x', expand=True, padx=(0, 10))
        self.sw_burn_sub = ctk.CTkSwitch(top, text='Burn sub cứng', progress_color=ACCENT)
        self.sw_burn_sub.pack(side='left')

        whisper_wrap = ctk.CTkFrame(self.local_lang_card, fg_color='transparent')
        whisper_wrap.pack(fill='x', padx=16, pady=(0, 14))
        ctk.CTkLabel(whisper_wrap, text='Whisper model', text_color=TEXT_DIM).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(whisper_wrap, text='Tiếng gốc', text_color=TEXT_DIM).grid(row=0, column=1, sticky='w', padx=(12, 0))
        self.whisper_model_var = ctk.StringVar(value='base')
        self.whisper_model_combo = ctk.CTkOptionMenu(whisper_wrap, values=['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3'], variable=self.whisper_model_var,
                                                     fg_color='#30363d', button_color='#3d4956', dropdown_fg_color=CARD_BG_2)
        self.whisper_model_combo.grid(row=1, column=0, sticky='ew')
        try:
            whisper_display_list = ['Auto (auto)'] + [f"{name.title()} ({code})" for code, name in whisper.tokenizer.LANGUAGES.items()]
        except Exception:
            whisper_display_list = ['Auto (auto)', 'Vietnamese (vi)', 'English (en)']
        self.whisper_lang_var = ctk.StringVar(value=whisper_display_list[0])
        self.whisper_lang_combo = ctk.CTkOptionMenu(whisper_wrap, values=whisper_display_list, variable=self.whisper_lang_var,
                                                    fg_color='#30363d', button_color='#3d4956', dropdown_fg_color=CARD_BG_2, width=220)
        self.whisper_lang_combo.grid(row=1, column=1, sticky='ew', padx=(12, 0))
        whisper_wrap.grid_columnconfigure(0, weight=1)
        whisper_wrap.grid_columnconfigure(1, weight=1)

        self.tts_card = self._card(self.middle_area, 'Văn bản TTS', 'Dùng chế độ này để tạo riêng một file audio từ đoạn văn bản bất kỳ.')
        self.tts_card.grid(row=2, column=0, sticky='nsew')
        self.tts_textbox = ctk.CTkTextbox(self.tts_card, font=ctk.CTkFont(size=14), fg_color='#11161d', border_color=BORDER, border_width=1)
        self.tts_textbox.pack(fill='both', expand=True, padx=16, pady=(0, 14))

        self.bottom_bar = ctk.CTkFrame(self.main_panel, fg_color='transparent')
        self.bottom_bar.grid(row=4, column=0, sticky='ew', padx=18, pady=(0, 18))
        self.bottom_bar.grid_columnconfigure(0, weight=1)
        self.status_lbl = ctk.CTkLabel(self.bottom_bar, text='Sẵn sàng.', text_color=TEXT_DIM)
        self.status_lbl.grid(row=0, column=0, sticky='w', pady=(0, 10))
        self.progress_bar = ctk.CTkProgressBar(self.bottom_bar, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(0, 12))
        self.btn_review = ctk.CTkButton(self.bottom_bar, text='🎭 PHÂN VAI & DUYỆT', height=42,
                                        fg_color='#3d4956', command=self.open_role_review)
        self.btn_review.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        self.btn_step1 = ctk.CTkButton(self.bottom_bar, text='⚙️ BƯỚC 1: EXTRACT', height=46, fg_color=ACCENT_2, command=lambda: self.start_pipeline_thread('extract'))
        self.btn_step1.grid(row=2, column=0, sticky='ew', padx=(0, 8))
        self.btn_step2 = ctk.CTkButton(self.bottom_bar, text='🚀 BƯỚC 2: RENDER', height=46, fg_color=ACCENT, text_color='#111', command=lambda: self.start_pipeline_thread('render'))
        self.btn_step2.grid(row=2, column=1, sticky='ew', padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(self.bottom_bar, text='🛑 Hủy', width=110, height=46, fg_color=DANGER, command=self.trigger_cancel_pipeline, state='disabled')
        self.cancel_btn.grid(row=2, column=2, sticky='ew')
        self.bottom_bar.grid_columnconfigure(1, weight=1)

    def _build_settings_panel(self):
        ctk.CTkLabel(self.settings_panel, text='⚙️ Điều khiển studio', font=ctk.CTkFont(size=20, weight='bold'), text_color=TEXT).pack(anchor='w', padx=18, pady=(18, 6))
        ctk.CTkLabel(self.settings_panel, text='Thiết lập giọng đọc, âm lượng và thư viện giọng.', text_color=TEXT_DIM).pack(anchor='w', padx=18, pady=(0, 14))

        self.voice_card = self._card(self.settings_panel, 'Giọng clone đang dùng', 'Có thể refresh giọng mới mà không cần tắt app.')
        self.voice_card.pack(fill='x', padx=16, pady=(0, 12))
        self.voice_combo = ctk.CTkOptionMenu(self.voice_card, values=['(chưa có giọng)'], fg_color='#30363d', button_color='#3d4956', dropdown_fg_color=CARD_BG_2)
        self.voice_combo.pack(fill='x', padx=16, pady=(0, 10))

        # Voice mode is explicit and always defaults to SINGLE on app start.
        # In particular, a previous video's speaker_roles.json never silently
        # turns multi-speaker back on.
        self.voice_mode_var = ctk.StringVar(value='1 GIỌNG')
        self.voice_mode_frame = ctk.CTkFrame(self.voice_card, fg_color='#111820', corner_radius=12, border_color=BORDER, border_width=1)
        self.voice_mode_frame.pack(fill='x', padx=16, pady=(0, 12))
        ctk.CTkLabel(self.voice_mode_frame, text='CHẾ ĐỘ LỒNG TIẾNG', font=ctk.CTkFont(size=12, weight='bold'),
                     text_color=ACCENT).pack(anchor='w', padx=12, pady=(10, 7))
        self.voice_mode_segment = ctk.CTkSegmentedButton(
            self.voice_mode_frame, values=['1 GIỌNG', 'MULTI-SPEAKER'],
            variable=self.voice_mode_var, command=self.on_voice_mode_change,
            selected_color=ACCENT_2, selected_hover_color='#2465b7',
            unselected_color='#30363d', unselected_hover_color='#3d4956',
            text_color=TEXT, font=ctk.CTkFont(size=12, weight='bold'), height=36)
        self.voice_mode_segment.pack(fill='x', padx=12)
        self.voice_mode_help = ctk.CTkLabel(self.voice_mode_frame,
            text='1 GIỌNG: chỉ dùng giọng ở ô bên trên. Không cần phân vai.',
            wraplength=285, justify='left', text_color=TEXT_DIM,
            font=ctk.CTkFont(size=11))
        self.voice_mode_help.pack(anchor='w', padx=12, pady=(8, 12))

        self.voice_buttons_row = ctk.CTkFrame(self.voice_card, fg_color='transparent')
        btnrow = self.voice_buttons_row
        btnrow.pack(fill='x', padx=16, pady=(0, 14))
        ctk.CTkButton(btnrow, text='🎙️ Thư viện Vbee', fg_color=ACCENT_2, command=self.open_vbee_library).pack(side='left', fill='x', expand=True, padx=(0, 6))
        ctk.CTkButton(btnrow, text='🔄 Refresh', fg_color='#30363d', command=self.load_voice_profiles).pack(side='left', fill='x', expand=True, padx=(6, 0))

        self.mixer_card = self._card(self.settings_panel, 'Âm thanh & xử lý', 'Chọn engine tách âm, luồng chạy và mức âm lượng từng thành phần.')
        self.mixer_card.pack(fill='x', padx=16, pady=(0, 12))
        opt = ctk.CTkFrame(self.mixer_card, fg_color='transparent')
        opt.pack(fill='x', padx=16, pady=(0, 10))
        ctk.CTkLabel(opt, text='Engine tách âm', text_color=TEXT_DIM).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(opt, text='Số luồng', text_color=TEXT_DIM).grid(row=0, column=1, sticky='w', padx=(12, 0))
        self.engine_var = ctk.StringVar(value='Demucs')
        self.threads_var = ctk.StringVar(value='3')
        self.engine_combo = ctk.CTkOptionMenu(opt, values=['Demucs', 'Roformer'], variable=self.engine_var, fg_color='#30363d', button_color='#3d4956', dropdown_fg_color=CARD_BG_2)
        self.engine_combo.grid(row=1, column=0, sticky='ew')
        self.threads_combo = ctk.CTkOptionMenu(opt, values=['1', '2', '3', '4', '5'], variable=self.threads_var, fg_color='#30363d', button_color='#3d4956', dropdown_fg_color=CARD_BG_2)
        self.threads_combo.grid(row=1, column=1, sticky='ew', padx=(12, 0))
        opt.grid_columnconfigure(0, weight=1)
        opt.grid_columnconfigure(1, weight=1)

        self.bg_slider_frame = self._slider_block(self.mixer_card, '🔉 Nhạc nền / background', 10)
        self.bg_slider = self.bg_slider_frame[1]
        self.bg_label = self.bg_slider_frame[0]
        self.vocal_slider_frame = self._slider_block(self.mixer_card, '🎤 Vocal gốc / lời gốc', 0)
        self.vocal_slider = self.vocal_slider_frame[1]
        self.vocal_label = self.vocal_slider_frame[0]
        self.dub_slider_frame = self._slider_block(self.mixer_card, '🗣️ Giọng lồng tiếng AI', 100)
        self.dub_slider = self.dub_slider_frame[1]
        self.dub_label = self.dub_slider_frame[0]

        self.tts_card_settings = self._card(self.settings_panel, 'TTS riêng', 'Chỉ áp dụng cho chế độ Text To Speech.')
        self.tts_card_settings.pack(fill='x', padx=16, pady=(0, 16))
        self.speed_slider_frame = self._slider_block(self.tts_card_settings, '⚡ Tốc độ đọc', 100, from_=80, to=130, scale=0.01, fmt='x')
        self.speed_slider = self.speed_slider_frame[1]
        self.pitch_slider_frame = self._slider_block(self.tts_card_settings, '🎚️ Cao độ', 100, from_=80, to=120, scale=0.01, fmt='x')
        self.pitch_slider = self.pitch_slider_frame[1]

    def _slider_block(self, parent, title, default_percent, from_=0, to=100, scale=1.0, fmt='%'):
        wrap = ctk.CTkFrame(parent, fg_color='transparent')
        wrap.pack(fill='x', padx=16, pady=(0, 10))
        label = ctk.CTkLabel(wrap, text=f"{title}: {default_percent}{fmt}", text_color=TEXT)
        label.pack(anchor='w')
        slider = ctk.CTkSlider(wrap, from_=from_, to=to, progress_color=ACCENT)
        slider.set(default_percent)
        slider.pack(fill='x', pady=(6, 0))
        def on_change(v):
            val = float(v) * scale if scale != 1.0 else float(v)
            shown = f"{val:.2f}" if fmt == 'x' else f"{int(float(v))}"
            suffix = fmt
            if fmt == 'x':
                label.configure(text=f"{title}: {shown}x")
            else:
                label.configure(text=f"{title}: {shown}{suffix}")
        slider.configure(command=on_change)
        return wrap, slider

    # ---------- sidebar helpers ----------
    def set_status_text(self, text):
        self.status_lbl.configure(text=text)
        self.sidebar_status.configure(text=text)

    def open_vbee_json_location(self):
        path = os.path.join(BASE_DIR, VBEE_JSON_NAME)
        if os.path.exists(path):
            safe_startfile(os.path.dirname(path))
        else:
            messagebox.showwarning('Thiếu file', f'Chưa thấy {VBEE_JSON_NAME} ở thư mục app.')

    def load_voice_profiles(self):
        os.makedirs(VOICES_DIR, exist_ok=True)
        profiles = [os.path.splitext(f)[0] for f in os.listdir(VOICES_DIR) if f.lower().endswith(('.wav', '.mp3', '.m4a'))]
        profiles = sorted(set(profiles), key=str.lower)
        if not profiles:
            profiles = ['(chưa có giọng)']
        self.voice_combo.configure(values=profiles)
        current = self.selected_voice_name if self.selected_voice_name in profiles else profiles[0]
        self.voice_combo.set(current)
        self.selected_voice_name = current
        self.set_status_text(f'Đã quét {0 if profiles == ["(chưa có giọng)"] else len(profiles)} giọng local.')

    def handle_voice_imported(self, imported_name):
        self.selected_voice_name = imported_name
        self.load_voice_profiles()
        self.voice_combo.set(imported_name)

    def open_role_review(self):
        if self.btn_step2.cget('state') == 'disabled':
            messagebox.showwarning('Đang render', 'Hãy đợi tác vụ render/extract đang chạy hoàn tất trước khi phân vai.')
            return
        if self.input_mode == 'tts':
            messagebox.showinfo('Chỉ cho video', 'AI phân vai chỉ dùng cho video có timeline. Chọn YouTube hoặc Local Video.')
            return
        video_input = self.input_entry.get().strip()
        if not video_input:
            messagebox.showwarning('Thiếu video', 'Nhập URL YouTube hoặc chọn file video trước.')
            return
        if self.input_mode == 'youtube':
            video_id = extract_video_id(video_input)
            if not video_id:
                messagebox.showerror('URL lỗi', 'Link YouTube không hợp lệ.')
                return
        else:
            if not os.path.isfile(video_input):
                messagebox.showerror('File lỗi', 'Không tìm thấy video local.')
                return
            video_id = os.path.splitext(os.path.basename(video_input))[0]
        # Same working-directory-relative folder as existing core.py.
        folder = os.path.abspath(os.path.join('downloaded_data', video_id))
        if not os.path.isfile(os.path.join(folder, 'final_subtitles.json')):
            messagebox.showwarning('Chưa có timeline', 'Hãy chạy BƯỚC 1: EXTRACT trước, sau đó mới phân vai.')
            return
        try:
            editor = RoleReviewDialog(
                self, folder=folder, input_mode=self.input_mode,
                input_path=video_input, default_profile=self.voice_combo.get(),
                voices_dir=VOICES_DIR, ffmpeg=get_ffmpeg_path(),
                video_id=video_id,
                vbee_json=os.path.join(BASE_DIR, VBEE_JSON_NAME))
            editor.focus()
        except Exception as exc:
            messagebox.showerror('Không mở được AI phân vai', str(exc))

    def open_vbee_library(self):
        json_path = os.path.join(BASE_DIR, VBEE_JSON_NAME)
        if not os.path.exists(json_path):
            chosen = filedialog.askopenfilename(title='Chọn file vbee_community_all.json', filetypes=[('JSON files', '*.json')])
            if not chosen:
                return
            json_path = chosen
        try:
            dlg = VbeeVoiceLibraryDialog(self, json_path, self.handle_voice_imported)
            dlg.focus()
        except Exception as e:
            messagebox.showerror('Lỗi mở thư viện', str(e))

    # ---------- voice mode ----------
    def on_voice_mode_change(self, _selection=None):
        self.refresh_voice_mode_ui()
        is_multi = self.voice_mode_var.get() == 'MULTI-SPEAKER'
        self.set_status_text(
            'Đã chọn MULTI-SPEAKER: phải duyệt phân vai trước khi render.' if is_multi
            else 'Đã chọn 1 GIỌNG: render như SYNC V3 cũ; giữ nguyên bản phân vai đã lưu.')

    def refresh_voice_mode_ui(self):
        if not hasattr(self, 'voice_mode_frame'):
            return
        if self.input_mode == 'tts':
            self.voice_mode_frame.pack_forget()
            self.btn_review.grid_remove()
            return

        # Restore panel in its original position when coming back from TTS.
        if not self.voice_mode_frame.winfo_manager():
            self.voice_mode_frame.pack(fill='x', padx=16, pady=(0, 12), before=self.voice_buttons_row)
        is_multi = self.voice_mode_var.get() == 'MULTI-SPEAKER'
        if is_multi:
            self.voice_mode_help.configure(
                text='MULTI: dùng speaker_roles.json đã DUYỆT. Chọn giọng cho từng vai ở nút Phân vai.')
            self.btn_review.grid()
        else:
            self.voice_mode_help.configure(
                text='1 GIỌNG: toàn video dùng giọng ở ô bên trên; bỏ qua phân vai cũ, không xóa file.')
            self.btn_review.grid_remove()

    # ---------- modes ----------
    def switch_input_mode(self, mode):
        self.input_mode = mode
        for btn in [self.btn_yt, self.btn_local, self.btn_tts]:
            btn.configure(fg_color=CARD_BG, text_color=TEXT)
        if mode == 'youtube':
            self.btn_yt.configure(fg_color=ACCENT, text_color='#111')
            self.mode_title.configure(text='YouTube Dubbing')
            self.mode_desc.configure(text='Dùng sub YouTube làm timeline chuẩn rồi lồng tiếng bằng translated.txt.')
            self.input_entry.configure(placeholder_text='Nhập link video YouTube...')
            self.browse_btn.pack_forget()
            self.scan_card.grid()
            self.local_lang_card.grid_remove()
            self.tts_card.grid_remove()
            self.btn_step1.grid()
            self.btn_review.grid()
            self.btn_step2.configure(text='🚀 BƯỚC 2: RENDER')
            self.mixer_card.pack(fill='x', padx=16, pady=(0, 12))
            self.tts_card_settings.pack_forget()
        elif mode == 'local':
            self.btn_local.configure(fg_color=ACCENT, text_color='#111')
            self.mode_title.configure(text='Local Video Dubbing')
            self.mode_desc.configure(text='Transcribe bằng Whisper, sau đó render ra voice clone theo ngôn ngữ đích.')
            self.input_entry.configure(placeholder_text='Chọn file video local...')
            self.browse_btn.pack(anchor='w', padx=16, pady=(0, 14))
            self.scan_card.grid_remove()
            self.local_lang_card.grid()
            self.tts_card.grid_remove()
            self.btn_step1.grid()
            self.btn_review.grid()
            self.btn_step2.configure(text='🚀 BƯỚC 2: RENDER')
            self.mixer_card.pack(fill='x', padx=16, pady=(0, 12))
            self.tts_card_settings.pack_forget()
        else:
            self.btn_tts.configure(fg_color=ACCENT, text_color='#111')
            self.mode_title.configure(text='Text To Speech')
            self.mode_desc.configure(text='Tạo nhanh một file audio bằng giọng clone đang chọn.')
            self.input_entry.configure(placeholder_text='Chế độ này không cần video nguồn')
            self.browse_btn.pack_forget()
            self.scan_card.grid_remove()
            self.local_lang_card.grid()
            self.tts_card.grid()
            self.btn_step1.grid_remove()
            self.btn_review.grid_remove()
            self.btn_step2.configure(text='✨ TẠO AUDIO TTS')
            self.mixer_card.pack_forget()
            self.tts_card_settings.pack(fill='x', padx=16, pady=(0, 16))
        self.refresh_voice_mode_ui()

    # ---------- input and sub handling ----------
    def browse_local_file(self):
        file_path = filedialog.askopenfilename(filetypes=[('Video Files', '*.mp4 *.mkv *.avi *.mov *.webm')])
        if file_path:
            self.input_entry.delete(0, 'end')
            self.input_entry.insert(0, file_path)

    def open_local_language_search(self):
        LanguageSearchDialog(self, self.full_lang_map, self.update_selected_local_language, '🔍 Chọn ngôn ngữ đích')

    def update_selected_local_language(self, language_name):
        self.selected_local_lang = language_name
        self.local_search_btn.configure(text=f'🌐 {language_name}')

    def open_yt_sub_search(self):
        if not getattr(self, 'yt_search_map', None):
            messagebox.showwarning('Khoan đã', 'Ông phải bấm Quét sub YouTube trước.')
            return
        LanguageSearchDialog(self, self.yt_search_map, self.update_selected_yt_sub, '🔍 Tìm & Chọn Sub YouTube')

    def update_selected_yt_sub(self, selected_display):
        self.selected_yt_sub_display = selected_display
        self.yt_sub_search_btn.configure(text=f'📜 {selected_display}')

    def scan_youtube_subs(self):
        url = self.input_entry.get().strip()
        vid = extract_video_id(url)
        if not vid:
            messagebox.showerror('Lỗi', 'Vui lòng nhập link YouTube hợp lệ để quét!')
            return
        self.btn_scan.configure(text='⏳ Đang quét...', state='disabled')
        self.set_status_text('Đang quét danh sách track sub YouTube...')

        def worker():
            yt = YouTubeProExtractor()
            self.available_subs_dict = yt.get_available_subs(vid)
            self.after(0, self.update_sub_dropdown)
        threading.Thread(target=worker, daemon=True).start()

    def update_sub_dropdown(self):
        self.btn_scan.configure(text='🔍 Quét sub YouTube', state='normal')
        if not self.available_subs_dict:
            messagebox.showwarning('Cảnh báo', 'Không quét được track phụ đề nào!')
            self.yt_sub_search_btn.configure(text='❌ Không có sub')
            return
        self.yt_search_map = {v: k for k, v in self.available_subs_dict.items()}
        first_display = sorted(list(self.yt_search_map.keys()))[0]
        self.update_selected_yt_sub(first_display)
        self.set_status_text(f'Quét thành công {len(self.yt_search_map)} track sub.')

    # ---------- pipeline ----------
    def update_gui_progress(self, percentage, status_text):
        self.after(0, lambda: self.progress_bar.set(percentage / 100.0))
        self.after(0, lambda: self.set_status_text(f'[{percentage}%] {status_text}'))

    def trigger_cancel_pipeline(self):
        if messagebox.askyesno('Xác nhận', 'Hủy ngang tiến trình đang chạy?'):
            cancel_event.set()

    def start_pipeline_thread(self, run_step='full'):
        if self.voice_combo.get() == '(chưa có giọng)':
            messagebox.showerror('Thiếu giọng', 'Chưa có giọng clone nào trong thư mục voices.')
            return

        if self.input_mode != 'tts':
            video_source = self.input_entry.get().strip()
            if not video_source:
                messagebox.showerror('Lỗi', 'Vui lòng nhập video nguồn!')
                return
        else:
            video_source = 'TTS_MODE'

        if self.input_mode == 'youtube':
            yt_map = getattr(self, 'yt_search_map', {}) or {}
            target_code = yt_map.get(self.selected_yt_sub_display)
            if not target_code:
                messagebox.showerror('Lỗi', 'Bạn phải quét và chọn một track sub trước!')
                return
        else:
            target_code = self.full_lang_map.get(self.selected_local_lang, 'vi')

        voice_mode = ('multi' if self.input_mode != 'tts'
                      and self.voice_mode_var.get() == 'MULTI-SPEAKER' else 'single')
        if run_step in ('render', 'full') and voice_mode == 'multi':
            # Short-circuit common mistakes before an expensive audio render.
            video_id = (extract_video_id(video_source) if self.input_mode == 'youtube'
                        else os.path.splitext(os.path.basename(video_source))[0])
            project_path = os.path.join('downloaded_data', video_id or '', 'speaker_roles.json')
            if not os.path.isfile(project_path):
                messagebox.showwarning('Chưa phân vai',
                    'Đang chọn MULTI-SPEAKER nhưng video chưa có speaker_roles.json.\n'
                    'Bấm PHÂN VAI & DUYỆT để phân vai và lưu trước khi render.')
                return
            try:
                with open(project_path, 'r', encoding='utf-8') as f:
                    role_project = json.load(f)
                if not role_project.get('approved'):
                    messagebox.showwarning('Chưa duyệt',
                        'Bản phân vai chưa được DUYỆT. Mở PHÂN VAI & DUYỆT rồi bấm DUYỆT & LƯU.')
                    return
            except (OSError, ValueError) as exc:
                messagebox.showerror('File phân vai lỗi', f'Không đọc được speaker_roles.json:\n{exc}')
                return

        self.btn_step2.configure(state='disabled', fg_color='#555')
        self.cancel_btn.configure(state='normal')
        self.voice_mode_segment.configure(state='disabled')
        if self.input_mode != 'tts':
            self.btn_step1.configure(state='disabled', fg_color='#555')
        self.progress_bar.set(0)
        self.set_status_text('Đang khởi động pipeline...')

        t = threading.Thread(target=self.bg_worker_pipeline, args=(video_source, target_code, run_step, voice_mode), daemon=True)
        t.start()

    def bg_worker_pipeline(self, video_source, target_code, run_step, voice_mode='single'):
        try:
            # License is verified online before each EXTRACT / RENDER / TTS.
            # A valid key is not bound to a hardware ID.
            from license_client import require_active_license
            require_active_license()
            selected_engine = self.engine_var.get()
            selected_threads = int(self.threads_var.get())
            tts_text_val = self.tts_textbox.get('1.0', 'end').strip()
            speed_val = float(self.speed_slider.get()) / 100.0
            pitch_val = float(self.pitch_slider.get()) / 100.0
            whisper_model_val = self.whisper_model_var.get()
            raw_source_lang = self.whisper_lang_var.get()
            source_lang_val = raw_source_lang.split('(')[-1].replace(')', '').strip()

            result = run_process(
                input_mode=self.input_mode,
                video_input=video_source,
                sub_lang_code=target_code,
                bg_vol=self.bg_slider.get(),
                vocal_vol=self.vocal_slider.get(),
                dub_vol=self.dub_slider.get(),
                profile_id=self.voice_combo.get(),
                burn_sub=bool(self.sw_burn_sub.get()),
                callback=self.update_gui_progress,
                web_cookie='',
                run_step=run_step,
                engine_mode=selected_engine,
                num_threads=selected_threads,
                tts_text=tts_text_val,
                speed=speed_val,
                pitch=pitch_val,
                whisper_model=whisper_model_val,
                source_lang=source_lang_val,
                voice_mode=voice_mode
            )

            if not result:
                raise RuntimeError('Tiến trình xử lý không trả về kết quả!')

            status = result.get('status')
            if status == 'extracted':
                folder_path = os.path.dirname(result.get('file'))
                safe_startfile(folder_path)
                self.after(0, lambda: messagebox.showinfo('BƯỚC 1 hoàn tất', "Đã tạo timeline + to_translate.txt. Giờ dịch bằng ChatGPT, lưu thành translated.txt rồi bấm BƯỚC 2."))
            elif status == 'success':
                self.after(0, lambda: messagebox.showinfo('Thành công', f"Đã lồng tiếng xong:\n{result.get('file')}"))
            elif status == 'tts_success':
                safe_startfile(os.path.dirname(result.get('file')))
                self.after(0, lambda: messagebox.showinfo('Thành công', f"Đã tạo file TTS:\n{result.get('file')}"))
            else:
                self.after(0, lambda: messagebox.showerror('Thất bại', f"Lỗi phát sinh:\n{result.get('msg')}"))
        except Exception as ex:
            self.after(0, lambda: messagebox.showerror('Lỗi bất ngờ', str(ex)))
        finally:
            self.after(0, lambda: self.btn_step1.configure(state='normal', fg_color=ACCENT_2))
            self.after(0, lambda: self.btn_step2.configure(state='normal', fg_color=ACCENT, text_color='#111'))
            self.after(0, lambda: self.cancel_btn.configure(state='disabled'))
            self.after(0, lambda: self.voice_mode_segment.configure(state='normal'))


if __name__ == '__main__':
    from license_ui import launch_with_license
    launch_with_license(AIDubbingStudioGUI)
