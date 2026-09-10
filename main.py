# main.py
# -*- coding: utf-8 -*-
import os
import re
import time
import sys

from kivy.app import App
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import (
    StringProperty, NumericProperty, BooleanProperty
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView

# ---------- 中文字体 ----------
FONT_NAME = 'Roboto'   # 默认
for candidate in ('NotoSansSC-Regular.ttf', 'font.ttf',
                  'NotoSansCJK-Regular.ttc', 'wqy-microhei.ttc'):
    if os.path.exists(candidate):
        try:
            LabelBase.register(name='Chinese', fn_regular=candidate)
            FONT_NAME = 'Chinese'
            print(f"[字体] 已加载: {candidate}")
            break
        except Exception as e:
            print(f"[字体] 加载 {candidate} 失败: {e}")

# ---------- mutagen（ID3 标签） ----------
try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC
    from mutagen.easyid3 import EasyID3
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("[警告] 未安装 mutagen，无法读取封面/元数据")

# ---------- Android 权限 ----------
try:
    from android.permissions import request_permissions, Permission
    HAS_ANDROID = True
except ImportError:
    HAS_ANDROID = False

# ---------- 配色 ----------
COLOR_RED = (0.831, 0.235, 0.200, 1)
COLOR_GRAY = (0.557, 0.557, 0.576, 1)
COLOR_TEXT = (0.110, 0.110, 0.118, 1)


# ============================================================
#  歌词解析器
# ============================================================
class LyricsParser:
    LRC_TIME_RE = re.compile(r'\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]')

    def __init__(self):
        self.lines = []

    def load_from_file(self, lrc_path):
        self.lines = []
        if not os.path.exists(lrc_path):
            return False
        content = None
        for enc in ('utf-8', 'utf-8-sig', 'gbk', 'gb18030', 'big5'):
            try:
                with open(lrc_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            return False
        self._parse(content)
        return True

    def load_from_string(self, content):
        self.lines = []
        self._parse(content)
        return len(self.lines) > 0

    def _parse(self, content):
        for raw_line in content.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            times, last_end = [], 0
            for m in self.LRC_TIME_RE.finditer(raw_line):
                mm, ss = int(m.group(1)), int(m.group(2))
                ms_str = m.group(3) or '0'
                if len(ms_str) == 3:
                    ms = int(ms_str) / 1000.0
                elif len(ms_str) == 2:
                    ms = int(ms_str) / 100.0
                else:
                    ms = int(ms_str) / 10.0
                times.append(mm * 60 + ss + ms)
                last_end = m.end()
            text = raw_line[last_end:].strip()
            if not text:
                continue
            for t in times:
                self.lines.append((t, text))
        self.lines.sort(key=lambda x: x[0])

    def is_empty(self):
        return len(self.lines) == 0


# ============================================================
#  元数据读取
# ============================================================
def read_metadata(path):
    title = os.path.splitext(os.path.basename(path))[0]
    artist = "未知歌手"
    album = ""
    duration = 0
    cover_data = None
    embedded_lyrics = ""

    if HAS_MUTAGEN:
        try:
            audio = MP3(path, ID3=ID3)
            duration = int(audio.info.length)
            if audio.tags:
                if 'TIT2' in audio.tags:
                    title = str(audio.tags['TIT2'])
                if 'TPE1' in audio.tags:
                    artist = str(audio.tags['TPE1'])
                if 'TALB' in audio.tags:
                    album = str(audio.tags['TALB'])
                for tag in audio.tags.values():
                    if isinstance(tag, APIC):
                        cover_data = tag.data
                        break
                if 'USLT' in audio.tags:
                    embedded_lyrics = str(audio.tags['USLT'])
        except Exception:
            try:
                audio = EasyID3(path)
                title = audio.get('title', [title])[0]
                artist = audio.get('artist', [artist])[0]
                album = audio.get('album', [album])[0]
            except Exception:
                pass

    lrc_path = os.path.splitext(path)[0] + '.lrc'
    lyrics = None
    if os.path.exists(lrc_path):
        lyrics = LyricsParser()
        if not lyrics.load_from_file(lrc_path):
            lyrics = None
    if lyrics is None and embedded_lyrics:
        lyrics = LyricsParser()
        lyrics.load_from_string(embedded_lyrics)

    return {
        'path': path,
        'title': title,
        'artist': artist,
        'album': album,
        'duration': duration,
        'cover': cover_data,
        'lyrics': lyrics,
    }


# ============================================================
#  播放引擎
# ============================================================
class MusicPlayer:
    def __init__(self):
        self.playlist = []
        self.current_index = -1
        self.sound = None
        self.is_playing = False
        self.is_paused = False
        self._start_offset = 0.0
        self._play_start_wall = 0.0
        self._pause_position = 0.0
        self.volume = 0.7

    def add_files(self, paths):
        added = []
        for p in paths:
            if not p.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a')):
                continue
            info = read_metadata(p)
            self.playlist.append(info)
            added.append(info)
        return added

    def play(self, index, start_sec=0.0):
        if index < 0 or index >= len(self.playlist):
            return False
        try:
            self.current_index = index
            if self.sound:
                try:
                    self.sound.stop()
                except Exception:
                    pass
            self.sound = SoundLoader.load(self.playlist[index]['path'])
            if self.sound is None:
                print(f"[播放失败] SoundLoader 无法加载: {self.playlist[index]['path']}")
                return False
            self.sound.volume = self.volume

            if start_sec > 0:
                try:
                    self.sound.seek(start_sec)
                except Exception:
                    pass

            self.sound.play()
            self._start_offset = start_sec
            self._play_start_wall = time.time()
            self.is_playing = True
            self.is_paused = False
            return True
        except Exception as e:
            print(f"[播放异常] {e}")
            return False

    def pause(self):
        if self.sound and self.is_playing and not self.is_paused:
            self._pause_position = self.get_position()
            try:
                self.sound.stop()
            except Exception:
                pass
            self.is_paused = True
            return True
        return False

    def resume(self):
        if self.sound and self.is_paused:
            return self.play(self.current_index, self._pause_position)
        return False

    def stop(self):
        if self.sound:
            try:
                self.sound.stop()
            except Exception:
                pass
        self.is_playing = False
        self.is_paused = False
        self._start_offset = 0.0
        self._pause_position = 0.0

    def next(self):
        if not self.playlist:
            return False
        return self.play((self.current_index + 1) % len(self.playlist))

    def prev(self):
        if not self.playlist:
            return False
        if self.get_position() > 3:
            return self.play(self.current_index)
        return self.play((self.current_index - 1) % len(self.playlist))

    def set_volume(self, v):
        self.volume = max(0.0, min(1.0, v))
        if self.sound:
            self.sound.volume = self.volume

    def get_position(self):
        if self.current_index < 0:
            return 0.0
        if self.is_paused:
            return self._pause_position
        if not self.is_playing:
            return self._start_offset
        elapsed = time.time() - self._play_start_wall
        pos = self._start_offset + elapsed
        dur = self.playlist[self.current_index]['duration']
        if dur > 0:
            pos = min(pos, dur)
        return max(0.0, pos)

    def is_busy(self):
        return self.sound is not None and self.sound.state == 'play'

    def seek(self, seconds):
        if self.current_index < 0:
            return
        dur = self.playlist[self.current_index]['duration']
        if dur > 0:
            seconds = max(0, min(seconds, dur - 0.5))
        self.play(self.current_index, seconds)

    def fast_forward(self, delta=10):
        self.seek(self.get_position() + delta)

    def rewind(self, delta=10):
        self.seek(self.get_position() - delta)


# ============================================================
#  KV 界面
# ============================================================
KV = '''
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<CardItem>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(64)
    padding: dp(12), dp(8)
    spacing: dp(12)
    canvas.before:
        Color:
            rgba: (1, 0.941, 0.941, 1) if root.is_current else (1, 1, 1, 1)
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: 0.941, 0.941, 0.949, 1
        Rectangle:
            pos: self.x, self.y
            size: self.width, dp(1)

    Label:
        text: ('▶' if root.is_current else str(root.song_index + 1))
        font_name: app.font_name
        font_size: sp(14)
        color: (0.831, 0.235, 0.200, 1) if root.is_current else (0.557, 0.557, 0.576, 1)
        size_hint_x: None
        width: dp(28)
        bold: root.is_current

    BoxLayout:
        orientation: 'vertical'
        size_hint_x: 1
        Label:
            text: root.song_title
            font_name: app.font_name
            color: (0.831, 0.235, 0.200, 1) if root.is_current else (0.110, 0.110, 0.118, 1)
            font_size: sp(15)
            bold: root.is_current
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'
        Label:
            text: root.song_artist
            font_name: app.font_name
            color: (0.557, 0.557, 0.576, 1)
            font_size: sp(12)
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'

    Label:
        text: root.song_duration
        font_name: app.font_name
        color: (0.557, 0.557, 0.576, 1)
        font_size: sp(12)
        size_hint_x: None
        width: dp(48)
        halign: 'right'
        text_size: self.size

<CardItem>:
    song_title: ''
    song_artist: ''
    song_duration: ''

<RoundImage>:
    canvas.before:
        Color:
            rgba: (0.831, 0.235, 0.200, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    Image:
        source: root.source
        allow_stretch: True
        keep_ratio: False
        pos_hint: {'center_x': 0.5, 'center_y': 0.5}
        size_hint: None, None
        size: root.size

<MainLayout>:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        Rectangle:
            pos: self.pos
            size: self.size

    # 顶部标题栏
    BoxLayout:
        size_hint_y: None
        height: dp(60)
        padding: dp(16), dp(10)
        spacing: dp(8)

        Label:
            text: '♪'
            font_name: app.font_name
            color: (0.831, 0.235, 0.200, 1)
            font_size: sp(24)
            size_hint_x: None
            width: dp(32)
            bold: True

        BoxLayout:
            orientation: 'vertical'
            Label:
                text: '本地音乐'
                font_name: app.font_name
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(20)
                bold: True
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            Label:
                text: '离线 · 私人曲库'
                font_name: app.font_name
                color: (0.557, 0.557, 0.576, 1)
                font_size: sp(11)
                halign: 'left'
                valign: 'middle'
                text_size: self.size

        Button:
            text: '＋ 导入'
            font_name: app.font_name
            size_hint_x: None
            width: dp(78)
            background_color: (0.831, 0.235, 0.200, 1)
            background_normal: ''
            color: (1, 1, 1, 1)
            font_size: sp(13)
            bold: True
            on_release: root.open_file_chooser()

    # 标签切换
    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(16), 0
        spacing: dp(20)

        Button:
            text: '本地音乐'
            font_name: app.font_name
            size_hint_x: None
            width: dp(70)
            background_normal: ''
            background_color: (1, 1, 1, 1)
            color: (0.831, 0.235, 0.200, 1) if root.current_tab == 0 else (0.557, 0.557, 0.576, 1)
            font_size: sp(15)
            bold: root.current_tab == 0
            on_release: root.switch_tab(0)
            canvas.after:
                Color:
                    rgba: (0.831, 0.235, 0.200, 1) if root.current_tab == 0 else (0, 0, 0, 0)
                Rectangle:
                    pos: self.x, self.y
                    size: self.width, dp(2)

        Button:
            text: '正在播放'
            font_name: app.font_name
            size_hint_x: None
            width: dp(80)
            background_normal: ''
            background_color: (1, 1, 1, 1)
            color: (0.831, 0.235, 0.200, 1) if root.current_tab == 1 else (0.557, 0.557, 0.576, 1)
            font_size: sp(15)
            bold: root.current_tab == 1
            on_release: root.switch_tab(1)
            canvas.after:
                Color:
                    rgba: (0.831, 0.235, 0.200, 1) if root.current_tab == 1 else (0, 0, 0, 0)
                Rectangle:
                    pos: self.x, self.y
                    size: self.width, dp(2)

        Widget:

    # 内容区
    FloatLayout:
        size_hint_y: 1

        ScrollView:
            id: list_scroll
            opacity: 1 if root.current_tab == 0 else 0
            disabled: root.current_tab != 0
            do_scroll_x: False
            BoxLayout:
                id: song_list_box
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: 0
                spacing: 0

        BoxLayout:
            id: play_page
            orientation: 'vertical'
            opacity: 1 if root.current_tab == 1 else 0
            disabled: root.current_tab != 1
            padding: dp(20), dp(10)
            spacing: dp(10)

            RoundImage:
                id: cover_big
                size_hint: None, None
                size: dp(220), dp(220)
                pos_hint: {'center_x': 0.5}
                source: root.current_cover_path if root.current_cover_path else ''

            Label:
                text: root.current_title or '未播放'
                font_name: app.font_name
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(18)
                bold: True
                size_hint_y: None
                height: dp(30)

            Label:
                text: root.current_artist or '本地音乐'
                font_name: app.font_name
                color: (0.557, 0.557, 0.576, 1)
                font_size: sp(13)
                size_hint_y: None
                height: dp(20)

            ScrollView:
                id: lyrics_scroll
                do_scroll_x: False
                BoxLayout:
                    id: lyrics_box
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(6)
                    padding: dp(10), dp(10)

    # 底部播放条
    BoxLayout:
        size_hint_y: None
        height: dp(110)
        orientation: 'vertical'
        padding: dp(12), dp(6)
        spacing: dp(4)
        canvas.before:
            Color:
                rgba: 1, 1, 1, 1
            Rectangle:
                pos: self.pos
                size: self.size
            Color:
                rgba: 0.914, 0.914, 0.925, 1
            Rectangle:
                pos: self.x, self.top - dp(1)
                size: self.width, dp(1)

        Slider:
            id: progress_slider
            min: 0
            max: 1000
            value: 0
            size_hint_y: None
            height: dp(20)
            cursor_size: dp(14), dp(14)
            on_release: root.on_seek(self.value)

        BoxLayout:
            size_hint_y: None
            height: dp(68)
            spacing: dp(6)

            RoundImage:
                id: cover_small
                size_hint: None, None
                size: dp(48), dp(48)
                pos_hint: {'center_y': 0.5}
                source: root.current_cover_path if root.current_cover_path else ''

            BoxLayout:
                orientation: 'vertical'
                size_hint_x: 0.6
                Label:
                    text: root.current_title or '未播放'
                    font_name: app.font_name
                    color: (0.110, 0.110, 0.118, 1)
                    font_size: sp(13)
                    bold: True
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size
                    shorten: True
                Label:
                    text: root.current_artist or '本地音乐'
                    font_name: app.font_name
                    color: (0.557, 0.557, 0.576, 1)
                    font_size: sp(11)
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size
                    shorten: True

            Button:
                text: '⏪'
                font_name: app.font_name
                size_hint_x: None
                width: dp(36)
                background_normal: ''
                background_color: (1, 1, 1, 1)
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(16)
                on_release: root.on_rewind()

            Button:
                text: '⏮'
                font_name: app.font_name
                size_hint_x: None
                width: dp(36)
                background_normal: ''
                background_color: (1, 1, 1, 1)
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(18)
                on_release: root.on_prev()

            Button:
                text: ('⏸' if root.is_playing_state else '▶')
                font_name: app.font_name
                size_hint_x: None
                width: dp(48)
                background_normal: ''
                background_color: (1, 1, 1, 1)
                color: (0.831, 0.235, 0.200, 1)
                font_size: sp(26)
                on_release: root.on_play_pause()

            Button:
                text: '⏭'
                font_name: app.font_name
                size_hint_x: None
                width: dp(36)
                background_normal: ''
                background_color: (1, 1, 1, 1)
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(18)
                on_release: root.on_next()

            Button:
                text: '⏩'
                font_name: app.font_name
                size_hint_x: None
                width: dp(36)
                background_normal: ''
                background_color: (1, 1, 1, 1)
                color: (0.110, 0.110, 0.118, 1)
                font_size: sp(16)
                on_release: root.on_forward()
'''


# ============================================================
#  自定义组件
# ============================================================
class CardItem(ButtonBehavior, BoxLayout):
    song_index = NumericProperty(0)
    is_current = BooleanProperty(False)
    song_title = StringProperty('')
    song_artist = StringProperty('')
    song_duration = StringProperty('')


class RoundImage(BoxLayout):
    source = StringProperty('')


# ============================================================
#  主布局
# ============================================================
class MainLayout(BoxLayout):
    current_tab = NumericProperty(0)
    current_title = StringProperty('')
    current_artist = StringProperty('')
    current_cover_path = StringProperty('')
    is_playing_state = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.player = MusicPlayer()
        self.current_lyric_index = -1
        self.lyric_labels = []
        Clock.schedule_interval(self.update_tick, 0.25)

    # ---------- 文件选择 ----------
    def open_file_chooser(self):
        if HAS_ANDROID:
            try:
                request_permissions([
                    Permission.READ_EXTERNAL_STORAGE,
                    Permission.WRITE_EXTERNAL_STORAGE,
                ])
            except Exception:
                pass

        default_path = '/storage/emulated/0' if HAS_ANDROID else os.path.expanduser('~')
        if not os.path.exists(default_path):
            default_path = os.path.expanduser('~')

        content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        filechooser = FileChooserListView(
            path=default_path,
            filters=['*.mp3', '*.wav', '*.ogg', '*.flac', '*.m4a'],
            multiselect=True,
        )
        content.add_widget(filechooser)

        btn_box = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        btn_cancel = Button(text='取消', font_name=FONT_NAME,
                            background_color=(0.7, 0.7, 0.7, 1),
                            background_normal='')
        btn_ok = Button(text='导入', font_name=FONT_NAME,
                        background_color=COLOR_RED, background_normal='')
        btn_box.add_widget(btn_cancel)
        btn_box.add_widget(btn_ok)
        content.add_widget(btn_box)

        popup = Popup(title='选择音乐文件', content=content,
                      size_hint=(0.95, 0.95))

        def on_ok(*args):
            files = list(filechooser.selection)
            if files:
                added = self.player.add_files(files)
                self.refresh_song_list()
                if added:
                    self._toast(f'已添加 {len(added)} 首歌曲')
            popup.dismiss()

        btn_cancel.bind(on_release=popup.dismiss)
        btn_ok.bind(on_release=on_ok)
        popup.open()

    def switch_tab(self, index):
        self.current_tab = index

    # ---------- 列表 ----------
    def refresh_song_list(self):
        box = self.ids.song_list_box
        box.clear_widgets()
        for i, song in enumerate(self.player.playlist):
            item = CardItem(
                song_index=i,
                is_current=(i == self.player.current_index),
            )
            item.song_title = song['title']
            item.song_artist = song['artist']
            item.song_duration = self._fmt_duration(song['duration'])
            item.bind(on_release=lambda inst, idx=i: self.play_song(idx))
            box.add_widget(item)

    def _fmt_duration(self, sec):
        if sec <= 0:
            return '--:--'
        return f'{sec // 60:02d}:{sec % 60:02d}'

    # ---------- 播放控制 ----------
    def play_song(self, index):
        if self.player.play(index):
            self.refresh_playing_ui()
            self.refresh_song_list()

    def on_play_pause(self):
        if self.player.current_index < 0:
            if self.player.playlist:
                self.play_song(0)
            return
        if self.player.is_paused:
            self.player.resume()
        elif self.player.is_playing:
            self.player.pause()
        else:
            self.play_song(self.player.current_index)
        self.refresh_playing_ui()

    def on_prev(self):
        if self.player.prev():
            self.refresh_playing_ui()
            self.refresh_song_list()

    def on_next(self):
        if self.player.next():
            self.refresh_playing_ui()
            self.refresh_song_list()

    def on_forward(self):
        if self.player.current_index < 0:
            return
        self.player.fast_forward(10)
        self.refresh_playing_ui()

    def on_rewind(self):
        if self.player.current_index < 0:
            return
        self.player.rewind(10)
        self.refresh_playing_ui()

    def on_seek(self, value):
        if self.player.current_index < 0:
            return
        dur = self.player.playlist[self.player.current_index]['duration']
        if dur <= 0:
            return
        target = int(value / 1000 * dur)
        self.player.seek(target)
        self.refresh_playing_ui()

    # ---------- 定时器 ----------
    def update_tick(self, dt):
        if self.player.current_index < 0:
            return

        # 自动下一首
        if self.player.is_playing and not self.player.is_busy() and not self.player.is_paused:
            self.player.next()
            self.refresh_playing_ui()
            self.refresh_song_list()
            return

        dur = self.player.playlist[self.player.current_index]['duration']
        pos = self.player.get_position()
        if dur > 0:
            self.ids.progress_slider.value = pos / dur * 1000

        self.update_lyrics(pos)

    # ---------- UI 刷新 ----------
    def refresh_playing_ui(self):
        idx = self.player.current_index
        if idx < 0 or idx >= len(self.player.playlist):
            return
        song = self.player.playlist[idx]

        self.current_title = song['title']
        self.current_artist = song['artist']
        self.is_playing_state = (self.player.is_playing and not self.player.is_paused)

        if song['cover']:
            self._save_cover_to_file(idx, song['cover'])
        else:
            self.current_cover_path = ''

        if song['lyrics'] and not song['lyrics'].is_empty():
            self.load_lyrics(song['lyrics'].lines)
        else:
            self.load_lyrics([])

    def _save_cover_to_file(self, idx, cover_bytes):
        try:
            temp_dir = os.path.join(os.path.expanduser('~'), '.mymusic_covers')
            os.makedirs(temp_dir, exist_ok=True)
            path = os.path.join(temp_dir, f'cover_{idx}.jpg')
            with open(path, 'wb') as f:
                f.write(cover_bytes)
            self.current_cover_path = path
        except Exception as e:
            print(f'[封面保存失败] {e}')
            self.current_cover_path = ''

    # ---------- 歌词 ----------
    def load_lyrics(self, lines):
        self.lyric_labels = []
        self.current_lyric_index = -1
        box = self.ids.lyrics_box
        box.clear_widgets()

        if not lines:
            lbl = Label(
                text='暂无歌词',
                font_name=FONT_NAME,
                color=COLOR_GRAY,
                font_size=sp(15),
                size_hint_y=None,
                height=dp(60),
            )
            box.add_widget(lbl)
            return

        for t, text in lines:
            lbl = Label(
                text=text,
                font_name=FONT_NAME,
                color=COLOR_GRAY,
                font_size=sp(15),
                size_hint_y=None,
                height=dp(36),
                halign='center',
                valign='middle',
                text_size=(Window.width - dp(40), None),
            )
            box.add_widget(lbl)
            self.lyric_labels.append(lbl)

    def update_lyrics(self, seconds):
        if not self.lyric_labels:
            return
        song = self.player.playlist[self.player.current_index]
        if not song['lyrics']:
            return

        lines = song['lyrics'].lines
        target = -1
        for i, (t, _) in enumerate(lines):
            if t <= seconds:
                target = i
            else:
                break

        if target == self.current_lyric_index:
            return

        if 0 <= self.current_lyric_index < len(self.lyric_labels):
            self.lyric_labels[self.current_lyric_index].color = COLOR_GRAY
            self.lyric_labels[self.current_lyric_index].bold = False
            self.lyric_labels[self.current_lyric_index].font_size = sp(15)

        if 0 <= target < len(self.lyric_labels):
            self.lyric_labels[target].color = COLOR_RED
            self.lyric_labels[target].bold = True
            self.lyric_labels[target].font_size = sp(17)

        self.current_lyric_index = target

    def _toast(self, msg):
        popup = Popup(
            title='提示',
            content=Label(text=msg, font_name=FONT_NAME, color=COLOR_TEXT),
            size_hint=(0.7, 0.25),
        )
        popup.open()
        Clock.schedule_once(lambda dt: popup.dismiss(), 1.5)


# ============================================================
#  App
# ============================================================
class MyMusicApp(App):
    font_name = StringProperty(FONT_NAME)

    def build(self):
        self.title = '本地音乐'
        Builder.load_string(KV)
        return MainLayout()

    def on_pause(self):
        return True

    def on_resume(self):
        pass


if __name__ == '__main__':
    MyMusicApp().run()