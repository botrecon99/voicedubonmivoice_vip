# AI Dubbing Studio V3.4.6 — License Key + Quản lý phiên bản

Bản này kế thừa **AI Dubbing Studio V3.4.5**, đặc biệt giữ nguyên công tắc **1 GIỌNG / MULTI-SPEAKER**, fix **audio WAV rỗng V3.4.4**, Pyannote, giọng Vbee, cache SYNC.

## 1. Chức năng

**Client Windows:** cửa sổ nhập license khi khởi động, tự ghi nhớ key của người dùng, kiểm tra online khi khởi động và ngay trước mỗi BƯỚC 1/BƯỚC 2/TTS, xem ngày hết hạn, check bản mới, tải ZIP cập nhật và xác minh SHA256. App chỉ tải ZIP, **không tự ghi đè/cài đặt**, tránh làm hỏng một phiên render hoặc code người dùng.

**Admin Cloudflare:** web quản lý key (tạo 30/90/365 ngày, xem/ẩn/copy, sửa người dùng/thời hạn/ghi chú, khóa/mở, gia hạn 30 ngày, đổi key, xóa); phát hành bản mới, quản lý lịch sử bản, bật chế độ bắt buộc cập nhật.

**Không HWID:** một key có thể chạy trên nhiều máy, không theo dõi ID thiết bị. Khi hết hạn, khóa hoặc thu hồi, các lượt xác thực tiếp theo sẽ thất bại. Không giới hạn số máy; đây là đúng yêu cầu thiết kế cũ.

**Bảo mật:** key mã hóa AES-256-GCM trước khi lưu D1; dùng HMAC-SHA256 tra cứu; ADMIN_TOKEN và KEY_ENCRYPTION_KEY chỉ ở Cloudflare Secrets, không bao giờ chép vào ZIP giao cho khách.

## 2. Tạo Cloudflare Worker + D1 (chỉ admin làm 1 lần)

Yêu cầu: Cloudflare account, Node.js/npx, Internet, Windows PowerShell.

1. Mở `cloudflare-worker`. Chạy `CAI_SERVER_CLOUDFLARE.bat` hoặc gõ các lệnh thủ công:

   ```bat
   npx wrangler login
   npx wrangler d1 create ai-dubbing-license-db
   ```

2. **Copy ID database** vừa được Cloudflare cấp vào file `cloudflare-worker/wrangler.toml`: thay `THAY_BANG_D1_DATABASE_ID`.

3. Khởi tạo bảng và deploy:

   ```bat
   npx wrangler d1 migrations apply ai-dubbing-license-db --remote
   npx wrangler deploy
   ```

4. Chạy `TAO_SECRET_CLOUDFLARE.ps1` ở thư mục cha (mở PowerShell tại đúng thư mục rồi chạy):

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\TAO_SECRET_CLOUDFLARE.ps1
   ```

   Công cụ in ra **ADMIN_TOKEN** và **KEY_ENCRYPTION_KEY** ngẫu nhiên. Lưu 2 secret trong nơi an toàn. Đặc biệt: mất hoặc thay **KEY_ENCRYPTION_KEY** thì key trong D1 không còn đọc/tra cứu được (phải khôi phục secret cũ).

5. Tại thư mục `cloudflare-worker` lần lượt chạy:

   ```bat
   npx wrangler secret put ADMIN_TOKEN
   npx wrangler secret put KEY_ENCRYPTION_KEY
   ```

   Paste giá trị tương ứng vào mỗi lệnh khi được hỏi.

6. Vào địa chỉ `https://<TEN_WORKER>.<SUBDOMAIN>.workers.dev/` (địa chỉ chính xác hiển thị sau `wrangler deploy`). Dán **ADMIN_TOKEN** vào giao diện để đăng nhập. **Không đăng địa chỉ này cùng token ở chỗ công khai.** Đường dẫn admin không bí mật, bảo mật dựa vào token dài.

**Lưu ý:** Nếu D1 của lần trước đã tồn tại, không chạy `d1 create` lần nữa; copy database ID đúng hiện có từ `npx wrangler d1 list`. Đây là gói server mới, không mặc định tương thích schema Worker D1 cũ — muốn dùng chung database phải migrate đúng schema trước.

## 3. Cài lên máy làm video (không làm mất data)

