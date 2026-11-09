# -*- coding: utf-8 -*-
import os
import re
import json
import shutil
import subprocess
import sys
import threading
import wave
import platform
import hashlib
import ctypes
import requests
import time
from concurrent.futures import ThreadPoolExecutor

import torch
import whisper
import torchaudio
from omnivoice import OmniVoice
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
from proglog import ProgressBarLogger

import logging
logging.getLogger("transformers").setLevel(logging.ERROR)

BASE_DATA_FOLDER = "downloaded_data"
COOKIE_YOUTUBE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_LOCAL_PATH = os.path.join(CURRENT_DIR, "ffmpeg.exe")

if os.path.exists(FFMPEG_LOCAL_PATH): 
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_LOCAL_PATH
else:
    import imageio_ffmpeg
    FFMPEG_LOCAL_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_LOCAL_PATH

cancel_event = threading.Event()
voice_lock = threading.Lock()
OMNIVOICE_MODEL = None

class ProcessCanceledException(Exception): pass

def log_info(msg): print(f"🔵 [INFO] {msg}")
def log_success(msg): print(f"✅ [SUCCESS] {msg}")
def log_warn(msg): print(f"⚠️ [WARN] {msg}")
def log_error(msg, e=None): print(f"❌ [ERROR] {msg}")

if platform.system() == 'Windows':
    try: ctypes.windll.msvcrt._setmaxstdio(2048)
    except: pass

def load_omnivoice_model():
    global OMNIVOICE_MODEL
    with voice_lock:
        if OMNIVOICE_MODEL is None:
            log_info("🧠 Đang nạp OmniVoice lên VRAM (RTX 3060 - FP16)...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            OMNIVOICE_MODEL = OmniVoice.from_pretrained("k2-fsa/OmniVoice", dtype=torch.float16)
            OMNIVOICE_MODEL.to(device)
            log_success("✅ Đã load OmniVoice hoàn tất!")

class MyBarLogger(ProgressBarLogger):
    def __init__(self, progress_func=None):
        super().__init__()
        self.progress_func = progress_func
    def bars_callback(self, bar, attr, value, old_value=None):
        if cancel_event.is_set(): raise ProcessCanceledException("🛑 Tiến trình Render bị hủy!")
        if bar == 't' and self.progress_func and self.bars[bar]['total'] > 0:
            self.progress_func(int(60 + ((value / self.bars[bar]['total']) * 40)), "Đang Render mã hóa MP4 (NVENC)...")

def extract_video_id(url):
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def generate_srt_file(subtitles, output_path):
    def format_ts(s):
        ms = int((s - int(s)) * 1000)
        m, s = divmod(int(s), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles):
            f.write(f"{i+1}\n{format_ts(sub['start'])} --> {format_ts(sub['end'])}\n{sub['text']}\n\n")

def translate_and_map(video_id, subtitles_list, web_cookie, src_lang, target_lang):
    log_info(f"🔄 Đang dịch {len(subtitles_list)} câu từ '{src_lang}' sang '{target_lang}' qua Transduck API...")
    url = "https://yd.transduck.com/api/v2/translateAll"
    headers = {'User-Agent': 'Mozilla/5.0', 'Cookie': web_cookie, 'Content-Type': 'application/json'}
    try:
        response = requests.post(url, 
            params={'language': src_lang, 'to': target_lang, 'videoId': video_id, 'platform': 'pc'}, 
            headers=headers, 
            json=[item['text'] for item in subtitles_list], 
            timeout=60
        )
        if response.status_code != 200: raise Exception(f"API Dịch lỗi với mã: {response.status_code}")
        translations = response.json().get("translations", [])
        for i, item in enumerate(subtitles_list):
            if i < len(translations): 
                item['text'] = (translations[i].get("text", "") if isinstance(translations[i], dict) else str(translations[i])).strip()
        return subtitles_list
    except Exception as e: 
        log_error("Lỗi khi gọi Transduck API", e)
        raise Exception(f"Lỗi dịch thuật API: {str(e)}")

class YouTubeProExtractor:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True, 'skip_download': True, 'ignore_no_formats_error': True, 'format': 'none',
            'extractor_args': {'youtube': {'player_client': ['all']}}
        }
        if os.path.exists(COOKIE_YOUTUBE_FILE): self.ydl_opts['cookiefile'] = COOKIE_YOUTUBE_FILE

    def get_available_subs(self, video_id):
        import yt_dlp
        opts = self.ydl_opts.copy()
        opts['listsubtitles'] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            subs = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})
            lang_dict = {}
            
            def is_valid_lang(code):
                c = code.lower()
                return "-" not in c or c == "en-us" or c.endswith("-orig") or c.endswith("-manual")

            for lang_code, formats in subs.items():
                if is_valid_lang(lang_code):
                    name = formats[0].get('name', lang_code) if formats else lang_code
                    lang_dict[lang_code] = f"{name} [Sub Gốc]"
                
            for lang_code, formats in auto_subs.items():
                if lang_code not in lang_dict and is_valid_lang(lang_code):
                    name = formats[0].get('name', lang_code) if formats else lang_code
                    lang_dict[lang_code] = f"{name} [Tự động]"
                    
            return lang_dict
        except Exception as e: return {}

    # FIX: phan biet sub theo CUM (en) va sub theo TU (en-orig).
    # YouTube JSON3 en thuong khong co tOffsetMs; moi event la ca mot cum.
    # Tuyet doi khong ep duration moi event ve 0.8 giay.
    def get_subtitle_data(self, video_id, output_folder, lang_code):
        if cancel_event.is_set():
            raise ProcessCanceledException("Da huy")
        try:
            import yt_dlp
            raw_file_path = os.path.join(output_folder, f"raw_youtube_{lang_code}.json")
            if os.path.exists(raw_file_path):
                with open(raw_file_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            else:
                session = requests.Session()
                opts = self.ydl_opts.copy()
                opts.update({'writesubtitles': True, 'writeautomaticsub': True,
                             'subtitleslangs': [lang_code]})
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"https://www.youtube.com/watch?v={video_id}", download=False)
                track = (info.get('subtitles', {}).get(lang_code)
                         or info.get('automatic_captions', {}).get(lang_code))
                if not track:
                    return []
                sub_url = next((x.get('url') for x in track
                                if 'json3' in x.get('url', '')), None)
                if not sub_url:
                    return []
                time.sleep(3)
                resp = session.get(sub_url, timeout=15)
                resp.raise_for_status()
                raw_data = resp.json()
                with open(raw_file_path, 'w', encoding='utf-8') as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=4)

            events = raw_data.get('events', [])
            has_word_offsets = any(
                'tOffsetMs' in seg
                for event in events for seg in event.get('segs', []))

            def clean_text(value):
                value = re.sub(r"\[[^\]]*\]|\([^)]*\)|[♪♫]", "", value)
                return re.sub(r"\s+", " ", value).strip()

            if not has_word_offsets:
                # Caption events: giu nguyen start/dDurationMs cua YouTube.
                parsed = []
                for e in events:
                    segs = e.get('segs') or []
                    value = clean_text(''.join(s.get('utf8', '') for s in segs))
                    if not value:
                        continue
                    start = max(0., e.get('tStartMs', 0) / 1000.)
                    duration = max(0., e.get('dDurationMs', 0) / 1000.)
                    parsed.append({'text': value, 'index': len(parsed),
                                   'start': start, 'end': start + duration})
                for i, s in enumerate(parsed):
                    next_start = (parsed[i+1]['start'] if i+1 < len(parsed)
                                  else float('inf'))
                    if s['end'] <= s['start']:
                        s['end'] = min(next_start, s['start'] + 2.0)
                    if next_start > s['start']:
                        s['end'] = min(s['end'], next_start)
                    s['end'] = max(s['start'] + .10, s['end'])
                return parsed

            # Rolling auto captions / en-orig: tOffsetMs la mốc thời gian từng từ.
            words = []
            for e in events:
                origin = e.get('tStartMs', 0) / 1000.
                for seg in e.get('segs', []):
                    value = clean_text(seg.get('utf8', ''))
                    if not value:
                        continue
                    words.append({'text': value,
                                  'start': origin + seg.get('tOffsetMs', 0)/1000.})
            words.sort(key=lambda x: x['start'])
            unique = []
            for w in words:
                if (unique and w['text'] == unique[-1]['text']
                        and abs(w['start'] - unique[-1]['start']) < .10):
                    continue
                unique.append(w)

            parsed, group = [], []
            def flush_group():
                if not group:
                    return
                text = ' '.join(w['text'] for w in group).strip()
                # Kết thúc tương đối sau tiếng cuối, không chờ tới tiếng của câu kế.
                s = group[0]['start']
                last = group[-1]['start']
                ending = min(last + .65, group[-1].get('next_start', last + .65))
                parsed.append({'text': text, 'index': len(parsed),
                               'start': s, 'end': max(s + .25, ending)})
                group.clear()

            for i, w in enumerate(unique):
                next_start = unique[i+1]['start'] if i + 1 < len(unique) else w['start']+.65
                w['next_start'] = next_start
                if group:
                    gap = w['start'] - group[-1]['start']
                    last_end = min(group[-1]['start'] + .65, w['start'])
                    silence_gap = w['start'] - last_end
                    prev = group[-1]['text']
                    if (silence_gap > .55 or
                        (prev.endswith(('.', '?', '!', '…')) and gap > .45) or
                        len(' '.join(x['text'] for x in group)) > 160):
                        flush_group()
                group.append(w)
            flush_group()
            return parsed
        except Exception as e:
            raise Exception(f"Loi lay sub JSON3: {e}")

