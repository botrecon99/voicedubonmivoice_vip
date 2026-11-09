# -*- coding: utf-8 -*-
"""Human-in-the-loop speaker-role review for OmniVoice. Requires no AI packages."""
import copy
import json
import os
import queue
import re
import traceback
from datetime import datetime
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk
from speaker_roles import (project_from_subtitles, read_role_file, role_file,
                           atomic_write_json, validate_project, timeline_signature,
                           ALLOWED_TYPES)

APP_BG = '#0d1117'
PANEL_BG = '#161b22'
CARD_BG = '#222b35'
BORDER = '#30363d'
ACCENT = '#f2b94b'
BLUE = '#2f81f7'
TEXT = '#f0f6fc'
DIM = '#99a6b6'
GREEN = '#2ea043'
VOICE_FOLDER = None

TYPES = {
    'unknown': 'Chưa rõ (tự chọn)',
    'male': 'Nam trưởng thành',
    'female': 'Nữ trưởng thành',
    'boy': 'Bé trai (thủ công)',
    'girl': 'Bé gái (thủ công)',
    'child': 'Trẻ em / chưa rõ',
    'older_male': 'Nam lớn tuổi',
    'older_female': 'Nữ lớn tuổi',
    'older': 'Người lớn tuổi / chưa rõ',
}
LABEL_TO_TYPE = {v: k for k, v in TYPES.items()}


def redact_secrets(text, token=''):
    """Prevent Hugging Face credentials appearing in GUI, copied or saved logs."""
    text = str(text)
    if token:
        text = text.replace(token, '[HIDDEN_TOKEN]')
    text = re.sub(r'(?i)\bBearer\s+[^\s\"\']+', 'Bearer [HIDDEN_TOKEN]', text)
    text = re.sub(r'\bhf_[A-Za-z0-9_-]{8,}\b', '[HIDDEN_TOKEN]', text)
    return text


def fmt_time(seconds):
    seconds = max(0, float(seconds))
    return '%02d:%02d:%02d' % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def get_voices(voices_dir):
    if not os.path.isdir(voices_dir):
        os.makedirs(voices_dir, exist_ok=True)
    return sorted({os.path.splitext(fn)[0] for fn in os.listdir(voices_dir)
                   if fn.lower().endswith(('.wav', '.mp3', '.m4a'))}, key=str.casefold)


def show_audio(path):
    if sys.platform.startswith('win'):
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def lookup_voice_metadata(json_path):
    try:
        with open(json_path, encoding='utf-8') as f:
            voices = json.load(f)['voices']
        return {str(item.get('id', ''))[:8].lower(): item for item in voices}
    except Exception:
        return {}


def suggest_voice(voice_type, local_voices, vbee_meta):
    """Suggest only if local imported file contains known Vbee ID suffix.

    Avoid falsely treating arbitrary local filename as a verified gender/age.
    """
    gender = {'male': 'male', 'older_male': 'male', 'boy': 'male',
              'female': 'female', 'older_female': 'female', 'girl': 'female'}.get(voice_type)
    ages = {'boy': ('child', 'teen'), 'girl': ('child', 'teen'),
            'child': ('child', 'teen'),
            'older_male': ('old', 'middle-aged'),
            'older_female': ('old', 'middle-aged'), 'older': ('old', 'middle-aged')}.get(voice_type, ('young', 'adult', 'middle-aged'))
    if voice_type == 'unknown':
        return ''
    candidates = []
    for name in local_voices:
        item = vbee_meta.get(name[-8:].lower())
        if not item:
            continue
        if gender and item.get('gender') != gender:
            continue
        if item.get('age_group') not in ages:
            continue
        age_pref = len(ages) - ages.index(item.get('age_group'))
        candidates.append((age_pref, name))
    return sorted(candidates, reverse=True)[0][1] if candidates else ''


