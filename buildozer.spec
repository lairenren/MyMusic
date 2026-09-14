[app]
title = 本地音乐
package.name = mymusic
package.domain = com.example
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf
version = 1.0

# ⭐ 关键1：显式指定 Python 3.11（避开 3.14 兼容问题）
# 注意：p4a 会强制 python3 和 hostpython3 一致，所以这里用 p4a 分支锁版本
requirements = python3,kivy==2.3.0,pillow,mutagen

# ⭐ 关键2：同时打两种架构（兼容新老手机）
android.archs = arm64-v8a, armeabi-v7a

# ⭐ 关键3：API 与 NDK 版本对齐
android.api = 31
android.minapi = 21
android.ndk = 23b

android.permissions = READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, READ_MEDIA_AUDIO
orientation = portrait
fullscreen = 0
android.accept_sdk_license = True
android.allow_backup = True

# ⭐ 关键4：强制 p4a 使用 Python 3.11 的 p4a 分支
p4a.branch = v2023.09.16

[buildozer]
log_level = 2
warn_on_root = 1