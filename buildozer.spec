[app]
title = 本地音乐
package.name = mymusic
package.domain = com.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,mp3,wav,ogg,flac,m4a

version = 1.0

requirements = kivy==2.3.1,pillow,mutagen

# 允许读取外部存储
android.permissions = READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, READ_MEDIA_AUDIO

orientation = portrait
fullscreen = 0

# 支持主流手机架构
android.archs = arm64-v8a

android.api = 33
android.minapi = 21
android.ndk = 25b

# 打包时把字体也带进去（如果有的话）
# source.include_patterns = font.ttf

[buildozer]
log_level = 2
warn_on_root = 1