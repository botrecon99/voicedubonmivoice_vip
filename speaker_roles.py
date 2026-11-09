# -*- coding: utf-8 -*-
"""Speaker-role manifest for OmniVoice SYNC V3.

No AI dependencies. Keeps the source index/timeline unchanged and requires
explicit approval before multi-voice rendering.
"""
import hashlib
import json
import os
from collections import Counter, defaultdict

ROLES_FILENAME = 'speaker_roles.json'
ROLES_VERSION = 1
ALLOWED_TYPES = ('unknown', 'male', 'female', 'boy', 'girl', 'child', 'older_male', 'older_female', 'older')


def timeline_signature(subtitles):
    timeline = [{'index': int(s['index']),
                 'start': round(float(s['start']), 3),
                 'end': round(float(s['end']), 3)}
                for s in subtitles]
    body = json.dumps(timeline, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def role_file(folder):
    return os.path.join(folder, ROLES_FILENAME)


def read_role_file(folder):
    p = role_file(folder)
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def atomic_write_json(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.writing'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def project_from_subtitles(subtitles, default_profile=''):
    """Manual starter: one speaker, every line assigned for review."""
    return {
        'version': ROLES_VERSION,
        'timeline_signature': timeline_signature(subtitles),
        'approved': False,
        'method': 'manual',
        'analysis_note': 'Chưa chạy Pyannote. Tự phân vai bằng tay hoặc bấm Quét AI.',
        'speakers': [{
            'id': 'SPEAKER_00',
            'suggested_type': 'unknown',
            'type': 'unknown',
            'confidence': None,
            'age_estimate': None,
            'voice_profile': default_profile or '',
            'preview_start': float(subtitles[0]['start']) if subtitles else 0.0,
            'preview_end': float(subtitles[0]['end']) if subtitles else 3.0,
        }],
        'segments': [
            {'index': int(s['index']), 'speaker_id': 'SPEAKER_00', 'voice_override': ''}
            for s in subtitles
        ],
    }


def match_subtitles_to_turns(subtitles, turns, min_overlap_ratio=0.18):
    """Pick speaker by maximum overlap with an exclusive diarization track.

    Low overlap gets None rather than forcing an incorrect identity.
    Returns list of dicts index, speaker_id, voice_override.
    """
    results = []
    ordered = sorted(turns, key=lambda x: float(x['start']))
    for sub in subtitles:
        a, b = float(sub['start']), float(sub['end'])
        duration = max(0.01, b - a)
        weights = defaultdict(float)
        for t in ordered:
            ta, tb = float(t['start']), float(t['end'])
            if ta >= b:
                break
            if tb <= a:
                continue
            overlap = max(0.0, min(b, tb) - max(a, ta))
            if overlap > 0:
                weights[str(t['speaker'])] += overlap
        if weights:
            spk, ov = max(weights.items(), key=lambda p: p[1])
            # short subtitle at boundary can still get valid allocation
            selected = spk if ov / duration >= min_overlap_ratio else None
        else:
            selected = None
        results.append({'index': int(sub['index']), 'speaker_id': selected, 'voice_override': ''})
    return results


def validate_project(project, subtitles, voices_dir, require_approved=True):
    """Raise ValueError on any unsafe/missing mapping. Return index->voice name."""
    if project.get('timeline_signature') != timeline_signature(subtitles):
        raise ValueError('Timeline đã thay đổi từ lúc phân vai. Hãy phân vai lại trước khi render.')
    if require_approved and not project.get('approved'):
        raise ValueError('AI PHÂN VAI chưa được DUYỆT. Mở bảng phân vai, kiểm tra từng câu và bấm DUYỆT & LƯU.')
    speakers = project.get('speakers', [])
    speaker_map = {str(s['id']): s for s in speakers}
    if len(speaker_map) != len(speakers):
        raise ValueError('Có mã người nói bị trùng trong speaker_roles.json.')
    segments = project.get('segments', [])
    by_idx = {}
    for entry in segments:
        idx = int(entry['index'])
        if idx in by_idx:
            raise ValueError(f'Phân vai có index {idx} trùng nhau.')
        by_idx[idx] = entry
    expected = {int(s['index']) for s in subtitles}
    if set(by_idx) != expected:
        raise ValueError('Phân vai sai số câu hoặc thiếu index. Hãy mở bảng duyệt lại.')
    mapping = {}
    for idx in expected:
        entry = by_idx[idx]
        speaker_id = entry.get('speaker_id')
        if not speaker_id or speaker_id not in speaker_map:
            raise ValueError(f'Index [{idx}] chưa được gán người nói. Hãy chọn thủ công.')
        voice = (entry.get('voice_override') or speaker_map[speaker_id].get('voice_profile') or '').strip()
        if not voice or voice == '(chưa có giọng)':
            raise ValueError(f'Index [{idx}] chưa có giọng tiếng Việt.')
        if os.path.basename(voice) != voice or '\\' in voice or '/' in voice:
            raise ValueError(f'Tên giọng không hợp lệ ở [{idx}].')
        if not any(os.path.isfile(os.path.join(voices_dir, voice + ext)) for ext in ('.wav', '.mp3', '.m4a')):
            raise ValueError(f'Index [{idx}] đang chọn giọng {voice!r} nhưng không có file trong voices/.')
        mapping[idx] = voice
    return mapping


def build_analysis_project(subtitles, turns, profiles=None):
    """Build an unapproved AI draft. Role types are 'unknown' until classified."""
    allocation = match_subtitles_to_turns(subtitles, turns)
    counter = Counter(t['speaker'] for t in turns)
    all_speakers = sorted(counter, key=lambda s: (int(str(s).split('_')[-1]) if str(s).split('_')[-1].isdigit() else 999, str(s)))
    if not all_speakers:
        raise ValueError('Pyannote không phát hiện được lời nói trong audio.')
    previews = {}
    for s in all_speakers:
        spans = [t for t in turns if t['speaker'] == s]
        best = max(spans, key=lambda t: float(t['end']) - float(t['start']))
        previews[s] = (float(best['start']), float(best['end']))
    speakers = []
    for s in all_speakers:
        a, b = previews[s]
        info = (profiles or {}).get(s, {})
        speakers.append({
            'id': s,
            'suggested_type': info.get('type', 'unknown'),
            'type': info.get('type', 'unknown'),
            'confidence': info.get('confidence'),
            'age_estimate': info.get('age_estimate'),
            'voice_profile': '',
            'preview_start': a,
            'preview_end': b,
        })
    return {
        'version': ROLES_VERSION,
        'timeline_signature': timeline_signature(subtitles),
        'approved': False,
        'method': 'pyannote-community-1',
        'analysis_note': 'AI chỉ đề xuất; cần nghe và duyệt lại. Giới tính/tuổi chỉ là suy đoán từ giọng nói.',
        'speakers': speakers,
        'segments': allocation,
    }


def inject_approved_voice_profiles(subtitles, folder, voices_dir):
    """Return shallow copies of subtitle rows with their voice profile, if enabled."""
    project = read_role_file(folder)
    if project is None:
        return subtitles
    mapping = validate_project(project, subtitles, voices_dir=voices_dir, require_approved=True)
    return [dict(s, voice_profile=mapping[int(s['index'])]) for s in subtitles]
