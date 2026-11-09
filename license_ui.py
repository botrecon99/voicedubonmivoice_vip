# -*- coding: utf-8 -*-
"""CustomTkinter activation window and version management UI."""
import datetime
import os
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from license_client import (APP_VERSION, LicenseError, validate_license, saved_key,
                            save_key, clear_key, short_key, download_update,
                            require_active_license)

BG='#0c111b'; PANEL='#172231'; ACCENT='#eebc57'; BLUE='#307be4'


def when(root, func):
    try:
        if root.winfo_exists(): root.after(0, func)
    except (RuntimeError, tk.TclError):
        pass


def fmt_date(raw):
    try:
        d=datetime.datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        return d.astimezone().strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError):
        return str(raw)


def async_call(root, task, on_success, on_failure):
    def run():
        try: outcome=task()
        except Exception as e:
            text=str(e)
            when(root,lambda: on_failure(text))
        else:
            when(root,lambda: on_success(outcome))
    threading.Thread(target=run,daemon=True).start()


def open_parent(path):
    try:
        if os.name=='nt': os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(['xdg-open',str(path)])
    except Exception:
        pass


class LicenseGate(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.allowed=False
        self.info=None
        self.pending_release=None
        self.busy=False
        self.title('AI Dubbing Studio • Kích hoạt license')
        self.geometry('570x420');self.resizable(False,False);self.configure(fg_color=BG)
        wrap=ctk.CTkFrame(self,fg_color=PANEL,corner_radius=16)
        wrap.pack(fill='both',expand=True,padx=22,pady=22)
        ctk.CTkLabel(wrap,text='🔐 KÍCH HOẠT AI DUBBING',font=ctk.CTkFont(size=24,weight='bold'),text_color=ACCENT).pack(pady=(27,8))
        ctk.CTkLabel(wrap,text='Key dùng trên nhiều máy • Không khóa HWID • Kiểm tra hạn online',text_color='#adbad0').pack()
        self.entry=ctk.CTkEntry(wrap,height=42,width=460,placeholder_text='ADS-XXXXXX-XXXXXX-XXXXXX-XXXXXX')
        self.entry.pack(pady=(22,9)); self.entry.insert(0,saved_key())
        self.info_lbl=ctk.CTkLabel(wrap,text='Nhập key để kích hoạt.',wraplength=460,text_color='#b4c8e4')
        self.info_lbl.pack(padx=16,pady=(0,12))
        row=ctk.CTkFrame(wrap,fg_color='transparent');row.pack(pady=7)
        self.btn=ctk.CTkButton(row,text='✅ XÁC THỰC & MỞ APP',width=220,height=40,fg_color=BLUE,command=self.check_key)
        self.btn.pack(side='left',padx=5)
        self.download_btn=ctk.CTkButton(row,text='⬇️ TẢI BẢN MỚI',width=160,height=40,fg_color='#3b4b62',command=self.fetch_update,state='disabled')
        self.download_btn.pack(side='left',padx=5)
        ctk.CTkLabel(wrap,text='Ứng dụng yêu cầu Internet để kiểm tra license. Không thu thập ID thiết bị.',text_color='#8392a8',font=ctk.CTkFont(size=11)).pack(pady=(21,5))
        self.entry.bind('<Return>',lambda e:self.check_key())
        if saved_key(): self.after(350,self.check_key)

    def label(self,message,color='#b4c8e4'):
        self.info_lbl.configure(text=message,text_color=color)

    def check_key(self):
        if self.busy: return
        key=self.entry.get().strip().upper();self.busy=True
        self.btn.configure(state='disabled',text='Đang kiểm tra...')
        def okay(result):
            self.busy=False;self.info=result;self.pending_release=result.get('latest_version')
            save_key(key)
            if result.get('update_required'):
                self.btn.configure(state='normal',text='✅ XÁC THỰC & MỞ APP')
                self.label('License hợp lệ nhưng PHẢI cập nhật bản '+str(self.pending_release.get('version'))+' trước khi mở app.','#ffd28b')
                self.download_btn.configure(state='normal')
                return
            self.allowed=True
            self.destroy()
        def failed(text):
            self.busy=False;self.btn.configure(state='normal',text='✅ XÁC THỰC & MỞ APP')
            self.label('⛔ '+text,'#ffb5b5')
        async_call(self,lambda:validate_license(key),okay,failed)

    def fetch_update(self):
        if not self.pending_release:return
        self.download_btn.configure(state='disabled')
        self.label('Đang tải gói cập nhật, kiểm tra SHA256...')
        def okay(path):
            self.label('Đã tải, xác minh SHA256: '+str(path))
            self.download_btn.configure(state='normal')
            messagebox.showinfo('Cập nhật','Đã tải file ZIP:\n'+str(path)+'\n\nĐóng Studio và cài đặt bản mới thủ công. Không tự ghi đè code.')
            open_parent(path.parent)
        def failed(text):
            self.download_btn.configure(state='normal');self.label('⛔ '+text,'#ffb5b5')
        async_call(self,lambda:download_update(self.pending_release),okay,failed)


def show_license_window(parent):
    win=ctk.CTkToplevel(parent)
    win.title('License & Phiên bản • AI Dubbing Studio')
    win.geometry('550x380');win.resizable(False,False);win.configure(fg_color=BG)
    win.transient(parent)
    wrap=ctk.CTkFrame(win,fg_color=PANEL,corner_radius=15);wrap.pack(fill='both',expand=True,padx=15,pady=15)
    ctk.CTkLabel(wrap,text='🔐 LICENSE & CẬP NHẬT',font=ctk.CTkFont(size=20,weight='bold'),text_color=ACCENT).pack(pady=(20,8))
    key_label=ctk.CTkLabel(wrap,text='Key: '+short_key(saved_key()),text_color='#adc1d8')
    key_label.pack(pady=4)
    label=ctk.CTkLabel(wrap,text='Phiên bản: '+APP_VERSION+'\nĐang dùng...',text_color='#c3d4e7',wraplength=475,justify='left')
    label.pack(padx=20,pady=12)
    row=ctk.CTkFrame(wrap,fg_color='transparent');row.pack(pady=6)
    reload_btn=ctk.CTkButton(row,text='🔄 Kiểm tra',fg_color=BLUE,width=140)
    reload_btn.pack(side='left',padx=5)
    dl_btn=ctk.CTkButton(row,text='⬇️ Tải cập nhật',fg_color='#3b4b62',width=145,state='disabled')
    dl_btn.pack(side='left',padx=5)
    newkey_btn=ctk.CTkButton(row,text='🔑 Đổi key',width=110,fg_color='#3b4b62')
    newkey_btn.pack(side='left',padx=5)
    state={'release':None}

    def refresh():
        reload_btn.configure(state='disabled');label.configure(text='Đang kết nối máy chủ license...')
        def okay(info):
            reload_btn.configure(state='normal')
            state['release']=info.get('latest_version')
            version=(state['release'] or {}).get('version','Chưa phát hành')
            label.configure(text='Bản đang dùng: '+APP_VERSION+'\nKey hết hạn: '+fmt_date(info.get('expires_at'))+'\nBản mới nhất: '+version+('\n⚠ BẮT BUỘC CẬP NHẬT' if info.get('update_required') else '\nCó bản cập nhật mới' if info.get('update_available') else '\nĐang là bản hiện hành'))
            dl_btn.configure(state='normal' if info.get('update_available') else 'disabled')
        def failure(text):
            reload_btn.configure(state='normal');dl_btn.configure(state='disabled')
            label.configure(text='⛔ '+text+'\n\nBản đang dùng: '+APP_VERSION)
        async_call(win,validate_license,okay,failure)
    reload_btn.configure(command=refresh)

    def dl():
        release=state['release']
        if not release:return
        dl_btn.configure(state='disabled')
        label.configure(text='Đang tải ZIP và kiểm tra mã SHA256...')
        def okay(path):
            dl_btn.configure(state='normal');messagebox.showinfo('Tải xong','Gói ZIP đã được kiểm tra SHA256:\n'+str(path))
            open_parent(path.parent);refresh()
        def failed(text):
            dl_btn.configure(state='normal');messagebox.showerror('Tải lỗi',text);refresh()
        async_call(win,lambda:download_update(release),okay,failed)
    dl_btn.configure(command=dl)

    def change_key():
        dialog=ctk.CTkInputDialog(text='Nhập key mới:',title='Đổi license key')
        val=dialog.get_input()
        if not val:return
        label.configure(text='Đang xác thực key mới...')
        def okay(result):
            save_key(val)
            key_label.configure(text='Key: '+short_key(saved_key()))
            refresh()
            if result.get('update_required'): messagebox.showwarning('Cập nhật','License hợp lệ nhưng bản mới đã được bắt buộc cập nhật.')
        def failed(text):messagebox.showerror('License',text);refresh()
        async_call(win,lambda:validate_license(val),okay,failed)
    newkey_btn.configure(command=change_key)
    refresh()
    return win


def attach_ui(app, start_info):
    app._license_info=start_info
    try:
        frame=ctk.CTkFrame(app.sidebar,fg_color='#202d40',corner_radius=9)
        frame.pack(side='bottom',fill='x',padx=12,pady=(2,12))
        btn=ctk.CTkButton(frame,text='🔐 License & Phiên bản',command=lambda:show_license_window(app),fg_color='#354d6a')
        btn.pack(fill='x',padx=7,pady=(7,4))
        def status_text(info):
            value='Hết hạn: '+fmt_date(info.get('expires_at'))
            if info.get('update_available'):
                value+='\n⬆ Có bản '+str((info.get('latest_version') or {}).get('version','mới'))
            return value
        status=ctk.CTkLabel(frame,text=status_text(start_info),font=ctk.CTkFont(size=11),text_color='#c1d1e8')
        status.pack(padx=7,pady=(0,6))
        app._license_status=status
    except Exception:
        return
    def periodic():
        def okay(result):
            app._license_info=result
            status.configure(text=status_text(result))
            # Do not blindly enable buttons here: a long EXTRACT/RENDER job
            # might still be using them in disabled state.

        def fail(text):
            status.configure(text='⚠ License cần kiểm tra lại')
            # Prevent new jobs until the connection/license issue is resolved.
            try:
                app.btn_step1.configure(state='disabled')
                app.btn_step2.configure(state='disabled')
            except Exception:pass
        async_call(app,require_active_license,okay,fail)
        app.after(15*60*1000,periodic)
    app.after(15*60*1000,periodic)


def launch_with_license(app_cls):
    gate=LicenseGate()
    gate.mainloop()
    if not gate.allowed: return
    app=app_cls()
    attach_ui(app,gate.info)
    app.mainloop()
