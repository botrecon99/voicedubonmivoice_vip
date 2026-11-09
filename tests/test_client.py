# -*- coding: utf-8 -*-
"""Offline unit tests for client; no network or actual activation server."""
import hashlib, io, json, sys, tempfile, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client_patch'))
import license_client as cl

class FakeResp(io.BytesIO):
    def __init__(self, raw, headers=None):
        super().__init__(raw); self.headers=headers or {}
    def geturl(self): return 'https://example.test/file.zip'

class FakeOpener:
    def __init__(self, payload): self.payload=payload
    def open(self, req, timeout=None): return FakeResp(self.payload)

with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    cl.USER_DIR=tmp;cl.SAVED_PATH=tmp/'license.json';cl.CONFIG_PATH=tmp/'license_config.json'
    cl.CONFIG_PATH.write_text('{"api_url":"https://example.test"}',encoding='utf-8')
    key='ADS-'+'ABCDEF-'*3+'ABCDEF'
    cl.save_key(key)
    assert cl.saved_key()==key
    cl._OPENER=FakeOpener(json.dumps({'ok':True,'expires_at':'2027-01-01T00:00:00Z','latest_version':None}).encode())
    assert cl.validate_license()['ok']
    assert cl.require_active_license()['ok']
    cl._OPENER=FakeOpener(json.dumps({'ok':True,'update_required':True,'latest_version':{'version':'3.4.7'}}).encode())
    try:
        cl.require_active_license()
        assert False, 'Mandatory update was not enforced'
    except cl.LicenseError: pass

    zipbuf=io.BytesIO()
    with zipfile.ZipFile(zipbuf,'w') as z: z.writestr('test.txt','valid')
    payload=zipbuf.getvalue()
    cl._OPENER=FakeOpener(payload)
    release={'version':'3.4.7','download_url':'https://example.test/file.zip','sha256':hashlib.sha256(payload).hexdigest()}
    out=cl.download_update(release,download_dir=tmp)
    assert out.is_file()
    assert out.read_bytes()==payload
    release['sha256']='a'*64
    try:
        cl.download_update(release,download_dir=tmp)
        assert False, 'Bad SHA allowed'
    except cl.LicenseError:pass
    assert not (tmp/'AI_Dubbing_Studio_Update_v3.4.7.zip.part').exists()
print('✅ Client tests: saved key, verify, force update, ZIP SHA256, clean failed download.')
