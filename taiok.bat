@echo off
setlocal EnableExtensions EnableDelayedExpansion
title YouTube Downloader <=1080p - yt-dlp (Stable Pro, Fixed Retry)

if not exist "downloads" mkdir "downloads"

yt-dlp.exe -U

yt-dlp.exe ^
 --no-js-runtimes ^
 --js-runtimes node ^
 -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" ^
 --merge-output-format mp4 ^
 --user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36" ^
 --add-header "Referer:https://www.youtube.com" ^
 --extractor-args "youtube:player_client=all" ^
 --force-ipv4 ^
 --geo-bypass ^
 --cookies "cookies.txt" ^
 --ignore-errors ^
 --no-part ^
 --no-keep-video ^
 --concurrent-fragments 10 ^
 --downloader-args "http_chunk_size:10M" ^
 --retries 20 ^
 --fragment-retries 50 ^
 --retry-sleep 5 ^
 -a "list.txt" ^
 -o "downloads\%%(title).120s [%%(id)s].%%(ext)s"

echo.
echo =====================================================
echo  ✅ HOÀN TẤT
echo  Video đã lưu trong thư mục "downloads"
echo  Định dạng tên: Title [ID].ext  (vd: My Clip [dQw4w9WgXcQ].mp4)
echo =====================================================
pause
endlocal