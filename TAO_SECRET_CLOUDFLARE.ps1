# Chay: powershell -NoProfile -ExecutionPolicy Bypass -File .\TAO_SECRET_CLOUDFLARE.ps1
# Generated secrets never written to disk by this script.
function RandomBytes($n) {
  $bytes = New-Object byte[] $n
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return ,$bytes
}
$adminBytes = RandomBytes 32
$keyBytes = RandomBytes 32
$admin = ([BitConverter]::ToString($adminBytes)).Replace('-', '').ToLowerInvariant()
$key = 'base64:' + [Convert]::ToBase64String($keyBytes)
Write-Host ''
Write-Host '======== ADMIN_TOKEN (dan vao wrangler secret put ADMIN_TOKEN) ========' -ForegroundColor Yellow
Write-Host $admin
Write-Host ''
Write-Host '======== KEY_ENCRYPTION_KEY (dan vao wrangler secret put KEY_ENCRYPTION_KEY) ========' -ForegroundColor Yellow
Write-Host $key
Write-Host ''
Write-Host 'LUU Y: Giu bi mat 2 gia tri. Mat KEY_ENCRYPTION_KEY thi khong doc duoc key cu.' -ForegroundColor Red
