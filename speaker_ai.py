# -*- coding: utf-8 -*-
"""Runs in a SEPARATE venv to avoid changing OmniVoice's torch environment.

CLI example:
 .venv_roles\\Scripts\\python.exe speaker_ai.py --input source_video.mp4 \
    --subtitles downloaded_data/ID/final_subtitles.json \
    --output downloaded_data/ID/speaker_roles.json --ffmpeg ffmpeg.exe

The audio is processed locally. Hugging Face token: HF_TOKEN environment variable.
Optional audEERING age/gender inference is NON-COMMERCIAL ONLY by its CC-BY-NC-SA-4.0 license.
"""
import argparse
import json
import os
import subprocess
import sys
import traceback
from importlib import metadata
import tempfile
import wave
from collections import defaultdict
from pathlib import Path


def log(msg):
    print(msg, flush=True)


def log_system_diagnostics():
    """Version summary helps diagnose TorchCodec/FFmpeg ABI errors."""
    log('[ENV] Python: ' + sys.version.split()[0])
    log('[ENV] Python executable: ' + sys.executable)
    for package in ('pyannote.audio', 'torch', 'torchaudio', 'torchcodec',
                    'transformers', 'huggingface-hub', 'numpy'):
        try:
            version = metadata.version(package)
        except metadata.PackageNotFoundError:
            version = 'NOT INSTALLED'
        log('[ENV] ' + package + ': ' + version)
    log('[ENV] HF_TOKEN provided: ' + ('yes (hidden)' if os.getenv('HF_TOKEN') else 'no'))


def extract_wav(source_video, wav_path, ffmpeg):
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
           '-i', source_video, '-vn', '-ar', '16000', '-ac', '1',
           '-c:a', 'pcm_s16le', wav_path]
    subprocess.run(cmd, check=True)


def read_pcm16_audio(wav_path):
    import numpy as np
    with wave.open(wav_path, 'rb') as f:
        sr = f.getframerate()
        if f.getsampwidth() != 2 or f.getnchannels() != 1:
            raise RuntimeError('Audio phải là WAV PCM16 mono')
        data = np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype('float32') / 32768
    return data, sr


def get_turns(annotation):
    turns = []
    if hasattr(annotation, 'itertracks'):
        iterable = ((seg, label) for seg, _, label in annotation.itertracks(yield_label=True))
    else:
        iterable = ((row[0], row[-1]) for row in annotation)
    for seg, label in iterable:
        if float(seg.end) <= float(seg.start):
            continue
        turns.append({'start': round(float(seg.start), 4),
                      'end': round(float(seg.end), 4),
                      'speaker': str(label)})
    return sorted(turns, key=lambda t: (t['start'], t['end']))


def run_pyannote(wav_path, token, cpu=False):
    import torch
    from pyannote.audio import Pipeline
    model = 'pyannote/speaker-diarization-community-1'
    log('Đang khởi tạo Pyannote Community-1...')
    try:
        if token:
            pipeline = Pipeline.from_pretrained(model, token=token)
        else:
            # HF cache / huggingface-cli login may already grant permission.
            pipeline = Pipeline.from_pretrained(model)
    except Exception as exc:
        raise RuntimeError('Không tải được Pyannote Community-1. Hãy chấp nhận điều kiện model tại Hugging Face, '
                           'đăng nhập bằng token Read và kiểm tra cài đặt .venv_roles. ' + str(exc)) from exc
    if pipeline is None:
        raise RuntimeError('Pyannote không khởi tạo được. Kiểm tra quyền truy cập Hugging Face.')
    if torch.cuda.is_available() and not cpu:
        pipeline.to(torch.device('cuda'))
        log('Phân tích người nói bằng GPU CUDA...')
    else:
        log('Phân tích người nói bằng CPU...')
    # pyannote.audio 4.x invokes torchcodec.AudioDecoder when passed a WAV path.
    # On Windows this can fail with "Could not load libtorchcodec" (missing FFmpeg
    # shared DLLs or torch/torchcodec ABI mismatch).  Feeding an already-decoded
    # waveform is an officially supported path and avoids TorchCodec decoding.
    # extract_wav() guarantees a 16-kHz, mono, PCM16 source.
    log('Đang đọc WAV PCM16 trực tiếp bằng Python, KHÔNG dùng TorchCodec...')
    signal, sample_rate = read_pcm16_audio(wav_path)
    if not len(signal):
        raise RuntimeError('File WAV trống: không có audio để phân vai.')
    waveform = torch.from_numpy(signal).unsqueeze(0).contiguous()  # (channels=1, samples)
    log(f'WAV: {sample_rate} Hz, {len(signal) / sample_rate:.1f} giây, '
        f'{len(signal):,} mẫu. Đã nạp vào RAM.')
    log('Đang chạy Pyannote từ waveform trong RAM (bỏ qua libtorchcodec)...')
    result = pipeline({'waveform': waveform, 'sample_rate': int(sample_rate)})
    annotation = getattr(result, 'exclusive_speaker_diarization', None)
    if annotation is None:
        annotation = getattr(result, 'speaker_diarization', result)
    return get_turns(annotation)