def export_text_for_llm(subtitles_list, output_txt_path):
    with open(output_txt_path, 'w', encoding='utf-8') as f:
        for sub in subtitles_list:
            f.write(f"[{sub['index']}] ({sub['end']-sub['start']:.2f}s) {sub['text']}\n")
    print(f"✅ Đã bóc text ra file: {output_txt_path}")

# Hàm 2: Nhồi Text tiếng Việt vào lại Timeline
def import_text_from_llm(json_path, translated_txt_path, output_json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        subs = json.load(f)
        
    with open(translated_txt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    translation_map = {}
    for line in lines:
        line = line.strip()
        if not line: continue
        match = re.match(r'\[(\d+)\]\s+(.*)', line)
        if match:
            idx = int(match.group(1))
            text_vn = match.group(2)
            translation_map[idx] = text_vn
            
    # Lắp ráp 1-1
    for sub in subs:
        idx = sub['index']
        if idx in translation_map:
            sub['text'] = translation_map[idx]
            
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(subs, f, ensure_ascii=False, indent=4)
    print(f"✅ Đã chèn tiếng Việt vào Timeline thành công!")
    return subs
# ==============================================================================
# [🔥 BẢN NÂNG CẤP TỪ STUDIO] CẮT CÂU LOCAL BẰNG WHISPER KẾT HỢP CHUẨN NETFLIX
# ==============================================================================
def transcribe_local_video_with_whisper(video_path, output_folder, whisper_model="base", source_lang="auto", callback=None):
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    audio_path = os.path.join(output_folder, "local_source_audio.wav")
    
    if callback: callback(3, "Đang trích xuất Audio từ Video Local...")
    cmd_extract = [FFMPEG_LOCAL_PATH, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", audio_path]
    subprocess.run(cmd_extract, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    if callback: callback(6, f"Kích hoạt Whisper model '{whisper_model}' (Chế độ Word-Level)...")
    model = whisper.load_model(whisper_model, device="cuda" if torch.cuda.is_available() else "cpu")
    
    transcribe_options = {
        "word_timestamps": True,
        "condition_on_previous_text": False,  
        "compression_ratio_threshold": 2.4,   
        "no_speech_threshold": 0.6            
    }
    
    if source_lang and source_lang.lower() != "auto":
        transcribe_options["language"] = source_lang
        if callback: callback(7, f"Đã ép cứng nhận diện ngôn ngữ: {source_lang}")

    result = model.transcribe(audio_path, **transcribe_options)
    detected_lang = result.get("language", source_lang if source_lang != "auto" else "en")
    
    all_words = []
    for seg in result.get("segments", []):
        if "words" in seg:
            for w in seg["words"]:
                txt = w["word"].strip()
                if txt: all_words.append({"text": txt, "start": w["start"], "end": w["end"]})
        else:
            txt = seg["text"].strip()
            if txt: all_words.append({"text": txt, "start": seg["start"], "end": seg["end"]})
                
    parsed_subs = []
    curr_words = []
    curr_start = -1
    last_end = -1
    consecutive_repeats = 0 
    
    for i, w in enumerate(all_words):
        gap = w["start"] - last_end if last_end != -1 else 0
        word_text = w["text"].strip()
        
        # Bẫy chống lặp từ (Bảo lưu từ bản cũ cực kỳ hiệu quả)
        if len(curr_words) > 0 and word_text == curr_words[-1]:
            consecutive_repeats += 1
            if consecutive_repeats >= 2: continue
        else:
            consecutive_repeats = 0 

        if detected_lang in ['zh', 'ja']: current_text = "".join(curr_words)
        else: current_text = " ".join(curr_words)
            
        ends_with_punc = current_text[-1] in ['.', '?', '!', '。', '？', '！', ','] if current_text else False
        
        # Tiêu chuẩn Studio
        is_too_long = len(current_text) >= 140
        is_natural_pause = gap > 0.6
        is_clause_end = ends_with_punc and gap > 0.3

        if curr_start != -1 and (is_too_long or is_natural_pause or is_clause_end):
            parsed_subs.append({"text": current_text.strip(), "index": len(parsed_subs), "start": curr_start, "end": last_end})
            curr_words = []
            curr_start = -1
            
        if curr_start == -1: curr_start = w["start"]
        curr_words.append(word_text)
        last_end = w["end"]
        
        if i == len(all_words) - 1 and curr_words:
            if detected_lang in ['zh', 'ja']: final_text = "".join(curr_words)
            else: final_text = " ".join(curr_words)
            parsed_subs.append({"text": final_text.strip(), "index": len(parsed_subs), "start": curr_start, "end": last_end})
            
    return parsed_subs, detected_lang


# ==============================================================================
# [🔥 NÂNG CẤP STUDIO 1] MASTERING ÂM THANH PHÒNG THU (DSP)
# ==============================================================================
def apply_studio_mastering(input_path, output_path):
    """
    Giả lập bộ lọc Audio DSP của OmniVoice Studio (Chuẩn Broadcast/Podcast).
    Làm giọng AI ấm hơn, đều âm lượng và triệt tiêu rè.
    """
    try:
        dsp_filters = "highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,alimiter=limit=-1.0dB"
        subprocess.run([
            FFMPEG_LOCAL_PATH, '-y', '-i', input_path, 
            '-filter:a', dsp_filters, 
            '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-vn', output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path
    except Exception as e:
        print(f"⚠️ [LỖI DSP] Bỏ qua Mastering do lỗi: {e}")
        # Fallback copy nếu bị lỗi
        shutil.copyfile(input_path, output_path)
        return output_path


# ==============================================================================
# [🔥 NÂNG CẤP STUDIO 3] BATCHING & ĐA LUỒNG CHO TTS (Tối đa hóa GPU)
# ==============================================================================
# ==============================================================================
# [🔥 NÂNG CẤP STUDIO 3.1] BATCHING & ĐA LUỒNG (CÓ KHÓA AN TOÀN CHỐNG CRASH)
# ==============================================================================
def _check_tts_audio(path):
    """Return an error description for a missing, empty, corrupt or silent WAV.

    Streaming validation keeps memory use small even for long clips.
    A WAV header is not proof that the file contains audio samples.
    """
    import numpy as np
    import soundfile as sf

    if not os.path.isfile(path):
        return "khong ton tai"
    if os.path.getsize(path) < 256:
        return "file qua nho / rong"
    try:
        with sf.SoundFile(path, 'r') as f:
            sr = f.samplerate
            frames = len(f)
            if sr < 8000 or frames < max(400, int(sr * 0.08)):
                return f"khong du mau am thanh (frames={frames}, sr={sr})"
            # Detect wholly-silent clips without reading everything into RAM.
            has_voice = False
            for chunk in f.blocks(blocksize=65536, dtype='float32', always_2d=True):
                if not np.isfinite(chunk).all():
                    return "co gia tri am thanh NaN/Inf"
                if np.any(np.abs(chunk) > 0.00001):
                    has_voice = True
            if not has_voice:
                return f"WAV hop le ve header nhung im lang hoan toan ({frames / sr:.2f}s)"
    except Exception as exc:
        return f"WAV bi hong/khong doc duoc: {exc}"
    return None


def generate_local_dubbing(video_id, subs, folder, target_lang, profile_id, callback, num_threads=3):
    """Generate only missing/changed/damaged clips, validate before caching.

    A failed generation now stops the render with the exact subtitle index.
    Already good clips remain cached, so retrying render is incremental.
    """
    total = len(subs)
    completed_count = 0
    count_lock = threading.Lock()
    load_omnivoice_model()
    voices_folder = os.path.join(CURRENT_DIR, "voices")

    def report_done():
        nonlocal completed_count
        with count_lock:
            completed_count += 1
            done = completed_count
        if callback:
            callback(20 + int((done / max(1, total)) * 30),
                     f"Dang sinh giong AI: {done}/{total}")

    def process_single_tts(item):
        if cancel_event.is_set():
            raise ProcessCanceledException("Da huy TTS.")

        selected_profile = item.get('voice_profile') or profile_id
        ref_audio = None
        for ext in ('.wav', '.mp3', '.m4a'):
            candidate = os.path.join(voices_folder, selected_profile + ext)
            if os.path.isfile(candidate):
                ref_audio = candidate
                break
        if not ref_audio:
            raise FileNotFoundError(
                f"Khong tim thay giong tai index [{item['index']}]: {selected_profile}")

        idx = int(item['index']) + 1
        output_file = os.path.join(folder, f"audio_{idx:05d}.wav")
        raw_file = os.path.join(folder, f"raw_{idx:05d}.wav")
        temp_output = os.path.join(folder, f"audio_{idx:05d}.working.wav")
        meta_file = output_file + '.meta.json'
        temp_meta = meta_file + '.writing'

        voice_info = os.stat(ref_audio)
        fingerprint = hashlib.sha256(json.dumps({
            "text": item['text'], "language": target_lang,
            "profile": selected_profile, "ref_size": voice_info.st_size,
            "ref_modified": voice_info.st_mtime_ns, "engine": "OmniVoice32"
        }, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

        existing_hash = None
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, encoding='utf-8') as mf:
                    existing_hash = json.load(mf).get('fingerprint')
            except (OSError, ValueError):
                pass

        # Old code only checked >1024 bytes. Empty/silent WAVs could pass.
        old_issue = _check_tts_audio(output_file) if os.path.isfile(output_file) else "chua co file"
        if existing_hash == fingerprint and old_issue is None:
            report_done()
            return
        if old_issue and old_issue != "chua co file":
            log_warn(f"[TTS CACHE] index [{item['index']}] {os.path.basename(output_file)} "
                     f"khong hop le: {old_issue}. Tu dong tao lai.")

        # Delete stale/corrupted cache; do not leave a valid .meta.json behind.
        for old in (output_file, meta_file, raw_file, temp_output, temp_meta):
            if os.path.isfile(old):
                os.remove(old)

        last_error = None
        for attempt in range(1, 4):
            if cancel_event.is_set():
                raise ProcessCanceledException("Da huy TTS.")
            try:
                # OmniVoice GPU access must remain sequential.
                with voice_lock:
                    audio_data = OMNIVOICE_MODEL.generate(
                        text=item['text'],
                        ref_audio=ref_audio,
                        num_step=32,
                        language=target_lang,
                        preprocess_prompt=False)

                wav_array = (audio_data[0] if isinstance(audio_data, list) and audio_data
                             else audio_data)
                if wav_array is None:
                    raise ValueError('OmniVoice tra ve None')
                wav_tensor = torch.as_tensor(wav_array).detach().cpu().float()
                if wav_tensor.ndim == 1:
                    wav_tensor = wav_tensor.unsqueeze(0)
                elif wav_tensor.ndim == 2 and wav_tensor.shape[0] > 2 and wav_tensor.shape[1] <= 2:
                    wav_tensor = wav_tensor.T
                if wav_tensor.ndim != 2 or wav_tensor.shape[0] not in (1, 2):
                    raise ValueError(f'OmniVoice tra ve shape khong hop le: {tuple(wav_tensor.shape)}')

                sr = int(getattr(OMNIVOICE_MODEL, 'sample_rate', 24000))
                if (wav_tensor.numel() == 0 or wav_tensor.shape[1] < max(400, int(sr * 0.08))):
                    raise ValueError(f'OmniVoice sinh audio rong/qua ngan, shape={tuple(wav_tensor.shape)}')
                if not torch.isfinite(wav_tensor).all().item():
                    raise ValueError('OmniVoice sinh audio co NaN/Inf')
                if float(wav_tensor.abs().max().item()) <= 0.00001:
                    raise ValueError('OmniVoice sinh waveform im lang hoan toan')

                torchaudio.save(raw_file, wav_tensor, sr, backend='soundfile')
                raw_issue = _check_tts_audio(raw_file)
                if raw_issue:
                    raise ValueError(f'Audio TTS raw khong hop le: {raw_issue}')

                # Render to .working.wav and publish only after successful validation.
                apply_studio_mastering(raw_file, temp_output)
                output_issue = _check_tts_audio(temp_output)
                if output_issue:
                    raise ValueError(f'Audio sau DSP khong hop le: {output_issue}')

                os.replace(temp_output, output_file)
                with open(temp_meta, 'w', encoding='utf-8') as mf:
                    json.dump({'fingerprint': fingerprint}, mf)
                os.replace(temp_meta, meta_file)
                if os.path.exists(raw_file):
                    os.remove(raw_file)
                if attempt > 1:
                    log_success(f'[TTS] index [{item["index"]}] da tao lai thanh cong lan {attempt}.')
                report_done()
                return

            except Exception as exc:
                last_error = exc
                log_warn(f'[TTS] index [{item["index"]}] voice={selected_profile!r} '
                         f'lan {attempt}/3 that bai: {exc}')
                for temp_path in (raw_file, temp_output, temp_meta):
                    if os.path.isfile(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                if attempt < 3:
                    time.sleep(0.25)

        raise RuntimeError(
            f'TTS LOI index [{item["index"]}] (audio_{idx:05d}.wav), '
            f'giong={selected_profile!r}, sau 3 lan sinh lai. '
            f'Chi tiet: {last_error}. Cac cau khac van duoc cache; '
            'sua van de nay roi bam BUOC 2 de thu lai.') from last_error

    with ThreadPoolExecutor(max_workers=max(1, int(num_threads))) as executor:
        # Unlike the old "except: log_error" approach, propagate TTS failures.
        for _ in executor.map(process_single_tts, subs):
            pass

    invalid = []
    for item in subs:
        idx = int(item['index']) + 1
        path = os.path.join(folder, f"audio_{idx:05d}.wav")
        reason = _check_tts_audio(path)
        if reason:
            invalid.append(f"[{item['index']}]: {reason}")
    if invalid:
        raise RuntimeError(
            'Khong duoc ghep video vi co audio TTS hong/rong: ' +
            '; '.join(invalid[:12]))


def process_tts_standalone(text, profile_id, target_lang, speed_factor, pitch_factor, volume_percent, output_file, callback):
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    if callback: callback(10, "Đang khởi tạo OmniVoice Clone AI...")
    load_omnivoice_model()

    voices_folder = os.path.join(CURRENT_DIR, "voices")
    ref_audio = None
    for ext in ['.wav', '.mp3', '.m4a']:
        candidate = os.path.join(voices_folder, f"{profile_id}{ext}")
        if os.path.exists(candidate):
            ref_audio = candidate
            break

    if not ref_audio:
        raise Exception(f"Không tìm thấy giọng Clone tên: {profile_id}")

    if callback: callback(40, "Đang tổng hợp giọng nói từ văn bản...")
    try:
        audio_data = OMNIVOICE_MODEL.generate(text=text, ref_audio=ref_audio, num_step=32, language=target_lang)
        wav_array = audio_data[0] if isinstance(audio_data, list) and len(audio_data) > 0 else audio_data
        wav_tensor = torch.from_numpy(wav_array).float()

        if wav_tensor.ndim == 1: wav_tensor = wav_tensor.unsqueeze(0)
        elif wav_tensor.ndim == 2 and wav_tensor.shape[0] > 2 and wav_tensor.shape[1] <= 2: wav_tensor = wav_tensor.T

        sr = int(getattr(OMNIVOICE_MODEL, 'sample_rate', 24000))
        raw_out = os.path.join(os.path.dirname(output_file), "temp_raw_tts.wav")
        torchaudio.save(raw_out, wav_tensor, sr, backend="soundfile")
    except Exception as e:
        raise Exception(f"Lỗi khi sinh giọng: {str(e)}")

    if callback: callback(70, "Đang áp dụng bộ lọc Pitch, Speed và Volume (FFmpeg)...")
    
    speed = max(0.5, min(2.0, speed_factor))
    pitch = max(0.5, min(2.0, pitch_factor))
    vol = volume_percent / 100.0

    overall_atempo = (1.0 / pitch) * speed
    atempo_filters = []
    
    while overall_atempo > 2.0:
        atempo_filters.append("atempo=2.0")
        overall_atempo /= 2.0
    while overall_atempo < 0.5:
        atempo_filters.append("atempo=0.5")
        overall_atempo *= 2.0
    atempo_filters.append(f"atempo={overall_atempo}")
    
    atempo_str = ",".join(atempo_filters)
    # Tích hợp cả Mastering cho standalone audio
    filter_str = f"highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,alimiter=limit=-1.0dB,volume={vol},asetrate={sr}*{pitch},aresample={sr},{atempo_str}"

    cmd = [FFMPEG_LOCAL_PATH, "-y", "-i", raw_out, "-filter:a", filter_str, output_file]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if os.path.exists(raw_out): os.remove(raw_out)
    if callback: callback(100, "Hoàn tất xuất file Audio!")
    return output_file

def download_video(video_id, folder):
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    if any(f.startswith("source_video") for f in os.listdir(folder) if f.endswith(('.mp4','.webm','.mkv'))): return
    bat_file_path = os.path.abspath(os.path.join(CURRENT_DIR, "taiok.bat"))
    if not os.path.exists(bat_file_path): bat_file_path = os.path.abspath(os.path.join(CURRENT_DIR, "..", "taiok.bat"))
    
    list_txt = os.path.join(os.path.dirname(bat_file_path), "list.txt")
    with open(list_txt, "w", encoding="utf-8") as f: f.write(f"https://www.youtube.com/watch?v={video_id}\n")
    
    subprocess.run([bat_file_path], cwd=os.path.dirname(bat_file_path), shell=True, input=b'\r\n')
    dl_dir = os.path.join(os.path.dirname(bat_file_path), "downloads")
    dl_file = next((os.path.join(dl_dir, f) for f in os.listdir(dl_dir) if f"[{video_id}]" in f), None)
    if dl_file: shutil.move(dl_file, os.path.join(folder, f"source_video.{dl_file.split('.')[-1]}"))
    else: raise Exception("taiok.bat không tải được video!")

def separate_audio_demucs(video_path, output_folder, engine_mode="Demucs", callback=None):
    v = os.path.join(output_folder, "vocals.wav"); nv = os.path.join(output_folder, "no_vocals.wav")
    if os.path.exists(v) and os.path.exists(nv): return v, nv

    temp = os.path.join(output_folder, "temp_full.wav")
    subprocess.run([FFMPEG_LOCAL_PATH, "-y", "-i", video_path, "-vn", "-c:a", "pcm_s16le", temp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if engine_mode == "Demucs":
        # Dung cung Python dang chay GUI (venv), khong goi Python he thong.
        # Khi dong goi thanh EXE, tim Python trong venv nam canh file EXE.
        if getattr(sys, "frozen", False):
            python_executable = os.path.join(os.path.dirname(sys.executable), "venv", "Scripts", "python.exe")
        else:
            python_executable = sys.executable

        if not os.path.isfile(python_executable):
            raise FileNotFoundError(
                f"Khong tim thay Python cua moi truong venv: {python_executable}. "
                "Hay chay lai BAT de tao venv."
            )

        demucs_device = "cuda" if torch.cuda.is_available() else "cpu"
        cmd = [python_executable, "-m", "demucs", "-n", "htdemucs",
               "--two-stems=vocals", "-d", demucs_device, "-o", output_folder, temp]
        log_info(f"Demucs Python: {python_executable} | Device: {demucs_device}")
        subprocess.run(cmd, check=True)
        demucs_v = os.path.join(output_folder, "htdemucs", "temp_full", "vocals.wav"); demucs_nv = os.path.join(output_folder, "htdemucs", "temp_full", "no_vocals.wav")
        if os.path.exists(demucs_v): shutil.move(demucs_v, v)
        if os.path.exists(demucs_nv): shutil.move(demucs_nv, nv)
    else:
        from audio_separator.separator import Separator; import logging
        separator = Separator(output_dir=output_folder, output_format="WAV", log_level=logging.WARNING)
        separator.load_model(model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt")
        output_files = separator.separate(temp)
        for file_name in output_files:
            f_path = os.path.join(output_folder, file_name)
            if not os.path.exists(f_path): f_path = os.path.join(os.getcwd(), file_name)
            if not os.path.exists(f_path): f_path = file_name
            fname_lower = file_name.lower()
            if "vocal" in fname_lower and "no" not in fname_lower and "instrumental" not in fname_lower: shutil.move(f_path, v)
            else: shutil.move(f_path, nv)

    if not os.path.exists(v) or not os.path.exists(nv): raise Exception(f"Không thấy file xuất ra!")
    return v, nv


# ==============================================================================
# [🔥 NÂNG CẤP STUDIO 4] SMART FIT & ONSET ALIGNMENT
# ==============================================================================
def prepare_audio_segment(input_path, output_path, target_duration):
    """Trim silence and keep spoken audio inside the allotted time slot.

    Preserve natural pauses for short speech: never slow down beyond 0.92x.
    Longer utterances are accelerated as needed to avoid shifting the next one.
    """
    import numpy as np
    import soundfile as sf
    target_duration = max(.12, float(target_duration))
    samples, sr = sf.read(input_path, dtype='float32', always_2d=True)
    if len(samples) == 0:
        raise ValueError(f"Audio rong: {input_path}")
    energy = np.max(np.abs(samples), axis=1)
    active = np.flatnonzero(energy > 0.002)
    if len(active):
        first = max(0, int(active[0]) - int(sr*.035))
        last = min(len(samples), int(active[-1]) + int(sr*.07))
        samples = samples[first:last]
    duration = len(samples)/sr
    # Only use the *spoken* part when choosing speech speed. When the spoken
    # segment is shorter than the YouTube slot, keep the natural pause rather
    # than stretching speech to fill the slot (0.6x can sound robotic).
    # atempo < 1 slows speech. Bound slowdown to at most ~8%.
    requested_speed_factor = duration/target_duration
    speed_factor = max(0.92, requested_speed_factor)
    # FFmpeg atempo filter accepts factors 0.5..2.0 each, chain if needed.
    tempo = speed_factor
    stages = []
    while tempo > 2.0:
        stages.append('atempo=2.0')
        tempo /= 2.0
    while tempo < .5:
        stages.append('atempo=0.5')
        tempo /= .5
    stages.append(f'atempo={tempo:.8f}')
    trim_file = output_path + '.trim.wav'
    try:
        sf.write(trim_file, samples, sr, subtype='PCM_16')
        subprocess.run([
            FFMPEG_LOCAL_PATH, '-y', '-i', trim_file,
            '-filter:a', ','.join(stages), '-ar', '44100', '-ac', '2',
            '-c:a', 'pcm_s16le', '-vn', output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
           check=True)
        return output_path, speed_factor, duration
    finally:
        if os.path.exists(trim_file):
            os.remove(trim_file)


def smart_mix_video_moviepy(folder, bg_vol, vocal_vol, dub_vol, vid, burn_sub,
                             callback, engine_mode="Demucs"):
    import csv
    import numpy as np
    import soundfile as sf
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
    from moviepy.audio.AudioClip import AudioArrayClip

    vid_path = next((os.path.join(folder, f) for f in os.listdir(folder)
                     if f.startswith('source_video')), None)
    if vid_path is None:
        raise FileNotFoundError('Khong tim thay source_video')
    clip = VideoFileClip(vid_path)
    base_clips = []
    try:
        v, nv = separate_audio_demucs(vid_path, folder, engine_mode=engine_mode)
        base_clips.append(AudioFileClip(nv).volumex(bg_vol/100.0))
        base_clips.append(AudioFileClip(v).volumex(vocal_vol/100.0))
    except Exception:
        base_clips.append(clip.audio.volumex(bg_vol/100.0))

    fps = 44100
    total_frames = int(clip.duration * fps) + fps
    master_arr = np.zeros((total_frames, 2), dtype=np.float32)
    with open(os.path.join(folder, 'final_subtitles.json'), 'r', encoding='utf-8') as f:
        subs = json.load(f)
    report = []
    for i, item in enumerate(subs):
        idx = int(item['index']) + 1
        audio_file = os.path.join(folder, f'audio_{idx:05d}.wav')
        if not os.path.isfile(audio_file):
            raise FileNotFoundError(f'Thieu file audio index {item["index"]}')
        actual_start = float(item['start'])
        orig_duration = max(.1, float(item['end']) - actual_start)
        next_start = (float(subs[i+1]['start'])
                      if i+1 < len(subs) else clip.duration)
        max_fit_duration = max(.12, min(
            clip.duration - actual_start, next_start - actual_start - .07))
        if max_fit_duration <= .12:
            log_warn(f"Index {item['index']} khong du khoang trong audio")
            continue
        audio_issue = _check_tts_audio(audio_file)
        if audio_issue:
            raise ValueError(
                f"Index [{item['index']}] co file TTS hong/rong: {audio_file}: "
                f"{audio_issue}. Hay bam BUOC 2 de tu sinh lai cau nay.")
        original_tts_duration = sf.info(audio_file).duration
        # Tinh pham vi: muon ket thuc gan theo sub goc nhung duoc muon slack
        # toi truoc cau tiep theo. Khong de cau sau bi day muon.
        aim_duration = min(orig_duration, max_fit_duration)
        # Neu audio ngan, khong keo dai qua toc do doc 0.9x (giu tu nhien).
        if original_tts_duration < aim_duration:
            aim_duration = min(aim_duration, original_tts_duration/.90)
        # Neu audio dai, co the tan dung khoang trong im lang duoc phep.
        if original_tts_duration > aim_duration:
            aim_duration = min(max_fit_duration,
                               max(aim_duration, original_tts_duration/1.18))
        aim_duration = max(.12, min(aim_duration, max_fit_duration))

        ready_path = os.path.join(folder, f'ready_{idx:05d}.wav')
        ready_file, speed_factor, trimmed_duration = prepare_audio_segment(
            audio_file, ready_path, aim_duration)
        arr, sr = sf.read(ready_file, dtype='float32', always_2d=True)
        if sr != fps:
            raise ValueError(f'Sample rate khong dung: {sr}')
        if arr.shape[1] == 1:
            arr = np.repeat(arr, 2, axis=1)
        elif arr.shape[1] != 2:
            arr = arr[:, :2]

        # Quan trong: vi tri bat dau luon dung start cua YouTube.
        start_frame = max(0, int(round(actual_start * fps)))
        room_frames = max(0, int(max_fit_duration*fps))
        arr = arr[:min(room_frames, max(0, total_frames-start_frame))]
        if not len(arr):
            continue
        max_amp = float(np.max(np.abs(arr)))
        if max_amp > 0:
            arr = (arr/max_amp)*.95
        fade = min(int(.035*fps), len(arr)//2)
        if fade:
            arr[:fade] *= np.linspace(0,1,fade)[:,None]
            arr[-fade:] *= np.linspace(1,0,fade)[:,None]
        arr *= dub_vol/100.
        master_arr[start_frame:start_frame+len(arr)] += arr

        # Only long speech requires editorial intervention; short speech is
        # played at a natural rate followed by its original silence.
        warning = 'DICH_QUA_DAI' if speed_factor > 1.50 else ''
        if warning:
            log_warn(f"[{item['index']}] {warning}: can atempo {speed_factor:.2f}x,"
                     f" slot {max_fit_duration:.2f}s; hay rut gon ban dich")
        report.append({
            'index': item['index'], 'start': round(actual_start, 3),
            'end_youtube': round(float(item['end']), 3),
            'slot_youtube_s': round(orig_duration, 3),
            'next_start': round(next_start, 3),
            'tts_raw_s': round(original_tts_duration, 3),
            'tts_trimmed_s': round(trimmed_duration, 3),
            'speed_factor': round(speed_factor, 3),
            'tts_fitted_s': round(len(arr)/fps, 3),
            'warning': warning,
            'text': item['text']
        })
    if report:
        with open(os.path.join(folder, 'timing_report.csv'), 'w',
                  encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=report[0].keys())
            writer.writeheader()
            writer.writerows(report)

    master_arr = np.clip(master_arr, -.99, .99)
    master_dub_clip = AudioArrayClip(master_arr, fps=fps)
    base_clips.append(master_dub_clip)
    final_audio = CompositeAudioClip(base_clips).set_duration(clip.duration)
    final_video = clip.set_audio(final_audio)
    out = os.path.join(folder, f'{vid}_final_dubbed.mp4')
    params = ['-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq',
              '-pix_fmt', 'yuv420p']
    if burn_sub and os.path.exists(os.path.join(folder, f'{vid}.srt')):
        srt_path = os.path.join(folder, f'{vid}.srt').replace('\\', '/').replace(':', '\\:')
        params.extend(['-vf', f"subtitles='{srt_path}':force_style='Fontname=Arial,FontSize=18,PrimaryColour=&H00FFFF'"])
    final_video.write_videofile(
        out, codec='h264_nvenc', audio_codec='aac',
        temp_audiofile=os.path.join(folder, 'temp.m4a'), remove_temp=True,
        ffmpeg_params=params, bitrate='15000k', threads=4,
        logger=MyBarLogger(callback))
    return out

def apply_voice_mode(subtitles, folder, voices_dir, voice_mode="single"):
    """Use explicit voice mode, never infer it from speaker_roles.json presence.

    Single: all source lines use the GUI's selected profile_id. Existing role
    manifests are untouched and may be reused if the user later chooses multi.
    Multi: require a valid, approved role manifest, exactly as in V3.4.
    """
    if voice_mode not in ("single", "multi"):
        raise ValueError(f"Che do giong khong hop le: {voice_mode!r}")
    if voice_mode == "single":
        # Guard against any old injected profiles in final_subtitles.json.
        clean = []
        for row in subtitles:
            item = dict(row)
            item.pop('voice_profile', None)
            clean.append(item)
        return clean
    from speaker_roles import read_role_file, inject_approved_voice_profiles
    if read_role_file(folder) is None:
        raise ValueError('MULTI-SPEAKER da chon nhung chua co speaker_roles.json. '
                         'Hay mo AI PHAN VAI, kiem tra roi bam DUYET & LUU.')
    return inject_approved_voice_profiles(subtitles, folder, voices_dir)


def run_process(input_mode, video_input, sub_lang_code, bg_vol, vocal_vol, dub_vol, profile_id, burn_sub, callback, web_cookie="", run_step="full", engine_mode="Demucs", num_threads=3, tts_text="", speed=1.0, pitch=1.0, whisper_model="base", source_lang="auto", voice_mode="single"):
    cancel_event.clear()
    try:
        # ==========================================
        # CHẾ ĐỘ 1: TTS ĐỘC LẬP (Không cần đổi)
        # ==========================================
        if input_mode == "tts":
            if not tts_text.strip():
                raise Exception("Ông chưa nhập văn bản cần đọc kìa!")
                
            target_lang = sub_lang_code[:2] if len(sub_lang_code) > 2 else "vi"
            folder = os.path.join(BASE_DATA_FOLDER, "TTS_Studio_Output")
            os.makedirs(folder, exist_ok=True)
            
            out_file = os.path.join(folder, f"TTS_Audio_{int(time.time())}.wav")
            final_file = process_tts_standalone(tts_text, profile_id, target_lang, speed, pitch, dub_vol, out_file, callback)
            
            return {"status": "tts_success", "file": final_file}

        # ==========================================
        # CHẾ ĐỘ 2: VIDEO DUBBING
        # ==========================================
        if input_mode == "youtube":
            vid = extract_video_id(video_input)
            if not vid: raise Exception("Link URL không hợp lệ!")
        else: vid = os.path.splitext(os.path.basename(video_input))[0]
            
        folder = os.path.join(BASE_DATA_FOLDER, vid)
        final_sub_path = os.path.join(folder, "final_subtitles.json")
        to_translate_path = os.path.join(folder, "to_translate.txt")
        translated_path = os.path.join(folder, "translated.txt")
        os.makedirs(folder, exist_ok=True)

        # ---------------------------------------------------------
        # BƯỚC 1: EXTRACT (Bóc băng & Khóa Timeline)
        # ---------------------------------------------------------
        if run_step in ["extract", "full"]:
            if input_mode == "youtube":
                yt_extractor = YouTubeProExtractor()
                available_subs = yt_extractor.get_available_subs(vid)
                if sub_lang_code.lower().endswith("-orig"):
                    raw_subs = yt_extractor.get_subtitle_data(vid, folder, sub_lang_code)
                else:
                    src_lang = 'en'
                    if 'en-US' not in available_subs and 'en' not in available_subs: src_lang = next(iter(available_subs.keys()), 'en')
                    elif 'en' in available_subs: src_lang = 'en'
                    else: src_lang = 'en-US'
                    raw_subs = yt_extractor.get_subtitle_data(vid, folder, src_lang)
            else:
                target_lang = sub_lang_code.split('-')[0]
                raw_subs, detected_src_lang = transcribe_local_video_with_whisper(
                    video_input, folder, whisper_model=whisper_model, source_lang=source_lang, callback=callback
                )
                detected_src_lang = detected_src_lang.split('-')[0]
                raw_local_path = os.path.join(folder, f"raw_whisper_subtitles_{detected_src_lang}.json")
                with open(raw_local_path, "w", encoding="utf-8") as f:
                    json.dump(raw_subs, f, ensure_ascii=False, indent=4)

            # Backup ban dich cu: khi re-extract phai dich lai theo timeline moi.
            # Neu de translated.txt cu, code se gan van ban cu sang cac moc moi.
            if input_mode == 'youtube' and os.path.isfile(translated_path):
                backup = translated_path + '.old_timeline.bak'
                if os.path.exists(backup):
                    backup = translated_path + f'.{int(time.time())}.bak'
                shutil.move(translated_path, backup)
                log_warn(f'Da backup ban dich cu sang {backup}; can dich lai to_translate.txt')

            # Dọn rác text và lưu JSON gốc
            cleaned_subs = []
            for item in raw_subs:
                txt = re.sub(r'\[.*?\]|\(.*?\)', '', item['text'])
                txt = re.sub(r'^-\s*|^:\s*', '', txt.strip())
                txt = re.sub(r'\s+', ' ', txt).strip()
                if txt: 
                    item['text'] = txt
                    cleaned_subs.append(item)
            
            for i, item in enumerate(cleaned_subs): item['index'] = i

            with open(final_sub_path, "w", encoding="utf-8") as f: 
                json.dump(cleaned_subs, f, ensure_ascii=False, indent=4)

            # [🔥 TUYỆT KỸ] Tự động xuất Text cho LLM dịch
            with open(to_translate_path, "w", encoding="utf-8") as f:
                for sub in cleaned_subs:
                    f.write(f"[{sub['index']}] ({sub['end']-sub['start']:.2f}s) {sub['text']}\n")

            if run_step == "extract": 
                msg = f"Đã cào xong Timeline! Hãy mở file 'to_translate.txt' trong thư mục {vid}, dịch qua ChatGPT và lưu lại với tên 'translated.txt' rồi chạy bước Render."
                return {"status": "extracted", "file": final_sub_path, "msg": msg}


        # ---------------------------------------------------------
        # BƯỚC 2: RENDER (Ghép bản dịch, Sinh giọng & Trộn Video)
        # ---------------------------------------------------------
        if run_step in ["render", "full"]:
            if not os.path.exists(final_sub_path): 
                raise Exception("Không tìm thấy kịch bản JSON! Bác phải chạy Bước Extract trước.")
            
            # [🔥 TUYỆT KỸ] Tự động dò tìm file dịch LLM và Zíp vào Timeline
            if os.path.exists(translated_path):
                if callback: callback(5, "Phát hiện bản dịch LLM, đang đồng bộ vào Timeline...")
                with open(translated_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    
                translation_map = {}
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    match = re.match(r'\[(\d+)\]\s+(.*)', line)
                    if match:
                        idx = int(match.group(1))
                        if idx in translation_map:
                            raise ValueError(f'Index {idx} bi lap lai trong translated.txt')
                        translation_map[idx] = match.group(2)
                        
                with open(final_sub_path, 'r', encoding='utf-8') as f:
                    subs_to_render = json.load(f)
                    
                expected_indexes = {s['index'] for s in subs_to_render}
                missing = sorted(expected_indexes - set(translation_map))
                extra = sorted(set(translation_map) - expected_indexes)
                if missing or extra:
                    raise ValueError(
                        f"Ban dich khong khop index: thieu {missing[:12]}, thua {extra[:12]}. "
                        "Moi dong tieng Anh phai duoc dich dung 1 dong tieng Viet."
                    )
                for sub in subs_to_render:
                    sub['text'] = translation_map[sub['index']]
                        
                # Lưu đè lại bản tiếng Việt
                with open(final_sub_path, 'w', encoding='utf-8') as f:
                    json.dump(subs_to_render, f, ensure_ascii=False, indent=4)

            # Bắt đầu quy trình lồng tiếng
            with open(final_sub_path, 'r', encoding='utf-8') as f:
                translated = json.load(f)
            if (input_mode == 'youtube' and len(translated) >= 12 and
                sum(abs(float(s['end'])-float(s['start'])-.8) < .001
                    for s in translated)/len(translated) > .8):
                raise ValueError(
                    "TIMELINE CU BI LOI 0.8 GIAY. Hay chay lai BUOC 1 voi core da sua "
                    "roi dich lai dung tung index. Khong render tu JSON cu."
                )
            if any(not str(s.get('text', '')).strip() for s in translated):
                raise ValueError('Ban dich co dong rong!')
            if input_mode == 'youtube':
                empty_speech = [s['index'] for s in translated
                                if re.fullmatch(r'[.。…\s-]*', s['text'])]
                if empty_speech:
                    raise ValueError(
                        f'Ban dich dang bo trong loi thoai tai index {empty_speech[:15]}. '
                        'Khong dung "..." thay cho cau noi tieng Anh.')

            generate_srt_file(translated, os.path.join(folder, f"{vid}.srt"))

            # YouTube sub code (en, en-orig) describes SOURCE, not OUTPUT.
            omni_lang = 'vi' if input_mode == 'youtube' else sub_lang_code.split('-')[0]
            
            if callback: callback(10, "Kích hoạt mô hình OmniVoice...")
            # V3.4.5: Explicit mode controls whether speaker_roles.json is used.
            # Default SINGLE ignores any old roles file but never deletes it.
            # MULTI requires review approval and a valid role->voice mapping.
            translated = apply_voice_mode(
                translated, folder, os.path.join(CURRENT_DIR, 'voices'), voice_mode=voice_mode)
            log_info(f"[VOICE MODE] {'MULTI-SPEAKER (duyet vai)' if voice_mode == 'multi' else '1 GIONG (bo qua speaker_roles.json)'}")
            generate_local_dubbing(vid, translated, folder, omni_lang, profile_id, callback, num_threads=num_threads)
            
            if input_mode != "youtube":
                ext = video_input.split('.')[-1]
                if not os.path.exists(os.path.join(folder, f"source_video.{ext}")): 
                    shutil.copy(video_input, os.path.join(folder, f"source_video.{ext}"))
            else: 
                download_video(vid, folder)
                
            final_video_path = smart_mix_video_moviepy(
                folder, float(bg_vol), float(vocal_vol), float(dub_vol), 
                vid, burn_sub, callback, engine_mode=engine_mode
            )
            return {"status": "success", "file": final_video_path}
            
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"status": "error", "msg": str(e)}