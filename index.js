import { ADMIN_HTML } from './admin_html.js';
import { ADMIN_SCRIPT } from './admin_script.js';

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const KEY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const KEY_RE = /^ADS(?:-[A-HJ-NP-Z2-9]{6}){4}$/;
const LIMIT_BODY = 16 * 1024;

function json(data, status=200) { return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS }); }
function msg(error, status=400) { return json({ ok:false, error }, status); }
function norm(v) { return String(v || '').trim().toUpperCase(); }
function validToken(request, env) {
  const expected = String(env.ADMIN_TOKEN || '');
  const supplied = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (expected.length < 32 || expected.length !== supplied.length) return false;
  let diff=0;
  for(let i=0;i<expected.length;i++) diff |= expected.charCodeAt(i) ^ supplied.charCodeAt(i);
  return diff===0;
}
function noStore(response) { response.headers.set('Cache-Control','no-store'); return response; }
// Cloudflare secrets can arrive with or without the `base64:` label.
// Normalize the label but ALWAYS require 32 random bytes (AES-256/HKDF).
// Never log or send the secret itself.
function decodeMasterSecret(env) {
  const secret = String(env.KEY_ENCRYPTION_KEY ?? '').trim();
  const encoded = (secret.startsWith('base64:') ? secret.slice(7) : secret).trim();
  if (!/^[A-Za-z0-9+/]{43}=$/.test(encoded))
    throw new Error('CONFIG_KEY_FORMAT: KEY_ENCRYPTION_KEY must be Base64 of 32 bytes, optionally prefixed with base64:');
  let raw;
  try { raw = b64ToBytes(encoded); }
  catch { throw new Error('CONFIG_KEY_BASE64: invalid KEY_ENCRYPTION_KEY Base64'); }
  if (raw.length !== 32) throw new Error('CONFIG_KEY_LENGTH: expected 32 bytes');
  return raw;
}
function checkEnv(env) {
  if (!env.DB) throw new Error('CONFIG_DB_MISSING: D1 binding DB not present');
  if (typeof env.ADMIN_TOKEN !== 'string' || env.ADMIN_TOKEN.length < 32)
    throw new Error('CONFIG_ADMIN_TOKEN: ADMIN_TOKEN is missing or shorter than 32 characters');
  decodeMasterSecret(env);
}
async function readBody(req) {
  if (Number(req.headers.get('content-length') || 0)>LIMIT_BODY) throw new Error('Dữ liệu quá lớn');
  const raw=await req.text();
  if (raw.length>LIMIT_BODY) throw new Error('Dữ liệu quá lớn');
  try { const body = JSON.parse(raw); if (!body || typeof body!=='object' || Array.isArray(body)) throw new Error(); return body; }
  catch { throw new Error('JSON không hợp lệ'); }
}
function parseDate(input) {
  if (typeof input !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/.test(input)) throw new Error('Ngày hết hạn phải là ISO UTC, ví dụ 2027-01-15T00:00:00Z');
  const ts=Date.parse(input);
  if (!Number.isFinite(ts)) throw new Error('Ngày hết hạn không hợp lệ');
  return new Date(ts).toISOString();
}
function expiryFromDays(days) {
  const d=Number(days);
  if (!Number.isInteger(d) || d < 1 || d > 36500) throw new Error('Số ngày phải từ 1 tới 36500');
  return new Date(Date.now()+d*86400000).toISOString();
}
function base32(bytes) {
  let bits=0, buff=0, text='';
  for(const byte of bytes) { buff=(buff<<8)|byte; bits+=8; while(bits>=5) { bits-=5; text+=KEY_ALPHABET[(buff>>>bits)&31]; buff &= (1<<bits)-1; } }
  return text;
}
function makeLicense() {
  const data = crypto.getRandomValues(new Uint8Array(15));
  const t = base32(data); // 120 random bits -> 24 characters
  return `ADS-${t.slice(0,6)}-${t.slice(6,12)}-${t.slice(12,18)}-${t.slice(18,24)}`;
}
function bytesToB64(arr){ return btoa(String.fromCharCode(...arr)); }
function b64ToBytes(s){ return Uint8Array.from(atob(s), c=>c.charCodeAt(0)); }
async function keys(env) {
  const raw=decodeMasterSecret(env);
  const master=await crypto.subtle.importKey('raw',raw,'HKDF',false,['deriveKey']);
  const common={name:'HKDF',hash:'SHA-256',salt:new TextEncoder().encode('omni-license-v1')};
  const aes=await crypto.subtle.deriveKey({...common,info:new TextEncoder().encode('db encryption')},master,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  const hmac=await crypto.subtle.deriveKey({...common,info:new TextEncoder().encode('key lookup')},master,{name:'HMAC',hash:'SHA-256',length:256},false,['sign']);
  return {aes,hmac};
}
async function hashKey(raw, k) {
  const sig=new Uint8Array(await crypto.subtle.sign('HMAC',k.hmac,new TextEncoder().encode(norm(raw))));
  return Array.from(sig,b=>b.toString(16).padStart(2,'0')).join('');
}
async function encryptKey(raw,k) {
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const encrypted=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv},k.aes,new TextEncoder().encode(raw)));
  return bytesToB64(iv)+'.'+bytesToB64(encrypted);
}
async function decryptKey(cipher,k) {
  const [iv,data]=String(cipher).split('.');
  const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64ToBytes(iv)},k.aes,b64ToBytes(data));
  return new TextDecoder().decode(bytes);
}
function appVersion(v) { return /^\d+\.\d+\.\d+$/.test(String(v||'')); }
function compareVersion(a,b) {
  const x=String(a).split('.').map(Number), y=String(b).split('.').map(Number);
  for(let i=0;i<3;i++){ if(x[i]<y[i]) return -1; if(x[i]>y[i]) return 1; }
  return 0;
}
function publicVersion(v) { if(!v) return null; return { version:v.version, download_url:v.download_url, sha256:v.sha256, notes:v.notes, mandatory:!!v.mandatory, published_at:v.published_at }; }
async function currentVersion(env) { return env.DB.prepare('SELECT * FROM versions WHERE is_current=1 LIMIT 1').first(); }
async function validate(req, env) {
  const body=await readBody(req); const raw=norm(body.key);
  if (!KEY_RE.test(raw)) return msg('Mã key không hợp lệ',401);
  const k=await keys(env); const h=await hashKey(raw,k);
  const lic=await env.DB.prepare('SELECT id, customer, expires_at, enabled, checks FROM licenses WHERE key_hash=?').bind(h).first();
  if (!lic) return msg('Không tìm thấy license',401);
  if (!lic.enabled) return msg('License đã bị khóa',403);
  if (Date.parse(lic.expires_at)<=Date.now()) return msg('License đã hết hạn',403);
  // Usage counters are best-effort; a counter outage should not revoke a valid license.
  try { await env.DB.prepare('UPDATE licenses SET checks=checks+1, last_seen_at=? WHERE id=?').bind(new Date().toISOString(),lic.id).run(); } catch { /* ignore counter failure */ }
  const latest=publicVersion(await currentVersion(env));
  const client=String(body.client_version || '');
  const update_available=!!(latest && appVersion(client) && compareVersion(client,latest.version)<0);
  const update_required=!!(latest && latest.mandatory && update_available);
  return json({ok:true, customer:lic.customer, expires_at:lic.expires_at, server_time:new Date().toISOString(),latest_version:latest, update_available,update_required});
}
async function createKey(req,env,k) {
  const b=await readBody(req); const customer=String(b.customer||'').trim().slice(0,120);
  const notes=String(b.notes||'').trim().slice(0,1000);
  const expires_at=b.expires_at ? parseDate(b.expires_at) : expiryFromDays(b.days??30);
  let key,hash,cipher;
  for(let i=0;i<4;i++) {
    key=makeLicense(); hash=await hashKey(key,k); cipher=await encryptKey(key,k);
    const existing=await env.DB.prepare('SELECT id FROM licenses WHERE key_hash=?').bind(hash).first();
    if(!existing) break; if(i===3) return msg('Không cấp được mã ngẫu nhiên',500);
  }
  const id=crypto.randomUUID(),now=new Date().toISOString();
  await env.DB.prepare('INSERT INTO licenses (id,key_hash,key_cipher,customer,notes,expires_at,enabled,created_at,updated_at,checks) VALUES (?,?,?,?,?,?,1,?,?,0)').bind(id,hash,cipher,customer,notes,expires_at,now,now).run();
  return json({ok:true, license:{id,key,customer,notes,expires_at,enabled:true,created_at:now,last_seen_at:null,checks:0}},201);
}
async function listKeys(env,k) {
  const {results}=await env.DB.prepare('SELECT id,key_cipher,customer,notes,expires_at,enabled,created_at,updated_at,last_seen_at,checks FROM licenses ORDER BY created_at DESC LIMIT 1000').all();
  const out=await Promise.all(results.map(async r => ({ ...r, key:await decryptKey(r.key_cipher,k), enabled:!!r.enabled, key_cipher:undefined })));
  return json({ok:true,licenses:out});
}
async function manipulateKey(req,env,k,id,action) {
  const current=await env.DB.prepare('SELECT * FROM licenses WHERE id=?').bind(id).first();
  if(!current) return msg('Không tìm thấy license',404);
  const now=new Date().toISOString();
  if(req.method==='DELETE' && !action) {
    await env.DB.prepare('DELETE FROM licenses WHERE id=?').bind(id).run();return json({ok:true});
  }
  if(req.method==='PATCH' && !action) {
    const b=await readBody(req);
    const customer=b.customer===undefined?current.customer:String(b.customer).trim().slice(0,120);
    const notes=b.notes===undefined?current.notes:String(b.notes).trim().slice(0,1000);
    const enabled=b.enabled===undefined?current.enabled:(b.enabled?1:0);
    const expires=b.expires_at===undefined?current.expires_at:parseDate(b.expires_at);
    await env.DB.prepare('UPDATE licenses SET customer=?, notes=?, enabled=?, expires_at=?, updated_at=? WHERE id=?').bind(customer,notes,enabled,expires,now,id).run();
    return json({ok:true});
  }
  if(req.method==='POST' && action==='renew') {
    const b=await readBody(req); const days=Number(b.days??30);
    if (!Number.isInteger(days)||days<1||days>36500) return msg('Số ngày không hợp lệ');
    const anchor=Math.max(Date.now(),Date.parse(current.expires_at));
    const newDate=new Date(anchor+days*86400000).toISOString();
    await env.DB.prepare('UPDATE licenses SET expires_at=?,updated_at=? WHERE id=?').bind(newDate,now,id).run();
    return json({ok:true,expires_at:newDate});
  }
  if(req.method==='POST' && action==='rotate') {
    const key=makeLicense(),hash=await hashKey(key,k),cipher=await encryptKey(key,k);
    await env.DB.prepare('UPDATE licenses SET key_hash=?,key_cipher=?,updated_at=? WHERE id=?').bind(hash,cipher,now,id).run();
    return json({ok:true,key});
  }
  return msg('Phương thức không được hỗ trợ',405);
}
function versionInput(b) {
  const version=String(b.version||'').trim();
  if(!appVersion(version)) throw new Error('Phiên bản phải theo dạng x.y.z');
  const url=String(b.download_url||'').trim();
  if(!url || url.length>1200 || !/^https:\/\//i.test(url)) throw new Error('Link tải phải dùng HTTPS');
  const hash=String(b.sha256||'').trim().toLowerCase();
  if(!/^[a-f0-9]{64}$/.test(hash)) throw new Error('SHA256 phải đủ 64 ký tự HEX');
  return {version, download_url:url, sha256:hash, notes:String(b.notes||'').slice(0,3000), mandatory: b.mandatory?1:0};
}
async function listVersions(env) { const {results}=await env.DB.prepare('SELECT * FROM versions ORDER BY published_at DESC LIMIT 200').all(); return json({ok:true, versions:results.map(v=>({...v,mandatory:!!v.mandatory,is_current:!!v.is_current}))}); }
async function publishVersion(req,env){
  const b=versionInput(await readBody(req)); const now=new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare('UPDATE versions SET is_current=0 WHERE is_current=1'),
    env.DB.prepare('INSERT INTO versions (version,download_url,sha256,notes,mandatory,is_current,published_at) VALUES (?,?,?,?,?,1,?)').bind(b.version,b.download_url,b.sha256,b.notes,b.mandatory,now)
  ]);return json({ok:true},201);
}
async function versionAction(req,env,version) {
  const found=await env.DB.prepare('SELECT * FROM versions WHERE version=?').bind(version).first();
  if(!found) return msg('Không tìm thấy phiên bản',404);
  if(req.method==='DELETE') { if(found.is_current) return msg('Không thể xóa phiên bản đang phát hành',409);await env.DB.prepare('DELETE FROM versions WHERE version=?').bind(version).run();return json({ok:true}); }
  if(req.method==='PATCH') {
    const b=versionInput({...(found||{}),...await readBody(req)});
    if(b.version!==version) return msg('Không được đổi số phiên bản; tạo bản mới',400);
    await env.DB.prepare('UPDATE versions SET download_url=?,sha256=?,notes=?,mandatory=? WHERE version=?').bind(b.download_url,b.sha256,b.notes,b.mandatory,version).run();return json({ok:true});
  }
  if(req.method==='POST') {
    await env.DB.batch([env.DB.prepare('UPDATE versions SET is_current=0 WHERE is_current=1'),env.DB.prepare('UPDATE versions SET is_current=1 WHERE version=?').bind(version)]);
    return json({ok:true});
  }
  return msg('Không hỗ trợ',405);
}
function securityHeaders(resp,html=false) {
  const r = new Response(resp.body,resp);
  r.headers.set('X-Content-Type-Options','nosniff');
  r.headers.set('Referrer-Policy','no-referrer');
  r.headers.set('X-Frame-Options','DENY');
  if(html) r.headers.set('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  return r;
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url), path=url.pathname.replace(/\/+$/,'')||'/';
    try {
      if(path==='/' && request.method==='GET') return securityHeaders(new Response(ADMIN_HTML,{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}}),true);
      if(path==='/admin.js' && request.method==='GET') return securityHeaders(new Response(ADMIN_SCRIPT,{headers:{'Content-Type':'text/javascript; charset=utf-8','Cache-Control':'no-store'}}));
      checkEnv(env);
      if(path==='/api/health' && request.method==='GET') return json({ok:true,service:'AI Dubbing License API'});
      if(path==='/api/version' && request.method==='GET') return json({ok:true,latest_version:publicVersion(await currentVersion(env))});
      if(path==='/api/validate' && request.method==='POST') return await validate(request,env);
      if(!path.startsWith('/api/admin/')) return msg('Không tìm thấy đường dẫn',404);
      if(!validToken(request,env)) return msg('Admin token không đúng',401);
      const k=await keys(env);
      if(path==='/api/admin/keys') {if(request.method==='GET') return listKeys(env,k); if(request.method==='POST') return createKey(request,env,k);}
      let m=path.match(/^\/api\/admin\/keys\/([a-f0-9-]{36})(?:\/(renew|rotate))?$/i);
      if(m) return manipulateKey(request,env,k,m[1],m[2]);
      if(path==='/api/admin/versions') {if(request.method==='GET') return listVersions(env); if(request.method==='POST') return publishVersion(request,env);}
      m=path.match(/^\/api\/admin\/versions\/(\d+\.\d+\.\d+)$/);
      if(m) return versionAction(request,env,m[1]);
      return msg('Không tìm thấy đường dẫn',404);
    } catch (e) {
      // Log a safe diagnostic for wrangler tail, but never log any secret/key value.
      const detail=String(e?.message || 'unknown');
      console.error('[AI_DUBBING_WORKER]', detail.startsWith('CONFIG_') ? detail : (e?.name || 'Error') + ': ' + detail.slice(0,300));
      // Public API keeps the generic 500 response to avoid leaking configuration.
      const isUserError=/JSON|Ngày|Số ngày|Phiên bản|Link tải|SHA256|Dữ liệu/.test(String(e.message));
      return msg(isUserError?e.message:'Lỗi máy chủ. Kiểm tra cấu hình/migration trong logs.',isUserError?400:500);
    }
  }
};