def classify_gender(wav_path, turns):
    """Audio-only male/female suggestion (Apache-2.0 model); no age claim."""
    import numpy as np
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    model_id = 'alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech'
    log('Đang tải model phân loại giọng nam/nữ (Apache-2.0)...')
    processor = AutoFeatureExtractor.from_pretrained(model_id)
    model = AutoModelForAudioClassification.from_pretrained(model_id)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device).eval()
    signal, sr = read_pcm16_audio(wav_path)
    spans = defaultdict(list)
    for t in turns:
        if float(t['end']) - float(t['start']) >= 1.4:
            spans[t['speaker']].append(t)
    profiles = {}
    # Explicit index mapping specified in model card.
    for speaker, candidates in spans.items():
        selected = sorted(candidates, key=lambda t: t['end']-t['start'], reverse=True)[:3]
        predictions = []
        for turn in selected:
            start = max(0, int(turn['start'] * sr))
            stop = min(len(signal), int(turn['end'] * sr), start + int(5*sr))
            clip = signal[start:stop]
            if len(clip) < int(sr*1.3):
                continue
            inputs = processor(clip, sampling_rate=sr, return_tensors='pt', padding=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.inference_mode():
                logits = model(**inputs).logits
            probs = torch.softmax(logits, -1).squeeze(0).cpu().numpy()
            predictions.append(probs)
        if not predictions:
            continue
        mean = np.mean(np.array(predictions), axis=0)
        # Model card label2id: female=0, male=1.
        ix = int(np.argmax(mean))
        conf = float(mean[ix])
        pred_type = ('female' if ix == 0 else 'male') if conf >= .65 else 'unknown'
        profiles[speaker] = {'type': pred_type, 'confidence': round(conf, 3), 'age_estimate': None}
        log(f'  {speaker}: dự đoán {pred_type} / mức tin cậy={conf:.2f}')
    return profiles


def classify_age_gender(wav_path, turns):
    """Optional audEERING classifier; only activated by explicit non-commercial checkbox."""
    import numpy as np
    import torch
    import torch.nn as nn
    from transformers import Wav2Vec2Processor
    from transformers.models.wav2vec2.modeling_wav2vec2 import Wav2Vec2Model, Wav2Vec2PreTrainedModel

    class ModelHead(nn.Module):
        def __init__(self, config, num_labels):
            super().__init__()
            self.dense = nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = nn.Dropout(config.final_dropout)
            self.out_proj = nn.Linear(config.hidden_size, num_labels)
        def forward(self, x):
            x = self.dropout(x)
            x = self.dense(x)
            x = torch.tanh(x)
            x = self.dropout(x)
            return self.out_proj(x)

    class AgeGenderModel(Wav2Vec2PreTrainedModel):
        def __init__(self, config):
            super().__init__(config)
            self.wav2vec2 = Wav2Vec2Model(config)
            self.age = ModelHead(config, 1)
            self.gender = ModelHead(config, 3)
            self.post_init()
        def forward(self, input_values):
            hidden = self.wav2vec2(input_values).last_hidden_state.mean(dim=1)
            return self.age(hidden), torch.softmax(self.gender(hidden), dim=1)

    model_id = 'audeering/wav2vec2-large-robust-6-ft-age-gender'
    log('Đang tải audEERING Age/Gender (chỉ dùng phi thương mại)...')
    processor = Wav2Vec2Processor.from_pretrained(model_id)
    model = AgeGenderModel.from_pretrained(model_id)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device)
    model.eval()
    signal, sr = read_pcm16_audio(wav_path)

    spans = defaultdict(list)
    for t in turns:
        if float(t['end']) - float(t['start']) >= 1.4:
            spans[t['speaker']].append(t)
    profiles = {}
    for speaker, all_turns in spans.items():
        # Several clean, reasonably long excerpts reduce errors from a single phrase.
        selected = sorted(all_turns, key=lambda x: x['end']-x['start'], reverse=True)[:3]
        ages, probs = [], []
        for item in selected:
            start = max(0, int(float(item['start']) * sr))
            end = min(len(signal), int(float(item['end']) * sr), start + int(9 * sr))
            clip = signal[start:end]
            if len(clip) < 1.3 * sr:
                continue
            x = processor(clip, sampling_rate=sr, return_tensors='pt')['input_values'].to(device)
            with torch.inference_mode():
                age, g = model(x)
            age_years = float(age.squeeze().item()) * 100.0
            pred_probs = g[0].detach().cpu().numpy()
            ages.append(age_years)
            probs.append(pred_probs)
        if not probs:
            continue
        mean_age = float(np.median(ages))
        pr = np.mean(probs, axis=0)
        # Model predicts [child, female, male]. Age is an approximate acoustic estimate.
        pred = int(np.argmax(pr))
        confidence = float(pr[pred])
        if confidence < .60:
            voice_type = 'unknown'
        elif pred == 0 or mean_age <= 12:
            voice_type = 'child'  # Cannot infer boy vs girl reliably.
        elif pred == 1:
            voice_type = 'older_female' if mean_age >= 60 else 'female'
        else:
            voice_type = 'older_male' if mean_age >= 60 else 'male'
        profiles[speaker] = {'type': voice_type,
                             'confidence': round(confidence, 3),
                             'age_estimate': round(mean_age, 1)}
        log(f'  {speaker}: loại giọng gợi ý={voice_type}, tuổi ước lượng≈{mean_age:.0f}, xác suất={confidence:.2f}')
    return profiles


