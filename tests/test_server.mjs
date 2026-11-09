import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import cryptoNode from 'node:crypto';
import worker from '../cloudflare-worker/src/index.js';
const db=new DatabaseSync(':memory:');
db.exec(readFileSync(new URL('../cloudflare-worker/migrations/0001_init.sql',import.meta.url),'utf8'));
class DB {
 prepare(query) { const stmt=db.prepare(query); return {bind(...args){return {run:async()=>stmt.run(...args),first:async()=>stmt.get(...args)||null,all:async()=>({results:stmt.all(...args)})}},run:async()=>stmt.run(),first:async()=>stmt.get()||null,all:async()=>({results:stmt.all()})};}
 async batch(prepared) {db.exec('BEGIN');try{const result=[];for(const p of prepared)result.push(await p.run());db.exec('COMMIT');return result;}catch(e){db.exec('ROLLBACK');throw e}}
}
const secret = cryptoNode.randomBytes(32).toString('base64');
const env={DB:new DB(),ADMIN_TOKEN:'ADMIN_EXAMPLE_32CHARACTER_SECRET_TOKEN_1234',KEY_ENCRYPTION_KEY:'base64:'+secret};
const root='https://license.example.workers.dev';
const h={Authorization:'Bearer '+env.ADMIN_TOKEN,'Content-Type':'application/json'};
async function call(path,method='GET',body,admin=false){const req=new Request(root+path,{method,headers:admin?h:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const res=await worker.fetch(req,env);const text=await res.text();let value;try{value=JSON.parse(text)}catch{value=text}return {status:res.status,value,headers:res.headers};}
const sha='a'.repeat(64);
const a=await call('/api/admin/keys','POST',{customer:'Khách thử',days:30,notes:'Gói 1'},true);
assert.equal(a.status,201,JSON.stringify(a.value));
const key=a.value.license.key;
assert.match(key,/^ADS(?:-[A-HJ-NP-Z2-9]{6}){4}$/);
let r=await call('/api/validate','POST',{key,client_version:'3.4.6'});
assert.equal(r.status,200,JSON.stringify(r.value));
assert.equal(r.value.customer,'Khách thử');
assert.equal(r.value.update_available,false);
r=await call('/api/admin/keys','GET',undefined,true);assert.equal(r.value.licenses.length,1);assert.equal(r.value.licenses[0].key,key);
r=await call('/api/admin/keys','GET');assert.equal(r.status,401);
r=await call('/api/admin/keys/'+a.value.license.id,'PATCH',{enabled:false},true);assert.equal(r.status,200);
r=await call('/api/validate','POST',{key});assert.equal(r.status,403);
r=await call('/api/admin/keys/'+a.value.license.id,'PATCH',{enabled:true,expires_at:'2020-01-01T00:00:00Z'},true);assert.equal(r.status,200);
r=await call('/api/validate','POST',{key});assert.equal(r.status,403);
r=await call('/api/admin/keys/'+a.value.license.id+'/renew','POST',{days:30},true);assert.equal(r.status,200);
r=await call('/api/validate','POST',{key});assert.equal(r.status,200);
r=await call('/api/admin/keys/'+a.value.license.id+'/rotate','POST',{},true);assert.equal(r.status,200);
const newkey=r.value.key;
assert.notEqual(newkey,key);
r=await call('/api/validate','POST',{key});assert.equal(r.status,401);
r=await call('/api/validate','POST',{key:newkey});assert.equal(r.status,200);
r=await call('/api/admin/versions','POST',{version:'3.4.7',download_url:'https://github.com/owner/repo/releases/download/v3.4.7/app.zip',sha256:sha,notes:'New features',mandatory:true},true);
assert.equal(r.status,201,JSON.stringify(r.value));
r=await call('/api/version');assert.equal(r.value.latest_version.version,'3.4.7');
r=await call('/api/validate','POST',{key:newkey,client_version:'3.4.6'});assert.equal(r.value.update_required,true);
r=await call('/api/validate','POST',{key:newkey,client_version:'3.4.7'});assert.equal(r.value.update_required,false);
r=await call('/api/admin/versions','POST',{version:'3.4.8',download_url:'https://github.com/owner/repo/releases/download/v3.4.8/app.zip',sha256:sha,mandatory:false},true);assert.equal(r.status,201);
r=await call('/api/validate','POST',{key:newkey,client_version:'3.4.7'});assert.equal(r.value.update_available,true);assert.equal(r.value.update_required,false);
r=await call('/api/admin/versions/3.4.7','POST',{},true);assert.equal(r.status,200);
r=await call('/api/admin/versions/3.4.7','DELETE',undefined,true);assert.equal(r.status,409);
r=await call('/api/admin/versions/3.4.8','DELETE',undefined,true);assert.equal(r.status,200);
r=await call('/api/admin/keys/'+a.value.license.id,'DELETE',undefined,true);assert.equal(r.status,200);
r=await call('/api/validate','POST',{key:newkey});assert.equal(r.status,401);
const html=await worker.fetch(new Request(root+'/'),env);assert.equal(html.status,200);assert.ok((await html.text()).includes('AI Dubbing License Center'));
console.log('✅ Tests passed: create/verify/hide/copy-admin-list/lock/expire/renew/rotate/delete/version/publish/mandatory/rollback/admin-auth/html');
