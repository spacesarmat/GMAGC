#!/usr/bin/env bash
# Дымовая проверка APK в эмуляторе: установка, запуск, живой процесс, снимок экрана и лог.
set -u
PKG=com.spacesarmat.gmagc
APK=$(ls apk/GMAGC-android-*.apk | head -1)
mkdir -p smoke
adb install -r "$APK" | tee smoke/install.txt
adb shell pm grant "$PKG" android.permission.CAMERA || true
adb logcat -c
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1
sleep 30
PID=$(adb shell pidof "$PKG" | tr -d '\r')
adb logcat -d > smoke/logcat.txt
adb exec-out screencap -p > smoke/screen.png
echo "pid: '$PID'" | tee smoke/result.txt
if [ -z "$PID" ]; then echo "приложение не запущено или упало" | tee -a smoke/result.txt; grep -n "FATAL\|Traceback\|python" smoke/logcat.txt | head -40 | tee -a smoke/result.txt; exit 1; fi
if grep -q "FATAL EXCEPTION" smoke/logcat.txt; then echo "FATAL EXCEPTION в логе" | tee -a smoke/result.txt; exit 1; fi
echo "ok" | tee -a smoke/result.txt