def analyze(args):
    token = os.environ.get('HF_TOKEN', '').strip()
    input_video = os.path.abspath(args.input)
    sub_path = os.path.abspath(args.subtitles)
    if not os.path.isfile(input_video) or not os.path.isfile(sub_path):
        raise FileNotFoundError('Không tìm thấy video hoặc final_subtitles.json.')
    if not os.path.isfile(args.ffmpeg) and not args.ffmpeg == 'ffmpeg':
        raise FileNotFoundError('Không tìm thấy FFmpeg, hãy kiểm tra ffmpeg.exe.')
    with open(sub_path, 'r', encoding='utf-8') as f:
        subs = json.load(f)
    folder = os.path.dirname(os.path.abspath(args.output))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from speaker_roles import build_analysis_project, atomic_write_json

    with tempfile.TemporaryDirectory(prefix='omnivoice_speaker_ai_') as tmp:
        wav = os.path.join(tmp, 'voice_source.wav')
        log('Đang tách audio gốc 16kHz...')
        extract_wav(input_video, wav, args.ffmpeg)
        turns = run_pyannote(wav, token, cpu=args.cpu)
        log(f'Đã phát hiện {len(turns)} đoạn nói, {len(set(t["speaker"] for t in turns))} người nói.')
        if not turns:
            raise RuntimeError('AI không phát hiện người nói. Có thể video không có thoại hoặc audio quá khó.')
        profiles = {}
        if args.age_gender:
            try:
                profiles = classify_age_gender(wav, turns)
            except Exception as exc:
                log('CẢNH BÁO: Model tuổi/giới tính thất bại: ' + str(exc))
                log('Tiếp tục phân vai người nói, không tự đoán kiểu giọng.')
        elif args.gender:
            try:
                profiles = classify_gender(wav, turns)
            except Exception as exc:
                log('CẢNH BÁO: Model nam/nữ thất bại: ' + str(exc))
                log('Tiếp tục phân vai người nói, bạn sẽ chọn kiểu giọng thủ công.')
        project = build_analysis_project(subs, turns, profiles)
        # Only store turn metadata, not a new, unsafely identified voice identity.
        project['analysis_note'] += ' Phải kiểm tra kỹ người kể chuyện và các giọng trùng nhau.'
        atomic_write_json(args.output, project)
        log('Đã lưu bản NHÁP (chưa duyệt): ' + args.output)


def main():
    parser = argparse.ArgumentParser(description='Pyannote speaker diarization for OmniVoice')
    parser.add_argument('--input', required=True)
    parser.add_argument('--subtitles', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--age-gender', action='store_true', help='Uses non-commercial CC-BY-NC-SA model')
    parser.add_argument('--gender', action='store_true', help='Uses Apache-2.0 male/female audio model')
    parser.add_argument('--cpu', action='store_true')
    args = parser.parse_args()
    log_system_diagnostics()
    try:
        analyze(args)
    except Exception as exc:
        log('LỖI: ' + str(exc))
        log('========== FULL PYTHON TRACEBACK BEGIN ==========')
        traceback.print_exc(file=sys.stdout)
        log('========== FULL PYTHON TRACEBACK END ============')
        sys.exit(1)


if __name__ == '__main__':
    main()