1. Tắt Studio, sao lưu `D:\OmniVoice_multi_speaker\modern_gui.py` thành `modern_gui.py.bak`.
2. Chép **3 file** từ `client_patch` vào `D:\OmniVoice_multi_speaker\`:

   - `modern_gui.py` (tích hợp license)
   - `license_client.py` (mạng và kiểm tra)
   - `license_ui.py` (giao diện)

3. Chép thêm `license_config.json` vào cùng thư mục và sửa thành URL Worker **thực tế**:

   ```json
   { "api_url": "https://<TEN_WORKER>.<SUBDOMAIN>.workers.dev" }
   ```

4. Tạo key trong admin web và nhập key đó vào cửa sổ kích hoạt. Khởi chạy **`modern_gui.py`** bằng cách chạy app như trước.
5. Key được ghi nhớ trong `%LOCALAPPDATA%\AI_Dubbing_Studio\license.json`. Mỗi máy có thể dùng cùng một key. Nếu xóa file đó, cửa sổ sẽ yêu cầu nhập lại.

**Không chép đè `core.py`**. Giữ nguyên `voices/`, `downloaded_data/`, `translated.txt`, `speaker_roles.json`, `venv/`, `.venv_roles/`, mọi file mô hình, cache và Pyannote.

### Nếu có file BAT khởi chạy app cũ

Tiếp tục chạy BAT cũ nếu nó gọi `python modern_gui.py` hoặc `pythonw modern_gui.py`.
Nếu BAT gọi file khác (ví dụ `main.py`), cần đảm bảo entry point thực tế chạy `modern_gui.py` đã tích hợp license. Đừng gửi cho khách bản code cũ chưa gắn cổng license.

## 4. Cấp key

- Mở trang Worker `/`, dán ADMIN_TOKEN.
- Điền tên khách + số ngày → **TẠO KEY**. Key ví dụ `ADS-XXXXXX-XXXXXX-XXXXXX-XXXXXX`.
- **Xem**, **Copy**, **Sửa** tên/notes/hạn, **+30 ngày**, **Khóa/Mở**, **Đổi mã** hoặc **Xóa**.
- Gia hạn +30 ngày được cộng từ ngày hết hạn hiện tại nếu key còn hạn, hoặc từ hiện tại nếu đã hết hạn.
- Đổi mã = key cũ vô hiệu ngay lập tức; gửi key mới cho khách.

## 5. Quản lý phiên bản

1. Đóng gói một ZIP cập nhật và đưa lên **GitHub Releases** hoặc nơi HTTPS công khai có URL tải trực tiếp. Không upload secret hay `.env` / `.dev.vars` / `wrangler.toml` chứa ID nhạy cảm vào ZIP giao khách. Repo có thể public, API không chứa ADMIN_TOKEN.
2. Lấy mã SHA256:

   ```powershell
   (Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\duong_dan\file_cap_nhat.zip').Hash.ToLowerInvariant()
   ```

   Hoặc kéo ZIP thả vào `CHECK_SHA256_ZIP.bat`.
3. Trong trang admin, nhập version (VD `3.4.7`), link ZIP HTTPS, SHA256, ghi chú; bật `Bắt buộc cập nhật` nếu muốn chặn bản cũ. Nhấn **PHÁT HÀNH**.
4. Khi khách mở app, client nhận được thông báo có bản mới. Nếu bắt buộc, sẽ phải cài bản mới trước khi dùng tiếp. Click tải ZIP chỉ **tải và kiểm tra SHA256**. Người dùng giải nén/cài thủ công sau khi tắt app.
5. Nếu lên bản mới, nhớ đổi hằng `APP_VERSION` trong `license_client.py` cho khớp số bản công bố. **Không đặt `mandatory=true` trước khi khách có thể tải/cài bản mới hợp lệ.**

## 6. Giới hạn rõ ràng

- Đây là **license online**: mất mạng hoặc Cloudflare lỗi => không mở app/không bắt đầu lượt mới. Nếu đã bắt đầu render thì không đột ngột cắt tác vụ đang chạy.
- Giao diện Python dễ bị người có kiến thức sửa code để bỏ kiểm tra. Không có cơ chế thuần Python nào chống can thiệp tuyệt đối. Muốn thương mại hóa mạnh hơn, cân nhắc đóng gói/biên dịch và đặt dịch vụ quan trọng ở server (tùy quy mô).
- D1 lưu số lần kiểm tra và thời điểm kiểm tra, không thu thập HWID. Cloudflare vẫn có thể lưu log mạng tiêu chuẩn nếu bạn bật log.
- Chưa thử chạy thực tế trên Windows hoặc deploy lên tài khoản Cloudflare của bạn. Có test server tích hợp và kiểm tra cú pháp Python.

## 7. Chạy kiểm thử (trên máy có Node 22+)

```bat
node tests\test_server.mjs
```

Bài test dùng SQLite trong bộ nhớ; kiểm tra cấp/khóa/mở/gia hạn/đổi/xóa key, phiên bản bắt buộc, admin auth, UI HTML. Không thay dữ liệu D1 thật.