class RoleReviewDialog(ctk.CTkToplevel):
    def __init__(self, parent, folder, input_mode, input_path, default_profile,
                 voices_dir, ffmpeg, video_id=None, vbee_json=None):
        super().__init__(parent)
        self.title('🎭 AI PHÂN VAI • Duyệt thủ công trước khi render')
        self.geometry('1410x870')
        self.minsize(1220, 750)
        self.configure(fg_color=APP_BG)
        self.transient(parent)
        self.parent = parent
        self.folder = folder
        self.sub_path = os.path.join(folder, 'final_subtitles.json')
        self.voices_dir = voices_dir
        self.input_mode = input_mode
        self.input_path = input_path
        self.default_profile = default_profile
        self.video_id = video_id
        self.ffmpeg = ffmpeg
        self.vbee_json = vbee_json
        self.current_scan = False
        self.is_dirty = False
        self.last_audio_process = None
        # The subprocess is in a separate AI venv. Stream *all* of its output
        # to a large, copyable panel and a text file; never display credentials.
        self._log_queue = queue.Queue()
        self.log_lines = []
        self.log_file = None
        self.log_popup = None
        self.log_popup_text = None
        self._log_after_id = None

        with open(self.sub_path, 'r', encoding='utf-8') as f:
            self.subtitles = json.load(f)
        self.index_to_sub = {int(s['index']): s for s in self.subtitles}
        self.translation = self._load_translation()
        self.voice_options = get_voices(voices_dir)
        self.vbee_meta = lookup_voice_metadata(vbee_json or '')
        self.project = read_role_file(folder) or project_from_subtitles(self.subtitles, default_profile)
        if self.project.get('timeline_signature') != timeline_signature(self.subtitles):
            raise ValueError('Timeline đã thay đổi. Hãy di chuyển speaker_roles.json cũ ra chỗ khác trước khi phân vai lại.')
        self.current_speaker = None
        self.selected_index = None
        self.filter_var = ctk.StringVar(value='Tất cả')
        self.index_voice_var = ctk.StringVar(value='Dùng giọng theo vai')
        self.index_speaker_var = ctk.StringVar(value='')
        self.hf_token = ctk.StringVar(value='')
        self.gender_var = ctk.BooleanVar(value=True)
        self.age_var = ctk.BooleanVar(value=False)
        self._build_ui()
        self._populate_speakers()
        self._populate_index_tree()
        self.set_status('Chưa có thay đổi. AI chỉ gợi ý; kiểm tra và duyệt trước khi render.')
        if self.project.get('approved'):
            self.set_status('Đã duyệt. Sẵn sàng render đa giọng; chỉnh sửa sẽ phải duyệt lại.')
        self._log_after_id = self.after(80, self._drain_log_queue)
        self.protocol('WM_DELETE_WINDOW', self.on_close)

    def _load_translation(self):
        txt = os.path.join(self.folder, 'translated.txt')
        texts = {}
        if os.path.isfile(txt):
            import re
            with open(txt, 'r', encoding='utf-8') as f:
                for row in f:
                    m = re.match(r'^\s*\[(\d+)\]\s+(.+?)\s*$', row)
                    if m:
                        texts[int(m.group(1))] = m.group(2)
        return texts

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        # Keep the log permanently visible and large enough to read tracebacks.
        self.grid_rowconfigure(3, weight=0)
        head = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16)
        head.grid(row=0, column=0, sticky='ew', padx=16, pady=(16, 8))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text='🎭 AI PHÂN VAI • DUYỆT TRƯỚC KHI RENDER',
                     font=ctk.CTkFont(size=23, weight='bold'), text_color=TEXT).grid(row=0, column=0, sticky='w', padx=18, pady=(12, 2))
        self.info_label = ctk.CTkLabel(head, text=f"{len(self.subtitles)} câu • {len(self.project['speakers'])} người nói • Chưa duyệt",
                                       text_color=DIM)
        self.info_label.grid(row=1, column=0, sticky='w', padx=18, pady=(0, 12))
        ctk.CTkButton(head, text='📁 Mở thư mục video', fg_color='#30363d', command=lambda: show_audio(self.folder)).grid(row=0, column=1, rowspan=2, padx=18)

        scan = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16)
        scan.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 8))
        scan.grid_columnconfigure(1, weight=1)
        self.btn_scan_ai = ctk.CTkButton(scan, text='🧠 QUÉT AI PYANNOTE', height=41, fg_color=BLUE, command=self.start_ai_scan)
        self.btn_scan_ai.grid(row=0, column=0, padx=(12, 8), pady=11)
        self.token_entry = ctk.CTkEntry(scan, textvariable=self.hf_token, show='•', height=39, placeholder_text='Hugging Face Read token (không lưu lại)')
        self.token_entry.grid(row=0, column=1, sticky='ew', padx=(0, 8))
        self.gender_check = ctk.CTkCheckBox(scan, text='AI đoán nam/nữ', variable=self.gender_var, width=130)
        self.gender_check.grid(row=0, column=2, padx=(0, 8))
        self.age_check = ctk.CTkCheckBox(scan, text='Tuổi/trẻ em (phi thương mại)', variable=self.age_var,
                                        command=self.on_age_toggle, width=220)
        self.age_check.grid(row=0, column=3, padx=(0, 12))

        center = ctk.CTkFrame(self, fg_color='transparent')
        center.grid(row=2, column=0, sticky='nsew', padx=16, pady=(0, 8))
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=0)
        center.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(center, fg_color=PANEL_BG, corner_radius=16, width=385)
        left.grid(row=0, column=0, sticky='ns', padx=(0, 9))
        left.grid_propagate(False)
        ctk.CTkLabel(left, text='1. Người nói & giọng Việt', text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight='bold')).pack(anchor='w', padx=12, pady=(12, 8))
        self.speaker_scroll = ctk.CTkScrollableFrame(left, fg_color='transparent')
        self.speaker_scroll.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        ctk.CTkButton(left, text='➕ Thêm người nói thủ công', fg_color='#30363d',
                      command=self.add_speaker).pack(fill='x', padx=12, pady=(0, 12))

        right = ctk.CTkFrame(center, fg_color=PANEL_BG, corner_radius=16)
        right.grid(row=0, column=1, sticky='nsew')
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        row = ctk.CTkFrame(right, fg_color='transparent')
        row.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 7))
        ctk.CTkLabel(row, text='2. Kiểm tra từng câu theo timeline', text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight='bold')).pack(side='left')
        self.filter_combo = ctk.CTkOptionMenu(row, values=['Tất cả'], variable=self.filter_var,
                                               fg_color='#30363d', width=170, command=lambda v: self._populate_index_tree())
        self.filter_combo.pack(side='right')

        table_container = tk.Frame(right, bg=PANEL_BG)
        table_container.grid(row=1, column=0, sticky='nsew', padx=12)
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Roles.Treeview', background=CARD_BG, foreground=TEXT,
                        fieldbackground=CARD_BG, borderwidth=0, rowheight=29,
                        font=('Segoe UI', 10))
        style.map('Roles.Treeview', background=[('selected', '#24568c')],
                  foreground=[('selected', '#ffffff')])
        style.configure('Roles.Treeview.Heading', background='#30363d', foreground=TEXT,
                        font=('Segoe UI', 10, 'bold'))
        self.table = ttk.Treeview(table_container, show='headings', style='Roles.Treeview',
                                  columns=('index', 'time', 'speaker', 'voice', 'text'), selectmode='browse')
        for key, title, width in [('index', 'Index', 65), ('time', 'Bắt đầu', 92),
                                  ('speaker', 'Người nói', 120), ('voice', 'Giọng Việt', 158), ('text', 'Câu dịch', 475)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=55, stretch=key in ('voice','text'))
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll_y = ttk.Scrollbar(table_container, orient='vertical', command=self.table.yview)
        scroll_y.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll_y.set)
        self.table.bind('<<TreeviewSelect>>', self._select_index)
        self.table.bind('<Double-Button-1>', self.preview_selected_index)

        editor = ctk.CTkFrame(right, fg_color=CARD_BG, corner_radius=14)
        editor.grid(row=2, column=0, sticky='ew', padx=12, pady=(10, 12))
        editor.grid_columnconfigure(1, weight=1)
        editor.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(editor, text='Sửa câu đang chọn:', text_color=TEXT).grid(row=0, column=0, sticky='w', padx=12, pady=(10, 3), columnspan=4)
        ctk.CTkLabel(editor, text='Người nói', text_color=DIM).grid(row=1, column=0, sticky='w', padx=(12, 8))
        self.index_speaker_combo = ctk.CTkOptionMenu(editor, values=['SPEAKER_00'],
                                                     variable=self.index_speaker_var,
                                                     command=self.update_index_speaker, fg_color='#30363d', width=150)
        self.index_speaker_combo.grid(row=1, column=1, sticky='ew', padx=(0, 8))
        ctk.CTkLabel(editor, text='Giọng riêng', text_color=DIM).grid(row=1, column=2, sticky='w', padx=(0, 8))
        self.index_voice_combo = ctk.CTkOptionMenu(editor, values=['Dùng giọng theo vai']+self.voice_options,
                                                   variable=self.index_voice_var,
                                                   command=self.update_index_voice, fg_color='#30363d')
        self.index_voice_combo.grid(row=1, column=3, sticky='ew', padx=(0, 12))
        ctk.CTkButton(editor, text='▶ Nghe lời gốc câu này', fg_color='#3d4956', command=self.preview_selected_index).grid(row=2, column=0, columnspan=2, sticky='ew', padx=12, pady=(10, 10))
        ctk.CTkButton(editor, text='▶ Nghe mẫu giọng Việt', fg_color=GREEN, command=self.preview_selected_voice).grid(row=2, column=2, columnspan=2, sticky='ew', padx=(0, 12), pady=(10, 10))

        # Large live console: line-wrapped stack traces are visible without a popup.
        log_panel = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16)
        log_panel.grid(row=3, column=0, sticky='ew', padx=16, pady=(0, 8))
        log_panel.grid_columnconfigure(0, weight=1)
        log_title = ctk.CTkFrame(log_panel, fg_color='transparent')
        log_title.grid(row=0, column=0, sticky='ew', padx=12, pady=(9, 5))
        ctk.CTkLabel(log_title, text='🖥 LOG AI PHÂN VAI — đầy đủ lỗi và traceback',
                     font=ctk.CTkFont(size=15, weight='bold'), text_color=TEXT).pack(side='left')
        ctk.CTkButton(log_title, text='⛶ PHÓNG TO LOG', width=135, fg_color=BLUE,
                      command=self.open_large_log).pack(side='right', padx=(8, 0))
        ctk.CTkButton(log_title, text='📋 COPY TOÀN BỘ', width=130, fg_color='#3d4956',
                      command=self.copy_log).pack(side='right', padx=(8, 0))
        ctk.CTkButton(log_title, text='📂 MỞ FILE LOG', width=126, fg_color='#3d4956',
                      command=self.open_log_file).pack(side='right')
        self.log_text = ctk.CTkTextbox(log_panel, height=194, fg_color='#090e14',
                                       text_color='#d7e7f7', font=('Consolas', 12),
                                       wrap='word', border_width=1, border_color=BORDER)
        self.log_text.grid(row=1, column=0, sticky='ew', padx=12, pady=(0, 10))
        self.log_text.insert('end', 'Log sẽ hiển thị trực tiếp tại đây khi bấm QUÉT AI PYANNOTE.\n'
                                   'Nếu thất bại, app sẽ hiện toàn bộ nguyên nhân và lưu file log.\n')
        self.log_text.configure(state='disabled')

        foot = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=16)
        foot.grid(row=4, column=0, sticky='ew', padx=16, pady=(0, 12))
        foot.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(foot, text='Sẵn sàng', text_color=DIM, wraplength=850, justify='left')
        self.status_label.grid(row=0, column=0, sticky='w', padx=16, pady=14)
        self.save_btn = ctk.CTkButton(foot, text='💾 LƯU NHÁP', fg_color='#3d4956', width=135, command=self.save_draft)
        self.save_btn.grid(row=0, column=1, padx=(0, 8))
        self.approve_btn = ctk.CTkButton(foot, text='✅ DUYỆT & LƯU', fg_color=GREEN, width=165, command=self.approve)
        self.approve_btn.grid(row=0, column=2, padx=(0, 16))

    # ====================== LIVE AI DIAGNOSTIC CONSOLE ======================
    def queue_log(self, message):
        """Safe to call from the scan worker thread; no Tk operations here."""
        self._log_queue.put(redact_secrets(message, self.hf_token.get() if threading.current_thread() is threading.main_thread() else ''))

    def _begin_log(self, mode, python_path):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.log_file = os.path.join(self.folder, f'ai_phan_vai_{stamp}.log')
        self.log_lines = []
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')
        if self.log_popup_text is not None and self.log_popup and self.log_popup.winfo_exists():
            self.log_popup_text.configure(state='normal')
            self.log_popup_text.delete('1.0', 'end')
            self.log_popup_text.configure(state='disabled')
        self.queue_log('=' * 74)
        self.queue_log('AI PHÂN VAI - BẢN GHI CHẨN ĐOÁN')
        self.queue_log('Thời gian: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.queue_log('Video folder: ' + self.folder)
        self.queue_log('Python AI: ' + python_path)
        self.queue_log('Chế độ: ' + mode)
        self.queue_log('Hugging Face token: ' + ('Đã nhập (được ẩn trong log)' if self.hf_token.get().strip() else 'Chưa nhập'))
        self.queue_log('=' * 74)

    def _drain_log_queue(self):
        """Batch updates to avoid slowing scroll and Tk when libs emit long traces."""
        try:
            batch = []
            for _ in range(400):
                try:
                    line = self._log_queue.get_nowait()
                except queue.Empty:
                    break
                # Token may have been included in an exception from a library.
                batch.append(redact_secrets(line, self.hf_token.get()))
            if batch:
                block = '\n'.join(batch) + '\n'
                self.log_lines.extend(batch)
                self.log_text.configure(state='normal')
                self.log_text.insert('end', block)
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
                if self.log_popup_text is not None and self.log_popup and self.log_popup.winfo_exists():
                    self.log_popup_text.configure(state='normal')
                    self.log_popup_text.insert('end', block)
                    self.log_popup_text.see('end')
                    self.log_popup_text.configure(state='disabled')
                if self.log_file:
                    try:
                        with open(self.log_file, 'a', encoding='utf-8', errors='replace') as handle:
                            handle.write(block)
                    except OSError as e:
                        self.set_status('Không lưu được file log: ' + str(e))
        except tk.TclError:
            return
        self._log_after_id = self.after(80, self._drain_log_queue)

    def copy_log(self):
        text = '\n'.join(self.log_lines)
        # Include pending messages even if user presses Copy within 80 ms.
        with self._log_queue.mutex:
            pending = list(self._log_queue.queue)
        if pending:
            text += '\n' + '\n'.join(pending)
        self.clipboard_clear()
        self.clipboard_append(redact_secrets(text, self.hf_token.get()))
        self.set_status('Đã copy toàn bộ log. Token đã được che. Dán nội dung vào chat để kiểm tra lỗi.')

    def open_log_file(self):
        if self.log_file and os.path.isfile(self.log_file):
            show_audio(self.log_file)
        else:
            messagebox.showinfo('Chưa có file log', 'Hãy bấm QUÉT AI rồi xem log ở đây; file log được tạo khi chạy.')

    def open_large_log(self):
        if self.log_popup is not None:
            try:
                if self.log_popup.winfo_exists():
                    self.log_popup.lift()
                    self.log_popup.focus_force()
                    return
            except tk.TclError:
                pass
        win = ctk.CTkToplevel(self)
        self.log_popup = win
        win.title('AI PHÂN VAI - LOG CHI TIẾT / TRACEBACK')
        win.geometry('1180x780')
        win.minsize(850, 550)
        win.configure(fg_color=APP_BG)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(win, fg_color=PANEL_BG)
        header.grid(row=0, column=0, sticky='ew', padx=14, pady=(14, 8))
        ctk.CTkLabel(header, text='🖥 LOG AI PYANNOTE • Đọc toàn bộ traceback tại đây',
                     font=ctk.CTkFont(size=19, weight='bold')).pack(side='left', padx=16, pady=10)
        ctk.CTkButton(header, text='📋 COPY', fg_color=BLUE, width=110,
                      command=self.copy_log).pack(side='right', padx=(4, 12))
        ctk.CTkButton(header, text='📂 MỞ FILE', fg_color='#3d4956', width=120,
                      command=self.open_log_file).pack(side='right', padx=4)
        self.log_popup_text = ctk.CTkTextbox(win, font=('Consolas', 13),
                                              fg_color='#090e14', text_color='#d7e7f7',
                                              wrap='none', border_width=1, border_color=BORDER)
        self.log_popup_text.grid(row=1, column=0, sticky='nsew', padx=14, pady=(0, 14))
        if self.log_lines:
            self.log_popup_text.insert('end', '\n'.join(self.log_lines) + '\n')
        self.log_popup_text.configure(state='disabled')
        self.log_popup_text.see('end')
        def close_popup():
            self.log_popup_text = None
            self.log_popup = None
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', close_popup)
        win.lift()

    def _on_ai_scan_failed(self, detail):
        self.set_status('❌ AI phân tích thất bại. Xem LOG phía dưới hoặc bấm PHÓNG TO LOG để đọc toàn bộ lỗi.')
        self.open_large_log()

    def set_status(self, text):
        self.status_label.configure(text=text)
        self.info_label.configure(text=f"{len(self.subtitles)} câu • {len(self.project['speakers'])} người nói • {'ĐÃ DUYỆT' if self.project.get('approved') else 'CHƯA DUYỆT'}")

    def mark_dirty(self):
        self.is_dirty = True
        if self.project.get('approved'):
            self.project['approved'] = False
        self.set_status('Đã thay đổi cấu hình. Nhớ DUYỆT & LƯU lần nữa trước khi render.')

    def on_age_toggle(self):
        if self.age_var.get() and not messagebox.askyesno('Chỉ sử dụng phi thương mại',
                'Model audEERING Age/Gender có giấy phép CC BY-NC-SA 4.0 (không thương mại).\n'
                'Không dùng cho video kiếm tiền nếu chưa có giấy phép khác.\n\n'
                'Bạn xác nhận chỉ dùng trong phạm vi phi thương mại được cho phép?'):
            self.age_var.set(False)
        if self.age_var.get():
            self.gender_var.set(False)

    def _populate_speakers(self):
        for w in self.speaker_scroll.winfo_children():
            w.destroy()
        self.voice_options = get_voices(self.voices_dir)
        self.index_voice_combo.configure(values=['Dùng giọng theo vai'] + self.voice_options)
        speaker_ids = [s['id'] for s in self.project['speakers']]
        self.index_speaker_combo.configure(values=speaker_ids or ['SPEAKER_00'])
        self.filter_combo.configure(values=['Tất cả'] + speaker_ids)
        self.speaker_select = {}
        for sp in self.project['speakers']:
            sp_id = sp['id']
            card = ctk.CTkFrame(self.speaker_scroll, fg_color=CARD_BG, corner_radius=14,
                                border_width=1, border_color=BORDER)
            card.pack(fill='x', pady=5)
            n = sum(1 for x in self.project['segments'] if x.get('speaker_id') == sp_id)
            ctk.CTkLabel(card, text=f'🎤 {sp_id}  • {n} câu', text_color=TEXT,
                         font=ctk.CTkFont(size=16, weight='bold')).pack(anchor='w', padx=12, pady=(11, 3))
            age = sp.get('age_estimate')
            conf = sp.get('confidence')
            note = f"AI gợi ý: {TYPES.get(sp.get('suggested_type'), 'Chưa rõ')}"
            if age is not None:
                note += f' • tuổi ước tính {age:.0f}'
            if conf is not None:
                note += f' • {conf:.0%}'
            ctk.CTkLabel(card, text=note, text_color=DIM, wraplength=320, font=ctk.CTkFont(size=11)).pack(anchor='w', padx=12)
            ctk.CTkLabel(card, text='Loại giọng (sửa nếu AI đoán sai)', text_color=DIM).pack(anchor='w', padx=12, pady=(6, 2))
            selected_type = TYPES.get(sp.get('type'), TYPES['unknown'])
            type_combo = ctk.CTkOptionMenu(card, values=list(TYPES.values()),
                                            fg_color='#30363d', command=lambda v, sid=sp_id: self.set_speaker_type(sid, v))
            type_combo.set(selected_type)
            type_combo.pack(fill='x', padx=12)
            ctk.CTkLabel(card, text='Giọng tiếng Việt từ voices/', text_color=DIM).pack(anchor='w', padx=12, pady=(8, 2))
            choices = ['(chưa chọn)'] + self.voice_options
            current = sp.get('voice_profile') or '(chưa chọn)'
            if current not in choices:
                current = '(chưa chọn)'
            voice_combo = ctk.CTkOptionMenu(card, values=choices, fg_color='#30363d',
                                             command=lambda v, sid=sp_id: self.set_speaker_voice(sid, v))
            voice_combo.set(current)
            voice_combo.pack(fill='x', padx=12, pady=(0, 8))
            self.speaker_select[sp_id] = (type_combo, voice_combo)
            buttons = ctk.CTkFrame(card, fg_color='transparent')
            buttons.pack(fill='x', padx=12, pady=(0, 10))
            ctk.CTkButton(buttons, text='▶ Nghe gốc', width=110, height=29, fg_color=BLUE,
                          command=lambda s=sp: self.preview_speaker(s)).pack(side='left', padx=(0, 5))
            ctk.CTkButton(buttons, text='▶ Nghe giọng VN', width=124, height=29, fg_color=GREEN,
                          command=lambda s=sp_id: self.preview_speaker_voice(s)).pack(side='left')

    def find_speaker(self, speaker_id):
        return next(s for s in self.project['speakers'] if s['id'] == speaker_id)

    def set_speaker_type(self, speaker_id, label):
        sp = self.find_speaker(speaker_id)
        sp['type'] = LABEL_TO_TYPE.get(label, 'unknown')
        if not sp.get('voice_profile'):
            hint = suggest_voice(sp['type'], self.voice_options, self.vbee_meta)
            if hint:
                sp['voice_profile'] = hint
                self.speaker_select[speaker_id][1].set(hint)
        self.mark_dirty()

    def set_speaker_voice(self, speaker_id, value):
        sp = self.find_speaker(speaker_id)
        sp['voice_profile'] = '' if value == '(chưa chọn)' else value
        self.mark_dirty()
        self._refresh_voices_in_table()

    def _display_voice(self, item):
        if not item.get('speaker_id'):
            return 'CHƯA XÁC ĐỊNH'
        if item.get('voice_override'):
            return '↳ ' + item['voice_override']
        try:
            sp = self.find_speaker(item['speaker_id'])
            return sp.get('voice_profile') or 'CHƯA CHỌN'
        except StopIteration:
            return 'CHƯA CHỌN'

    def _populate_index_tree(self):
        selected = self.selected_index
        old_rows = self.table.get_children()
        if old_rows:
            self.table.delete(*old_rows)
        f = self.filter_var.get()
        for item in self.project['segments']:
            if f != 'Tất cả' and item.get('speaker_id') != f:
                continue
            idx = int(item['index'])
            sub = self.index_to_sub.get(idx, {})
            text = self.translation.get(idx) or sub.get('text', '')
            row = (idx, fmt_time(sub.get('start', 0)), item.get('speaker_id') or '⚠ Chưa rõ',
                   self._display_voice(item), text)
            self.table.insert('', 'end', iid=str(idx), values=row)
        if selected is not None and self.table.exists(str(selected)):
            self.table.selection_set(str(selected))
            self.table.see(str(selected))

    def _refresh_voices_in_table(self):
        for item in self.project['segments']:
            idx = str(item['index'])
            if self.table.exists(idx):
                self.table.set(idx, 'voice', self._display_voice(item))

    def _select_index(self, _event=None):
        selections = self.table.selection()
        if not selections:
            return
        idx = int(selections[0])
        self.selected_index = idx
        item = self._get_segment(idx)
        if item.get('speaker_id'):
            self.index_speaker_combo.set(item['speaker_id'])
        else:
            self.index_speaker_combo.set(self.project['speakers'][0]['id'])
        override = item.get('voice_override') or 'Dùng giọng theo vai'
        self.index_voice_combo.set(override)

    def _get_segment(self, idx):
        return next(s for s in self.project['segments'] if int(s['index']) == int(idx))

    def update_index_speaker(self, value):
        if self.selected_index is None:
            return
        self._get_segment(self.selected_index)['speaker_id'] = value
        self.mark_dirty()
        self._populate_index_tree()
        self._populate_speakers()

    def update_index_voice(self, value):
        if self.selected_index is None:
            return
        self._get_segment(self.selected_index)['voice_override'] = '' if value == 'Dùng giọng theo vai' else value
        self.mark_dirty()
        self._refresh_voices_in_table()

    def add_speaker(self):
        ids = {x['id'] for x in self.project['speakers']}
        n = 0
        while 'SPEAKER_%02d' % n in ids:
            n += 1
        sid = 'SPEAKER_%02d' % n
        self.project['speakers'].append({
            'id': sid, 'suggested_type': 'unknown', 'type': 'unknown',
            'confidence': None, 'age_estimate': None, 'voice_profile': '',
            'preview_start': 0.0, 'preview_end': 3.0,
        })
        self.mark_dirty()
        self._populate_speakers()
        self._populate_index_tree()

    def _source_video(self, download=False):
        if self.input_mode == 'local' and os.path.isfile(self.input_path):
            return self.input_path
        for fn in os.listdir(self.folder):
            if fn.startswith('source_video.') and fn.lower().endswith(('.mp4','.mkv','.webm','.mov','.avi')):
                return os.path.join(self.folder, fn)
        if download and self.input_mode == 'youtube':
            from core import download_video, cancel_event
            cancel_event.clear()
            download_video(self.video_id, self.folder)
            return self._source_video(download=False)
        return None

    def preview_speaker(self, sp):
        self._preview_audio_slice(sp.get('preview_start', 0), sp.get('preview_end', 3))

    def preview_selected_index(self, _event=None):
        if self.selected_index is None:
            messagebox.showinfo('Chọn câu', 'Hãy chọn câu trong danh sách trước.')
            return
        sub = self.index_to_sub.get(self.selected_index, {})
        self._preview_audio_slice(sub.get('start', 0), sub.get('end', 3))

    def _preview_audio_slice(self, start, end):
        video = self._source_video()
        if not video:
            messagebox.showinfo('Chưa có video',
                                'Chưa có source_video. Bấm QUÉT AI để app tải video về trước, hoặc tự đặt video source_video.mp4 vào thư mục này.')
            return
        if not self.ffmpeg:
            messagebox.showerror('Thiếu FFmpeg', 'Không tìm thấy FFmpeg.')
            return
        start = float(start)
        duration = min(15, max(1.5, float(end) - start))
        def task():
            try:
                dest = os.path.join(tempfile.gettempdir(), 'omnivoice_role_preview_%d.wav' % int(time.time()*1000))
                subprocess.run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                                '-ss', str(max(0, start)), '-i', video, '-vn',
                                '-t', str(duration), '-ar', '24000', '-ac', '1', dest], check=True)
                self.after(0, lambda: show_audio(dest))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror('Lỗi nghe lời gốc', msg))
        threading.Thread(target=task, daemon=True).start()

    def preview_speaker_voice(self, speaker_id):
        sp = self.find_speaker(speaker_id)
        self._open_local_voice(sp.get('voice_profile'))

    def preview_selected_voice(self):
        if self.selected_index is None:
            return
        item = self._get_segment(self.selected_index)
        sp = next((s for s in self.project['speakers'] if s['id'] == item.get('speaker_id')), None)
        self._open_local_voice(item.get('voice_override') or (sp.get('voice_profile') if sp else None))

    def _open_local_voice(self, voice):
        if not voice:
            messagebox.showwarning('Chưa chọn giọng', 'Hãy chọn giọng tiếng Việt trong voices/ trước.')
            return
        for ext in ('.wav', '.mp3', '.m4a'):
            p = os.path.join(self.voices_dir, voice + ext)
            if os.path.isfile(p):
                show_audio(p)
                return
        messagebox.showerror('Thiếu file', f'Không tìm thấy audio của giọng {voice!r}.')

    def save_draft(self):
        self.project['approved'] = False
        atomic_write_json(role_file(self.folder), self.project)
        self.is_dirty = False
        self.set_status('Đã LƯU NHÁP. Chưa được render đa giọng cho đến khi bấm DUYỆT & LƯU.')

    def approve(self):
        self.project['approved'] = False
        try:
            validate_project(self.project, self.subtitles, self.voices_dir, require_approved=False)
        except ValueError as exc:
            messagebox.showerror('Chưa duyệt được', str(exc))
            self.set_status('Phân vai chưa hoàn chỉnh, chưa được phép render.')
            return
        if not messagebox.askyesno('Xác nhận duyệt phân vai',
            'Đã NGHE và KIỂM TRA giọng người nói + giọng tiếng Việt của các vai?\n\n'
            'Nhấn YES để cho phép BƯỚC 2 RENDER dùng đúng danh sách này.'):
            return
        self.project['approved'] = True
        self.project['approved_at_local'] = time.strftime('%Y-%m-%d %H:%M:%S')
        atomic_write_json(role_file(self.folder), self.project)
        self.is_dirty = False
        self.set_status('✅ ĐÃ DUYỆT & LƯU! Bây giờ có thể đóng bảng và bấm BƯỚC 2: RENDER.')
        messagebox.showinfo('Đã duyệt', 'Render đa giọng đã được kích hoạt cho video này.\n'
                            'Nếu thay timeline, phần mềm sẽ chặn để tránh lệch index.')

    def start_ai_scan(self):
        if self.current_scan:
            return
        if (read_role_file(self.folder) or self.is_dirty) and not messagebox.askyesno('Quét lại?',
            'Quét lại sẽ thay thế bản phân vai hiện có bằng bản nháp AI.\n'
            'Các chỉnh sửa và trạng thái đã duyệt trước đó sẽ phải duyệt lại. Tiếp tục?'):
            return
        if not self.ffmpeg:
            messagebox.showerror('FFmpeg', 'Không tìm thấy ffmpeg.exe để tách audio.')
            return
        roles_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv_roles', 'Scripts', 'python.exe')
        if not os.path.isfile(roles_py):
            messagebox.showwarning('Thiếu môi trường AI',
                'Chưa cài AI phân vai. Hãy chạy CAI_AI_PHAN_VAI.bat trước.\n'
                'Vẫn có thể chỉnh vai hoàn toàn thủ công mà không cài model.')
            return
        self.current_scan = True
        self.btn_scan_ai.configure(state='disabled', text='⏳ ĐANG QUÉT AI...')
        self.set_status('Đang lấy audio và phân tích người nói; theo dõi LOG lớn bên dưới.')
        token = self.hf_token.get().strip()
        gender = self.gender_var.get()
        age = self.age_var.get()
        mode = 'Age/Gender (chỉ phi thương mại)' if age else 'Nam/Nữ' if gender else 'Chỉ phân người nói'
        self._begin_log(mode, roles_py)

        def worker():
            try:
                self.queue_log('[INPUT] Đang tìm/tải video nguồn...')
                video = self._source_video(download=True)
                if not video:
                    raise RuntimeError('Chưa có source_video trong thư mục video.')
                self.queue_log('[INPUT] Video: ' + video)
                cli = [roles_py, '-u', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'speaker_ai.py'),
                       '--input', video, '--subtitles', self.sub_path,
                       '--output', role_file(self.folder), '--ffmpeg', self.ffmpeg]
                if age:
                    cli.append('--age-gender')
                elif gender:
                    cli.append('--gender')
                env = os.environ.copy()
                if token:
                    env['HF_TOKEN'] = token
                env['PYTHONIOENCODING'] = 'utf-8'
                env['PYTHONUNBUFFERED'] = '1'
                self.queue_log('[RUN] Khởi động subprocess Python AI...')
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith('win') else 0
                proc = subprocess.Popen(cli, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace',
                                        bufsize=1, env=env, creationflags=creationflags)
                for msg in proc.stdout:
                    msg = msg.rstrip('\r\n')
                    # Do not trim indentation: it helps read nested Pyannote/torchcodec traces.
                    self.queue_log(msg.replace(token, '[HIDDEN_TOKEN]') if token else msg)
                code = proc.wait()
                self.queue_log('[EXIT] Python AI kết thúc, exit code=' + str(code))
                if code != 0:
                    raise RuntimeError('Phân tích AI thất bại (exit code %s). Xem traceback đầy đủ bên dưới.' % code)
                self.queue_log('[OK] Pyannote đã hoàn thành. Đang nạp kết quả để duyệt...')
                self.after(0, self.on_analysis_success)
            except Exception:
                self.queue_log('[FAIL] Phân tích AI thất bại. TRACEBACK ĐẦY ĐỦ:')
                self.queue_log(traceback.format_exc())
                self.after(0, lambda: self._on_ai_scan_failed('Xem log'))
            finally:
                self.after(0, self.scan_finished)
        threading.Thread(target=worker, daemon=True).start()

    def on_analysis_success(self):
        self.project = read_role_file(self.folder)
        self.is_dirty = True
        # If AI predicts an age/gender type, suggest a matching imported LOCAL Vbee voice.
        # User must still review and approve; not automatic render.
        for sp in self.project['speakers']:
            sp['voice_profile'] = suggest_voice(sp.get('type', 'unknown'), self.voice_options, self.vbee_meta)
        self.filter_var.set('Tất cả')
        self._populate_speakers()
        self._populate_index_tree()
        unknown = sum(1 for s in self.project['segments'] if not s.get('speaker_id'))
        self.set_status(f'AI tìm được {len(self.project["speakers"])} người nói. '
                        f'{unknown} câu chưa rõ người nói. Chọn giọng, sửa sai và bấm DUYỆT & LƯU.')
        self.queue_log(f'[REVIEW] Phát hiện {len(self.project["speakers"])} người nói, còn {unknown} câu chưa rõ. Chưa tự duyệt.')

    def scan_finished(self):
        self.current_scan = False
        self.btn_scan_ai.configure(state='normal', text='🧠 QUÉT AI PYANNOTE')

    def on_close(self):
        if self.current_scan:
            messagebox.showinfo('Đang quét AI', 'AI đang phân tích. Hãy giữ bảng này mở để nhận kết quả.')
            return
        if self.is_dirty:
            choice = messagebox.askyesnocancel('Lưu bản nháp?',
                'Có thay đổi chưa lưu.\n'
                'Yes: lưu NHÁP (bỏ duyệt), No: bỏ thay đổi, Cancel: ở lại.')
            if choice is None:
                return
            if choice:
                self.save_draft()
        # Flush the last partial traceback before closing the review window.
        self._drain_log_queue()
        if self._log_after_id is not None:
            try:
                self.after_cancel(self._log_after_id)
            except Exception:
                pass
        if self.log_popup is not None:
            try:
                self.log_popup.destroy()
            except Exception:
                pass
        self.hf_token.set('')
        self.destroy()
