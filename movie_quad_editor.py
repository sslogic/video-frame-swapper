import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter as tk

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk


SLOT_COUNT = 4
HIGH_FPS_TARGET = 120.0
PREVIEW_EDIT_DETAIL_RADIUS = 100
PREVIEW_MAX = (960, 540)
TIMELINE_HEIGHT = 86
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
ANALYSIS_SAMPLE_RATE = 22050
ANALYSIS_SECONDS = 90
APP_DIR = Path(__file__).resolve().parent
RECENT_PROJECTS_PATH = APP_DIR / "recent_projects.json"
SOURCE_FRAME_CACHE_LIMIT_BYTES = 2 * 1024 * 1024 * 1024


def best_effort_raise_process_priority():
    if os.name != "nt":
        return
    try:
        import ctypes

        priority = getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0) or getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)
        if priority:
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), priority)
    except Exception:
        pass


def high_priority_subprocess_flags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)


def encoder_options(encoder):
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "23", "-pix_fmt", "nv12"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


class FixedValue:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def clamp(value, low, high):
    return max(low, min(high, value))


def image_to_bgr(path, size):
    image = Image.open(path).convert("RGB")
    image = image.resize(size, Image.Resampling.LANCZOS)
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def load_recent_projects():
    try:
        data = json.loads(RECENT_PROJECTS_PATH.read_text(encoding="utf-8"))
        return [Path(item) for item in data if Path(item).exists()]
    except Exception:
        return []


def save_recent_projects(projects):
    unique = []
    seen = set()
    for project in projects:
        project = Path(project)
        key = str(project)
        if key not in seen and project.exists():
            unique.append(key)
            seen.add(key)
    RECENT_PROJECTS_PATH.write_text(json.dumps(unique[:12], indent=2), encoding="utf-8")


def shortest_semitone_shift(source_pc, target_pc):
    shift = (target_pc - source_pc) % 12
    if shift > 6:
        shift -= 12
    return shift


def key_label(result):
    if not result:
        return "unknown"
    return f"{KEY_NAMES[result['pc']]} {result['mode']} ({result['confidence']:.2f})"


def ffmpeg_pitch_filter(semitones):
    if semitones == 0:
        return "aresample=44100,"
    factor = 2 ** (semitones / 12.0)
    tempo = 1.0 / factor
    return f"aresample=44100,asetrate=44100*{factor:.8f},aresample=44100,atempo={tempo:.8f},"


def analyze_audio_key(ffmpeg, media_path):
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(ANALYSIS_SAMPLE_RATE),
        "-t",
        str(ANALYSIS_SECONDS),
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size < ANALYSIS_SAMPLE_RATE:
        raise RuntimeError(f"Not enough audio to analyze key in {Path(media_path).name}.")

    audio = audio - np.mean(audio)
    peak = np.max(np.abs(audio))
    if peak <= 1e-5:
        raise RuntimeError(f"Audio is too quiet to analyze key in {Path(media_path).name}.")
    audio = audio / peak

    window_size = 4096
    hop = 2048
    window = np.hanning(window_size)
    freqs = np.fft.rfftfreq(window_size, 1.0 / ANALYSIS_SAMPLE_RATE)
    usable = (freqs >= 60.0) & (freqs <= 5000.0)
    usable_freqs = freqs[usable]
    pitch_classes = np.round(12 * np.log2(usable_freqs / 440.0) + 69).astype(int) % 12

    chroma = np.zeros(12, dtype=np.float64)
    frame_count = 0
    for start in range(0, audio.size - window_size, hop):
        frame = audio[start : start + window_size] * window
        spectrum = np.abs(np.fft.rfft(frame))[usable]
        if spectrum.size == 0:
            continue
        spectrum = np.log1p(spectrum)
        for pc in range(12):
            chroma[pc] += spectrum[pitch_classes == pc].sum()
        frame_count += 1

    if frame_count == 0 or chroma.sum() <= 0:
        raise RuntimeError(f"Could not build chroma profile for {Path(media_path).name}.")

    chroma = chroma / np.linalg.norm(chroma)
    major = MAJOR_PROFILE / np.linalg.norm(MAJOR_PROFILE)
    minor = MINOR_PROFILE / np.linalg.norm(MINOR_PROFILE)
    scores = []
    for pc in range(12):
        scores.append((float(np.dot(chroma, np.roll(major, pc))), pc, "major"))
        scores.append((float(np.dot(chroma, np.roll(minor, pc))), pc, "minor"))
    scores.sort(reverse=True, key=lambda item: item[0])
    best_score, best_pc, best_mode = scores[0]
    second_score = scores[1][0]
    confidence = clamp((best_score - second_score) * 10.0, 0.0, 1.0)
    return {"pc": best_pc, "mode": best_mode, "score": best_score, "confidence": confidence}


def blend_replacement_frame(replacement, previous_frame, next_frame, color_strength, frequency_strength):
    context = []
    for frame in (previous_frame, next_frame):
        if frame is not None:
            context.append(frame.astype(np.float32))
    if not context:
        return replacement

    replacement_float = replacement.astype(np.float32)
    context_frame = np.mean(context, axis=0)

    repl_mean, repl_std = cv2.meanStdDev(replacement_float)
    ctx_mean, ctx_std = cv2.meanStdDev(context_frame)
    repl_mean = repl_mean.reshape(1, 1, 3)
    repl_std = np.maximum(repl_std.reshape(1, 1, 3), 1.0)
    ctx_mean = ctx_mean.reshape(1, 1, 3)
    ctx_std = np.maximum(ctx_std.reshape(1, 1, 3), 1.0)

    matched = (replacement_float - repl_mean) * (ctx_std / repl_std) + ctx_mean
    matched = np.clip(matched, 0, 255)
    blended = replacement_float * (1.0 - color_strength) + matched * color_strength
    edge_mix = min(0.35, color_strength * 0.5)
    blended = blended * (1.0 - edge_mix) + context_frame * edge_mix

    if frequency_strength > 0:
        blur_size = (0, 0)
        replacement_low = cv2.GaussianBlur(replacement_float, blur_size, 3.0)
        context_low = cv2.GaussianBlur(context_frame, blur_size, 3.0)
        replacement_detail = replacement_float - replacement_low
        context_detail = context_frame - context_low
        detail = replacement_detail * (1.0 - frequency_strength) + context_detail * frequency_strength
        low = cv2.GaussianBlur(blended, blur_size, 1.8)
        blended = low + detail
    return np.clip(blended, 0, 255).astype(np.uint8)


@dataclass
class AudioTrack:
    path: str
    volume: float = 0.5
    start_time: float = 0.0
    repeat: bool = True
    repeat_every: float = 0.0
    repeat_count: int = 0
    speed: float = 1.0
    masking: bool = True
    duck_below_main: bool = True
    duration: float = 0.0

    @property
    def name(self):
        return Path(self.path).name

    def to_dict(self):
        return {
            "path": self.path,
            "volume": self.volume,
            "start_time": self.start_time,
            "repeat": self.repeat,
            "repeat_every": self.repeat_every,
            "repeat_count": self.repeat_count,
            "speed": self.speed,
            "masking": self.masking,
            "duck_below_main": self.duck_below_main,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            path=str(data.get("path", "")),
            volume=float(data.get("volume", 0.5)),
            start_time=float(data.get("start_time", 0.0)),
            repeat=bool(data.get("repeat", True)),
            repeat_every=float(data.get("repeat_every", 0.0)),
            repeat_count=int(data.get("repeat_count", 0)),
            speed=float(data.get("speed", 1.0)),
            masking=bool(data.get("masking", True)),
            duck_below_main=bool(data.get("duck_below_main", True)),
            duration=float(data.get("duration", 0.0)),
        )

@dataclass
class VideoState:
    video_path: Path
    edit_path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    current_output_frame: int = 0
    edits: dict = field(default_factory=dict)
    source_volume: float = 1.0
    music_path: str = ""
    music_volume: float = 0.5
    music_tone_match: bool = False
    first_audio_as_main_mask: bool = False
    audio_tracks: list = field(default_factory=list)
    output_fps_multiplier: int = SLOT_COUNT
    frame_color_blend: bool = True
    frame_color_blend_strength: float = 0.65
    frame_frequency_blend_strength: float = 0.35

    @property
    def duration(self):
        return self.frame_count / self.fps if self.fps else 0

    @property
    def export_fps(self):
        return HIGH_FPS_TARGET if self.output_fps_multiplier == SLOT_COUNT else self.fps

    @property
    def output_frame_count(self):
        if self.output_fps_multiplier == SLOT_COUNT:
            return max(1, int(round(self.duration * self.export_fps)))
        return self.frame_count

    def source_frame_for_output(self, output_frame=None):
        output_frame = self.current_output_frame if output_frame is None else output_frame
        if self.output_fps_multiplier == SLOT_COUNT:
            frame_time = output_frame / self.export_fps
            return clamp(int(frame_time * self.fps), 0, self.frame_count - 1)
        return clamp(output_frame, 0, self.frame_count - 1)

    def output_frame_for_source(self, source_frame):
        source_frame = clamp(source_frame, 0, self.frame_count - 1)
        if self.output_fps_multiplier == SLOT_COUNT:
            return clamp(int(round((source_frame / self.fps) * self.export_fps)), 0, self.output_frame_count - 1)
        return source_frame

    def frame_override(self, output_frame=None):
        output_frame = self.current_output_frame if output_frame is None else output_frame
        return self.edits.get(str(output_frame))


class MovieQuadEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Frame Swapper")
        self.geometry("1180x760")
        self.minsize(980, 660)

        self.state = None
        self.capture = None
        self.preview_photo = None
        self.exporting = False
        self.replacing_frames = False
        self.playing = False
        self.play_after_id = None
        self.video_controls = []
        self.imported_image_path = None
        self.imported_image = None
        self.repeat_image_path = None
        self.repeat_editor_template = None
        self.editor_state = None
        self.source_frame_cache = None
        self.source_frame_cache_key = None
        self.recent_projects = load_recent_projects()
        self.music_volume_var = tk.DoubleVar(value=50.0)
        self.source_volume_var = tk.DoubleVar(value=100.0)
        self.music_label_var = tk.StringVar(value="No music track")
        self.music_tone_var = tk.BooleanVar(value=False)
        self.first_audio_mask_var = tk.BooleanVar(value=False)
        self.audio_editor_window = None
        self.high_fps_var = tk.BooleanVar(value=True)
        self.color_blend_var = tk.BooleanVar(value=True)
        self.color_blend_strength_var = tk.DoubleVar(value=65.0)
        self.frequency_blend_strength_var = tk.DoubleVar(value=35.0)
        self.timeline_zoom_var = tk.DoubleVar(value=1.0)

        self._build_ui()
        self._set_controls_enabled(False)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        topbar = ttk.Frame(self, padding=(10, 10, 10, 6))
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.columnconfigure(8, weight=1)

        self.open_button = ttk.Button(topbar, text="Open Video", command=self.open_video)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.save_button = ttk.Button(topbar, text="Save Edits", command=self.save_edits)
        self.save_button.grid(row=0, column=1, padx=(0, 8))
        self.open_project_button = ttk.Button(topbar, text="Open Project", command=self.open_project)
        self.open_project_button.grid(row=0, column=2, padx=(0, 8))
        self.recent_project_button = ttk.Button(topbar, text="Recent Project", command=self.open_recent_project)
        self.recent_project_button.grid(row=0, column=3, padx=(0, 8))
        self.export_button = ttk.Button(topbar, text="Export Video", command=self.export_video)
        self.export_button.grid(row=0, column=4, padx=(0, 12))
        self.play_button = ttk.Button(topbar, text="Play Preview", command=self.toggle_playback)
        self.play_button.grid(row=0, column=5, padx=(0, 12))
        self.new_window_button = ttk.Button(topbar, text="New Window", command=self.launch_new_instance)
        self.new_window_button.grid(row=0, column=6, padx=(0, 12))

        self.video_label = ttk.Label(topbar, text="No video loaded")
        self.video_label.grid(row=0, column=7, columnspan=2, sticky="w")

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        preview_panel = ttk.Frame(main, padding=10)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        main.add(preview_panel, weight=4)

        self.preview_canvas = tk.Canvas(preview_panel, bg="#151515", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        timeline_frame = ttk.Frame(preview_panel)
        timeline_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        timeline_frame.columnconfigure(1, weight=1)
        ttk.Button(timeline_frame, text="-", width=3, command=lambda: self.adjust_timeline_zoom(0.5)).grid(row=0, column=0, padx=(0, 6))
        self.timeline_canvas = tk.Canvas(
            timeline_frame,
            height=TIMELINE_HEIGHT,
            bg="#202020",
            highlightthickness=1,
            highlightbackground="#3f3f46",
            highlightcolor="#48a6ff",
            takefocus=True,
        )
        self.timeline_canvas.grid(row=0, column=1, sticky="ew")
        self.timeline_canvas.bind("<Button-1>", self.on_timeline_click)
        self.timeline_canvas.bind("<B1-Motion>", self.on_timeline_click)
        self.timeline_canvas.bind("<FocusIn>", lambda _event: self.draw_timeline())
        self.timeline_canvas.bind("<FocusOut>", lambda _event: self.draw_timeline())
        for key in ("<Left>", "<KP_Left>", "<Right>", "<KP_Right>", "<Up>", "<KP_Up>", "<Down>", "<KP_Down>"):
            self.timeline_canvas.bind(key, self.on_timeline_key)
        ttk.Button(timeline_frame, text="+", width=3, command=lambda: self.adjust_timeline_zoom(2.0)).grid(row=0, column=2, padx=(6, 0))

        controls_outer = ttk.Frame(main)
        controls_outer.rowconfigure(0, weight=1)
        controls_outer.rowconfigure(1, weight=1)
        controls_outer.columnconfigure(0, weight=1)

        controls = ttk.Frame(controls_outer, padding=10)
        controls.columnconfigure(0, weight=1)
        controls.grid(row=0, column=0, sticky="nsew")

        audio_outer = ttk.LabelFrame(controls_outer, text="Audio", padding=(0, 0, 0, 0))
        audio_outer.rowconfigure(0, weight=1)
        audio_outer.columnconfigure(0, weight=1)
        audio_canvas = tk.Canvas(audio_outer, highlightthickness=0, width=390)
        audio_scrollbar = ttk.Scrollbar(audio_outer, orient=tk.VERTICAL, command=audio_canvas.yview)
        audio_controls = ttk.Frame(audio_canvas, padding=10)
        audio_window = audio_canvas.create_window((0, 0), window=audio_controls, anchor="nw")
        audio_controls.columnconfigure(0, weight=1)
        audio_controls.bind("<Configure>", lambda _event: audio_canvas.configure(scrollregion=audio_canvas.bbox("all")))
        audio_canvas.bind("<Configure>", lambda event: audio_canvas.itemconfigure(audio_window, width=event.width))
        audio_canvas.configure(yscrollcommand=audio_scrollbar.set)
        audio_canvas.grid(row=0, column=0, sticky="nsew")
        audio_scrollbar.grid(row=0, column=1, sticky="ns")
        audio_outer.grid(row=1, column=0, sticky="nsew", padx=0, pady=(8, 0))
        main.add(controls_outer, weight=2)

        ttk.Label(controls, text="Output Frame").grid(row=0, column=0, sticky="w")
        frame_row = ttk.Frame(controls)
        frame_row.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        frame_row.columnconfigure(1, weight=1)
        self.prev_button = ttk.Button(frame_row, text="<", width=4, command=lambda: self.move_frame(-1))
        self.prev_button.grid(row=0, column=0, padx=(0, 6))
        self.frame_var = tk.StringVar(value="0")
        self.frame_entry = ttk.Entry(frame_row, textvariable=self.frame_var, width=10)
        self.frame_entry.grid(row=0, column=1, sticky="ew")
        self.frame_entry.bind("<Return>", lambda _event: self.goto_frame_entry())
        self.next_button = ttk.Button(frame_row, text=">", width=4, command=lambda: self.move_frame(1))
        self.next_button.grid(row=0, column=2, padx=(6, 0))

        self.frame_slider = ttk.Scale(controls, from_=0, to=0, orient=tk.HORIZONTAL, command=self.on_slider)
        self.frame_slider.grid(row=2, column=0, sticky="ew", pady=(0, 14))

        self.high_fps_check = ttk.Checkbutton(
            controls,
            text="120 FPS output",
            variable=self.high_fps_var,
            command=self.on_output_fps_changed,
        )
        self.high_fps_check.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        edit_row = ttk.Frame(controls)
        edit_row.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        edit_row.columnconfigure(0, weight=1)
        edit_row.columnconfigure(1, weight=1)
        edit_row.columnconfigure(2, weight=1)
        edit_row.columnconfigure(3, weight=1)
        edit_row.columnconfigure(4, weight=1)
        self.import_button = ttk.Button(edit_row, text="Import Image", command=self.import_image)
        self.import_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.edit_image_button = ttk.Button(edit_row, text="Edit Frame/Image", command=self.open_import_editor)
        self.edit_image_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.replace_button = ttk.Button(edit_row, text="Replace Frame", command=self.replace_frame)
        self.replace_button.grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.replace_interval_button = ttk.Button(edit_row, text="Replace Every X", command=self.replace_every_x_frames)
        self.replace_interval_button.grid(row=0, column=3, sticky="ew", padx=(0, 6))
        self.clear_button = ttk.Button(edit_row, text="Clear Frame", command=self.clear_frame)
        self.clear_button.grid(row=0, column=4, sticky="ew")

        self.color_blend_check = ttk.Checkbutton(
            controls,
            text="Color blend replacement images",
            variable=self.color_blend_var,
            command=self.on_color_blend_changed,
        )
        self.color_blend_check.grid(row=5, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(controls, text="Color Blend Strength").grid(row=6, column=0, sticky="w")
        self.color_blend_slider = ttk.Scale(
            controls,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.color_blend_strength_var,
            command=self.on_color_blend_changed,
        )
        self.color_blend_slider.grid(row=7, column=0, sticky="ew", pady=(2, 10))
        ttk.Label(controls, text="Image Frequency Blend").grid(row=8, column=0, sticky="w")
        self.frequency_blend_slider = ttk.Scale(
            controls,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.frequency_blend_strength_var,
            command=self.on_color_blend_changed,
        )
        self.frequency_blend_slider.grid(row=9, column=0, sticky="ew", pady=(2, 10))

        ttk.Label(controls, text="Timeline Zoom").grid(row=10, column=0, sticky="w")
        self.timeline_zoom_slider = ttk.Scale(
            controls,
            from_=1,
            to=80,
            orient=tk.HORIZONTAL,
            variable=self.timeline_zoom_var,
            command=self.on_timeline_zoom_changed,
        )
        self.timeline_zoom_slider.grid(row=11, column=0, sticky="ew", pady=(2, 10))

        ttk.Separator(controls).grid(row=12, column=0, sticky="ew", pady=8)

        music_row = ttk.Frame(audio_controls)
        music_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Audio Editor", command=self.open_audio_editor)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Audio", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(audio_controls, textvariable=self.music_label_var, wraplength=360).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.source_volume_slider = ttk.Scale(audio_controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.source_volume_var, command=self.on_source_volume_changed)
        self.music_volume_slider = ttk.Scale(audio_controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.music_volume_var, command=self.on_music_volume_changed)
        self.tone_match_button = ttk.Button(audio_controls, text="Tone Match + Half Volume", command=self.apply_tone_match_preset)

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(audio_controls, textvariable=self.status_var, wraplength=360, justify=tk.LEFT)
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        ttk.Separator(audio_controls).grid(row=3, column=0, sticky="ew", pady=8)

        self.info_var = tk.StringVar(value="")
        ttk.Label(audio_controls, textvariable=self.info_var, justify=tk.LEFT, wraplength=360).grid(row=4, column=0, sticky="ew")

        self.progress = ttk.Progressbar(audio_controls, mode="determinate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(16, 4))

        self.video_controls = [
            self.save_button,
            self.open_project_button,
            self.recent_project_button,
            self.export_button,
            self.play_button,
            self.prev_button,
            self.frame_entry,
            self.next_button,
            self.frame_slider,
            self.high_fps_check,
            self.import_button,
            self.edit_image_button,
            self.replace_button,
            self.replace_interval_button,
            self.clear_button,
            self.color_blend_check,
            self.color_blend_slider,
            self.frequency_blend_slider,
            self.add_music_button,
            self.clear_music_button,

            self.timeline_zoom_slider,
        ]

    def _set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.video_controls:
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def launch_new_instance(self):
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=str(APP_DIR),
                close_fds=True,
                creationflags=high_priority_subprocess_flags(),
            )
            self.status_var.set("Opened another editor window.")
        except Exception as exc:
            messagebox.showerror("New Window", f"Could not open another editor window:\n{exc}")

    def open_video(self):
        path = filedialog.askopenfilename(
            title="Open Video",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            messagebox.showerror("Open Video", "Could not open that video.")
            return

        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frame_count <= 0 or width <= 0 or height <= 0:
            capture.release()
            messagebox.showerror("Open Video", "Could not read video frame information.")
            return

        if self.capture:
            self.capture.release()
        self.stop_playback()
        self.capture = capture

        video_path = Path(path)
        edit_path = video_path.with_suffix(video_path.suffix + ".quad_edits.json")
        self.state = VideoState(video_path, edit_path, fps, frame_count, width, height)
        self.source_frame_cache = None
        self.source_frame_cache_key = None

        self.video_label.configure(text=str(video_path))
        self.frame_slider.configure(to=max(0, self.state.output_frame_count - 1))
        self._set_controls_enabled(True)
        self.status_var.set("Loaded video. Use Open Project to load saved edits.")
        self.update_info()
        self.show_current_frame()

    def open_video_path(self, path):
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            messagebox.showerror("Open Video", "Could not open that video.")
            return False
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frame_count <= 0 or width <= 0 or height <= 0:
            capture.release()
            messagebox.showerror("Open Video", "Could not read video frame information.")
            return False
        if self.capture:
            self.capture.release()
        self.stop_playback()
        self.capture = capture
        video_path = Path(path)
        edit_path = video_path.with_suffix(video_path.suffix + ".quad_edits.json")
        self.state = VideoState(video_path, edit_path, fps, frame_count, width, height)
        self.source_frame_cache = None
        self.source_frame_cache_key = None
        self.video_label.configure(text=str(video_path))
        self.frame_slider.configure(to=max(0, self.state.output_frame_count - 1))
        self._set_controls_enabled(True)
        return True

    def open_project(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("Frame swap project", "*.quad_edits.json"), ("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.load_project_file(Path(path))

    def open_recent_project(self):
        self.recent_projects = load_recent_projects()
        if not self.recent_projects:
            messagebox.showinfo("Recent Project", "No recent project found.")
            return
        self.load_project_file(self.recent_projects[0])

    def load_project_file(self, project_path):
        try:
            data = json.loads(Path(project_path).read_text(encoding="utf-8"))
            video_path = Path(data["video"])
        except Exception as exc:
            messagebox.showerror("Open Project", f"Could not read project file:\n{exc}")
            return
        if not video_path.exists():
            messagebox.showerror("Open Project", f"Video file is missing:\n{video_path}")
            return
        if not self.open_video_path(video_path):
            return
        self.state.edit_path = Path(project_path)
        self.apply_project_data(data)
        self.status_var.set(f"Opened project {Path(project_path).name}.")
        self.show_current_frame()

    def load_edits(self):
        if not self.state or not self.state.edit_path.exists():
            return
        try:
            data = json.loads(self.state.edit_path.read_text(encoding="utf-8"))
            if data.get("video") == str(self.state.video_path):
                self.apply_project_data(data)
                self.status_var.set(f"Loaded {len(self.state.edits)} saved frame swaps.")
        except Exception as exc:
            messagebox.showwarning("Load Edits", f"Could not load saved edit map:\n{exc}")

    def apply_project_data(self, data):
        self.state.edits = self.normalize_edit_map(data.get("edits", {}))
        self.state.source_volume = float(data.get("source_volume", 1.0))
        self.state.music_path = data.get("music_path", "")
        self.state.music_volume = float(data.get("music_volume", 0.5))
        self.state.music_tone_match = bool(data.get("music_tone_match", False))
        self.state.first_audio_as_main_mask = bool(data.get("first_audio_as_main_mask", False))
        tracks = data.get("audio_tracks")
        if isinstance(tracks, list):
            self.state.audio_tracks = [AudioTrack.from_dict(item) for item in tracks if item.get("path")]
        elif self.state.music_path:
            self.state.audio_tracks = [
                AudioTrack(
                    path=self.state.music_path,
                    volume=self.state.music_volume,
                    masking=self.state.music_tone_match,
                    duck_below_main=True,
                    duration=self.media_duration_seconds(self.state.music_path),
                )
            ]
        else:
            self.state.audio_tracks = []
        self.state.output_fps_multiplier = self.normalize_output_multiplier(data.get("output_fps_multiplier", SLOT_COUNT))
        self.state.frame_color_blend = bool(data.get("frame_color_blend", True))
        self.state.frame_color_blend_strength = float(data.get("frame_color_blend_strength", 0.65))
        self.state.frame_frequency_blend_strength = float(data.get("frame_frequency_blend_strength", 0.35))
        self.frame_slider.configure(to=max(0, self.state.output_frame_count - 1))
        self.state.current_output_frame = clamp(self.state.current_output_frame, 0, self.state.output_frame_count - 1)
        self.sync_output_fps_controls()
        self.sync_color_blend_controls()
        self.sync_music_controls()

    def normalize_output_multiplier(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = SLOT_COUNT
        return SLOT_COUNT if value == SLOT_COUNT else 1

    def normalize_edit_map(self, edits):
        normalized = {}
        for key, value in edits.items():
            if ":" in key:
                try:
                    frame_text, slot_text = key.split(":", 1)
                    output_frame = int(frame_text) * SLOT_COUNT + int(slot_text)
                    normalized[str(output_frame)] = value
                except ValueError:
                    continue
            else:
                normalized[str(key)] = value
        return normalized

    def save_edits(self):
        if not self.state:
            return
        data = {
            "video": str(self.state.video_path),
            "fps": self.state.fps,
            "width": self.state.width,
            "height": self.state.height,
            "edits": self.state.edits,
            "source_volume": self.state.source_volume,
            "music_path": self.state.music_path,
            "music_volume": self.state.music_volume,
            "music_tone_match": self.state.music_tone_match,
            "first_audio_as_main_mask": self.state.first_audio_as_main_mask,
            "audio_tracks": [track.to_dict() for track in self.state.audio_tracks],
            "output_fps_multiplier": self.state.output_fps_multiplier,
            "frame_color_blend": self.state.frame_color_blend,
            "frame_color_blend_strength": self.state.frame_color_blend_strength,
            "frame_frequency_blend_strength": self.state.frame_frequency_blend_strength,
        }
        self.state.edit_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.remember_project(self.state.edit_path)
        self.status_var.set(f"Saved edits to {self.state.edit_path.name}.")

    def remember_project(self, project_path):
        project_path = Path(project_path)
        self.recent_projects = [project_path] + [p for p in load_recent_projects() if p != project_path]
        save_recent_projects(self.recent_projects)

    def sync_music_controls(self):
        if not self.state:
            self.music_label_var.set("No added audio tracks")
            self.music_volume_var.set(50.0)
            self.source_volume_var.set(100.0)
            self.music_tone_var.set(False)
            self.first_audio_mask_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
        self.first_audio_mask_var.set(self.state.first_audio_as_main_mask)
        if self.state.audio_tracks:
            count = len(self.state.audio_tracks)
            masking_count = sum(1 for track in self.state.audio_tracks if track.masking)
            duck_count = sum(1 for track in self.state.audio_tracks if track.duck_below_main)
            first_mask = ", first track as main mask" if self.state.first_audio_as_main_mask else ""
            self.music_label_var.set(
                f"{count} added audio track(s), main {self.source_volume_var.get():.0f}%, "
                f"masking {masking_count}, below-main {duck_count}{first_mask}"
            )
        else:
            self.music_label_var.set("No added audio tracks")

    def sync_output_fps_controls(self):
        if not self.state:
            self.high_fps_var.set(True)
            return
        self.high_fps_var.set(self.state.output_fps_multiplier == SLOT_COUNT)

    def on_output_fps_changed(self):
        if not self.state:
            return
        self.stop_playback()
        source_frame = self.state.source_frame_for_output()
        self.state.output_fps_multiplier = SLOT_COUNT if self.high_fps_var.get() else 1
        self.state.current_output_frame = clamp(
            self.state.output_frame_for_source(source_frame),
            0,
            self.state.output_frame_count - 1,
        )
        self.frame_slider.configure(to=max(0, self.state.output_frame_count - 1))
        self.status_var.set(
            f"120 FPS output {'enabled' if self.state.output_fps_multiplier == SLOT_COUNT else 'disabled'}."
        )
        self.show_current_frame()

    def sync_color_blend_controls(self):
        if not self.state:
            self.color_blend_var.set(True)
            self.color_blend_strength_var.set(65.0)
            return
        self.color_blend_var.set(self.state.frame_color_blend)
        self.color_blend_strength_var.set(round(self.state.frame_color_blend_strength * 100, 1))
        self.frequency_blend_strength_var.set(round(self.state.frame_frequency_blend_strength * 100, 1))

    def read_frame(self, frame_index):
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.capture.read()
        if not ok:
            return None
        return frame

    def get_output_frame(self, output_frame):
        source_frame = self.state.source_frame_for_output(output_frame)
        override = self.state.frame_override(output_frame)
        if override and Path(override).exists():
            return self.make_replacement_frame(output_frame, override)
        return self.read_frame(source_frame)

    def source_frame_cache_bytes(self, frame_count):
        if not self.state:
            return 0
        return int(self.state.width) * int(self.state.height) * 3 * int(frame_count)

    def preload_source_frames(self, frame_indices, label):
        if not self.state:
            return None
        unique_indices = sorted({clamp(int(frame_index), 0, self.state.frame_count - 1) for frame_index in frame_indices})
        if not unique_indices:
            return {}
        estimated_bytes = self.source_frame_cache_bytes(len(unique_indices))
        if estimated_bytes > SOURCE_FRAME_CACHE_LIMIT_BYTES:
            estimated_gb = estimated_bytes / (1024 ** 3)
            limit_gb = SOURCE_FRAME_CACHE_LIMIT_BYTES / (1024 ** 3)
            self.after(
                0,
                self.status_var.set,
                f"{label}: {estimated_gb:.1f} GB decoded, above {limit_gb:.1f} GB RAM cache limit. Streaming instead...",
            )
            return None

        self.after(0, self.status_var.set, f"{label}: loading {len(unique_indices)} source frames into memory...")
        cache = {}
        cap = cv2.VideoCapture(str(self.state.video_path))
        current_source_frame = None
        try:
            for offset, frame_index in enumerate(unique_indices):
                if current_source_frame is not None and frame_index == current_source_frame + 1:
                    ok, frame = cap.read()
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    ok, frame = cap.read()
                if ok:
                    cache[frame_index] = frame
                    current_source_frame = frame_index
                if offset % 50 == 0:
                    self.after(0, self.status_var.set, f"{label}: loaded {offset + 1} of {len(unique_indices)} frames into memory...")
        finally:
            cap.release()
        self.after(0, self.status_var.set, f"{label}: using {len(cache)} cached source frames from memory...")
        return cache

    def frame_from_cache_or_video(self, frame_index, frame_cache=None, cap=None):
        frame_index = clamp(int(frame_index), 0, self.state.frame_count - 1)
        if frame_cache is not None and frame_index in frame_cache:
            return frame_cache[frame_index]
        return self.read_frame_from_video(frame_index, cap)

    def read_frame_from_video(self, frame_index, cap=None):
        own_capture = cap is None
        cap = cap or cv2.VideoCapture(str(self.state.video_path))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, clamp(frame_index, 0, self.state.frame_count - 1))
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            if own_capture:
                cap.release()

    def preload_replacement_images(self):
        cache = {}
        for override in sorted({str(path) for path in self.state.edits.values()}):
            path = Path(override)
            if path.exists():
                cache[str(path)] = image_to_bgr(path, (self.state.width, self.state.height))
        if cache:
            self.after(0, self.status_var.set, f"Cached {len(cache)} replacement images for export...")
        return cache

    def make_replacement_frame(self, output_frame, override_path, frame_reader=None, replacement_cache=None):
        path_key = str(Path(override_path))
        replacement = replacement_cache.get(path_key) if replacement_cache is not None else None
        if replacement is None:
            replacement = image_to_bgr(override_path, (self.state.width, self.state.height))
        if not self.state.frame_color_blend:
            return replacement
        frame_reader = frame_reader or self.read_frame_from_video
        previous_output = max(0, output_frame - 1)
        next_output = min(self.state.output_frame_count - 1, output_frame + 1)
        previous_frame = frame_reader(self.state.source_frame_for_output(previous_output))
        next_frame = frame_reader(self.state.source_frame_for_output(next_output))
        return blend_replacement_frame(
            replacement,
            previous_frame,
            next_frame,
            self.state.frame_color_blend_strength,
            self.state.frame_frequency_blend_strength,
        )

    def show_current_frame(self):
        if not self.state:
            return
        image = self.make_frame_preview()
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_canvas.delete("all")
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        x = canvas_width // 2
        y = canvas_height // 2
        self.preview_canvas.create_image(x, y, image=self.preview_photo)

        self.frame_var.set(str(self.state.current_output_frame))
        self.frame_slider.set(self.state.current_output_frame)
        self.update_info()
        self.draw_timeline()

    def toggle_playback(self):
        if not self.state:
            return
        if self.playing:
            self.stop_playback()
            return
        self.playing = True
        self.play_button.configure(text="Stop Preview")
        self.status_var.set(
            f"Playing preview at {self.state.export_fps:.3f} FPS. Full detail within {PREVIEW_EDIT_DETAIL_RADIUS} frames of edits."
        )
        self.playback_tick()

    def stop_playback(self):
        self.playing = False
        if self.play_after_id is not None:
            try:
                self.after_cancel(self.play_after_id)
            except tk.TclError:
                pass
            self.play_after_id = None
        if hasattr(self, "play_button"):
            try:
                self.play_button.configure(text="Play Preview")
            except tk.TclError:
                pass

    def playback_tick(self):
        if not self.playing or not self.state:
            self.stop_playback()
            return
        self.show_current_frame()
        if self.state.current_output_frame >= self.state.output_frame_count - 1:
            self.stop_playback()
            return
        step = self.preview_playback_step(self.state.current_output_frame)
        self.state.current_output_frame = clamp(
            self.state.current_output_frame + step,
            0,
            self.state.output_frame_count - 1,
        )
        playback_fps = max(1.0, self.state.export_fps)
        self.play_after_id = self.after(max(1, int(round(1000 * step / playback_fps))), self.playback_tick)

    def preview_playback_step(self, output_frame):
        if self.preview_frame_near_edit(output_frame):
            return 1
        current_source = self.state.source_frame_for_output(output_frame)
        next_source_frame = min(self.state.frame_count - 1, current_source + 1)
        next_source_output = self.state.output_frame_for_source(next_source_frame)
        if next_source_output <= output_frame:
            return 1
        next_edit = self.next_edit_frame(output_frame)
        if next_edit is not None:
            next_source_output = min(next_source_output, max(output_frame + 1, next_edit - PREVIEW_EDIT_DETAIL_RADIUS))
        return max(1, next_source_output - output_frame)

    def preview_frame_near_edit(self, output_frame):
        edit_frame = self.next_edit_frame(output_frame - PREVIEW_EDIT_DETAIL_RADIUS)
        if edit_frame is None:
            return False
        return abs(edit_frame - output_frame) <= PREVIEW_EDIT_DETAIL_RADIUS

    def next_edit_frame(self, output_frame):
        candidates = []
        for key in self.state.edits:
            try:
                edit_frame = int(key)
            except ValueError:
                continue
            if edit_frame >= output_frame:
                candidates.append(edit_frame)
        return min(candidates) if candidates else None

    def make_frame_preview(self):
        canvas_width = max(640, self.preview_canvas.winfo_width() or PREVIEW_MAX[0])
        canvas_height = max(420, self.preview_canvas.winfo_height() or PREVIEW_MAX[1])
        sheet_width = min(PREVIEW_MAX[0], canvas_width - 24)
        sheet_height = min(PREVIEW_MAX[1], canvas_height - 24)
        sheet = Image.new("RGB", (sheet_width, sheet_height), "#101010")
        draw = ImageDraw.Draw(sheet)
        frame = self.get_output_frame(self.state.current_output_frame)
        if frame is not None:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            max_image_width = sheet_width - 24
            max_image_height = sheet_height - 48
            if self.playing and not self.preview_frame_near_edit(self.state.current_output_frame):
                max_image_width = max(160, int(max_image_width * 0.55))
                max_image_height = max(90, int(max_image_height * 0.55))
            image.thumbnail((max_image_width, max_image_height), Image.Resampling.LANCZOS)
            sheet.paste(image, ((sheet_width - image.width) // 2, (sheet_height - image.height) // 2 + 10))
        override = self.state.frame_override()
        label = f"Frame {self.state.current_output_frame}  source {self.state.source_frame_for_output()}"
        if override:
            label += "  swapped"
        draw.rectangle([10, 10, 260, 36], fill="#000000")
        draw.text((18, 17), label, fill="#ffffff")
        return sheet

    def draw_timeline(self):
        if not self.state:
            return
        canvas = self.timeline_canvas
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = TIMELINE_HEIGHT
        total = max(1, self.state.output_frame_count)
        zoom = max(1.0, self.timeline_zoom_var.get())
        visible = max(12, int(total / zoom))
        current = self.state.current_output_frame
        start = clamp(current - visible // 2, 0, max(0, total - visible))
        end = min(total, start + visible)
        focused = self.focus_get() == canvas
        canvas.create_rectangle(0, 0, width, height, fill="#202020", outline="#48a6ff" if focused else "")
        cell_width = width / max(1, end - start)
        show_all_copies = visible <= 96 or cell_width >= 8
        show_original_frames = not show_all_copies and (visible <= self.state.frame_count * 2 or cell_width >= 2)
        if show_all_copies:
            self.draw_output_frame_cells(canvas, start, end, width)
        elif show_original_frames:
            self.draw_original_frame_cells(canvas, start, end, width)
        else:
            self.draw_timeline_overview(canvas, start, end, width)
        play_x = int((current - start) / max(1, end - start) * width)
        canvas.create_line(play_x, 10, play_x, height - 8, fill="#48a6ff", width=3)
        canvas.create_text(8, 10, anchor="nw", text=f"{start} - {end - 1} / {total - 1}", fill="#e5e7eb")
        hint = "keys: left/right step, up/down zoom" if focused else "click timeline for keys"
        canvas.create_text(width - 8, 10, anchor="ne", text=f"zoom {zoom:.1f}x", fill="#e5e7eb")
        canvas.create_text(width // 2, height - 12, text=hint, fill="#cbd5e1")

    def draw_output_frame_cells(self, canvas, start, end, width):
        count = max(1, end - start)
        for output_frame in range(start, end):
            x = int((output_frame - start) / count * width)
            x2 = int((output_frame + 1 - start) / count * width)
            source_frame = self.state.source_frame_for_output(output_frame)
            copy_index = output_frame - self.state.output_frame_for_source(source_frame)
            swapped = str(output_frame) in self.state.edits
            if swapped:
                fill = "#f59e0b"
            elif copy_index == 0:
                fill = "#64748b"
            else:
                fill = "#374151"
            canvas.create_rectangle(x, 28, max(x + 1, x2), 64, fill=fill, outline="#111827")
            if x2 - x >= 24:
                label = "O" if copy_index == 0 else str(copy_index + 1)
                canvas.create_text((x + x2) // 2, 40, text=label, fill="#f8fafc", font=("Segoe UI", 9, "bold"))
                canvas.create_text((x + x2) // 2, 56, text=str(output_frame), fill="#e5e7eb", font=("Segoe UI", 7))
            elif x2 - x >= 12:
                label = "O" if copy_index == 0 else str(copy_index + 1)
                canvas.create_text((x + x2) // 2, 46, text=label, fill="#f8fafc", font=("Segoe UI", 8))

    def draw_original_frame_cells(self, canvas, start, end, width):
        first_source = self.state.source_frame_for_output(start)
        last_source = self.state.source_frame_for_output(end - 1)
        source_count = max(1, last_source - first_source + 1)
        for source_frame in range(first_source, last_source + 1):
            output_start = self.state.output_frame_for_source(source_frame)
            if source_frame >= self.state.frame_count - 1:
                output_end = self.state.output_frame_count
            else:
                output_end = self.state.output_frame_for_source(source_frame + 1)
            x = int((max(output_start, start) - start) / max(1, end - start) * width)
            x2 = int((min(output_end, end) - start) / max(1, end - start) * width)
            swapped = any(str(i) in self.state.edits for i in range(output_start, output_end))
            fill = "#f59e0b" if swapped else "#475569"
            canvas.create_rectangle(x, 30, max(x + 1, x2), 62, fill=fill, outline="#1f2937")
            if x2 - x >= 26:
                canvas.create_text((x + x2) // 2, 46, text=str(source_frame), fill="#f8fafc", font=("Segoe UI", 8))

    def draw_timeline_overview(self, canvas, start, end, width):
        canvas.create_rectangle(0, 34, width, 58, fill="#334155", outline="")
        for output_frame_text in self.state.edits:
            try:
                output_frame = int(output_frame_text)
            except ValueError:
                continue
            if start <= output_frame < end:
                x = int((output_frame - start) / max(1, end - start) * width)
                canvas.create_line(x, 28, x, 66, fill="#f59e0b", width=2)

    def on_timeline_click(self, event):
        if not self.state:
            return
        self.stop_playback()
        self.timeline_canvas.focus_set()
        width = max(1, self.timeline_canvas.winfo_width())
        total = max(1, self.state.output_frame_count)
        zoom = max(1.0, self.timeline_zoom_var.get())
        visible = max(12, int(total / zoom))
        start = clamp(self.state.current_output_frame - visible // 2, 0, max(0, total - visible))
        frame = start + int(clamp(event.x / width, 0.0, 1.0) * max(1, visible - 1))
        self.state.current_output_frame = clamp(frame, 0, total - 1)
        self.show_current_frame()

    def on_timeline_key(self, event):
        if not self.state:
            return "break"
        if event.keysym in ("Left", "KP_Left"):
            self.move_frame(-1)
        elif event.keysym in ("Right", "KP_Right"):
            self.move_frame(1)
        elif event.keysym in ("Up", "KP_Up"):
            self.adjust_timeline_zoom(1.35)
        elif event.keysym in ("Down", "KP_Down"):
            self.adjust_timeline_zoom(1 / 1.35)
        return "break"

    def update_info(self):
        if not self.state:
            self.info_var.set("")
            return
        override = self.state.frame_override()
        frame_text = "swapped image" if override else "source video frame"
        source_frame = self.state.source_frame_for_output()
        copy_number = self.state.current_output_frame - self.state.output_frame_for_source(source_frame) + 1
        copy_text = "original copy" if copy_number == 1 else f"copy {copy_number}"
        fps_mode = "120 FPS" if self.state.output_fps_multiplier == SLOT_COUNT else "normal"
        self.info_var.set(
            f"Source frames: {self.state.frame_count}\n"
            f"Source FPS: {self.state.fps:.3f}\n"
            f"Export frames: {self.state.output_frame_count}\n"
            f"Export FPS: {self.state.export_fps:.3f}\n"
            f"FPS mode: {fps_mode}\n"
            f"Duration: {self.state.duration:.2f} seconds\n"
            f"Swapped frames: {len(self.state.edits)}\n"
            f"Current frame: {self.state.current_output_frame} ({copy_text} of source {source_frame})\n"
            f"Frame content: {frame_text}\n"
            f"Audio tracks: {len(self.state.audio_tracks)} added\n"
            f"Color blend: {'on' if self.state.frame_color_blend else 'off'}"
        )

    def move_frame(self, delta):
        if not self.state:
            return
        self.stop_playback()
        self.state.current_output_frame = clamp(
            self.state.current_output_frame + delta,
            0,
            self.state.output_frame_count - 1,
        )
        self.show_current_frame()

    def goto_frame_entry(self):
        if not self.state:
            return
        self.stop_playback()
        try:
            frame = int(self.frame_var.get())
        except ValueError:
            frame = self.state.current_output_frame
        self.state.current_output_frame = clamp(frame, 0, self.state.output_frame_count - 1)
        self.show_current_frame()

    def on_slider(self, value):
        if not self.state:
            return
        if self.playing:
            return
        frame = int(float(value))
        if frame != self.state.current_output_frame:
            self.state.current_output_frame = frame
            self.show_current_frame()

    def on_timeline_zoom_changed(self, _value=None):
        if not self.state:
            return
        self.draw_timeline()

    def adjust_timeline_zoom(self, factor):
        self.timeline_zoom_var.set(clamp(self.timeline_zoom_var.get() * factor, 1.0, 80.0))
        self.draw_timeline()

    def replace_frame(self):
        if not self.state:
            return
        path = filedialog.askopenfilename(
            title="Choose Image For This Frame",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            Image.open(path).verify()
        except Exception:
            messagebox.showerror("Replace Frame", "That file does not look like a readable image.")
            return
        path = Path(path)
        self.repeat_image_path = path
        self.repeat_editor_template = None
        self.state.edits[str(self.state.current_output_frame)] = str(path)
        self.show_current_frame()
        self.status_var.set("Frame replaced. Click Save Edits to keep this change.")

    def replace_every_x_frames(self):
        if not self.state or self.exporting or self.replacing_frames:
            return
        if self.repeat_image_path and self.repeat_image_path.exists():
            path = self.repeat_image_path
        elif self.imported_image_path and self.imported_image_path.exists():
            path = self.imported_image_path
        else:
            path_text = filedialog.askopenfilename(
                title="Choose Image For Repeated Replacement",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                    ("All files", "*.*"),
                ],
            )
            if not path_text:
                return
            path = Path(path_text)
            try:
                self.imported_image = Image.open(path).convert("RGBA")
                self.imported_image_path = path
                self.repeat_image_path = path
            except Exception:
                messagebox.showerror("Replace Every X", "That file does not look like a readable image.")
                return
        interval = simpledialog.askinteger(
            "Replace Every X",
            "Replace one frame every how many output frames?",
            parent=self,
            minvalue=1,
            maxvalue=max(1, self.state.output_frame_count),
        )
        if not interval:
            return

        start_frame = self.state.current_output_frame
        template = self.repeat_editor_template
        path = Path(path)
        total = len(range(start_frame, self.state.output_frame_count, interval))
        self.replacing_frames = True
        self.stop_playback()
        self.open_button.configure(state=tk.DISABLED)
        self._set_controls_enabled(False)
        self.progress.configure(value=0, maximum=max(1, total))
        self.status_var.set(f"Replacing {total} frames every {interval} output frames...")
        thread = threading.Thread(
            target=self._replace_every_x_worker,
            args=(start_frame, interval, path, template, total),
            daemon=True,
        )
        thread.start()

    def _replace_every_x_worker(self, start_frame, interval, path, template, total):
        best_effort_raise_process_priority()
        edits = {}
        count = 0
        cap = None
        try:
            if template:
                edit_dir = self.state.video_path.with_suffix("").parent / ".frame_edits"
                edit_dir.mkdir(exist_ok=True)
                output_frames = list(range(start_frame, self.state.output_frame_count, interval))
                frame_cache = self.preload_source_frames(
                    (self.state.source_frame_for_output(output_frame) for output_frame in output_frames),
                    "Replace Every X",
                )
                cap = cv2.VideoCapture(str(self.state.video_path))
                for index, output_frame in enumerate(output_frames):
                    output = edit_dir / f"{self.state.video_path.stem}_frame_{output_frame}.png"
                    custom_image = self.compose_editor_template_image(template, output_frame, cap, frame_cache)
                    if custom_image is not None:
                        custom_image.convert("RGB").save(output)
                        edits[str(output_frame)] = str(output)
                        count += 1
                    if index % 10 == 0:
                        self.after(0, self.progress.configure, {"value": index + 1})
                        self.after(0, self.status_var.set, f"Replacing frame {index + 1} of {total}...")
            else:
                for index, output_frame in enumerate(range(start_frame, self.state.output_frame_count, interval)):
                    edits[str(output_frame)] = str(path)
                    count += 1
                    if index % 500 == 0:
                        self.after(0, self.progress.configure, {"value": index + 1})
            self.after(0, self._replace_every_x_done, start_frame, interval, edits, count, None)
        except Exception as exc:
            self.after(0, self._replace_every_x_done, start_frame, interval, edits, count, exc)
        finally:
            if cap is not None:
                cap.release()

    def _replace_every_x_done(self, start_frame, interval, edits, count, error):
        self.replacing_frames = False
        self.open_button.configure(state=tk.NORMAL)
        self._set_controls_enabled(True)
        self.progress.configure(value=0)
        if error:
            self.status_var.set("Replace Every X failed.")
            messagebox.showerror("Replace Every X", str(error))
            return
        self.state.edits.update(edits)
        self.show_current_frame()
        self.status_var.set(
            f"Replaced {count} frames every {interval} output frames starting at frame {start_frame}. Click Save Edits to keep this change."
        )

    def import_image(self):
        if not self.state:
            return
        path = filedialog.askopenfilename(
            title="Import Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            self.imported_image = Image.open(path).convert("RGBA")
        except Exception:
            messagebox.showerror("Import Image", "That file does not look like a readable image.")
            return
        self.imported_image_path = Path(path)
        self.repeat_image_path = self.imported_image_path
        self.repeat_editor_template = None
        self.status_var.set(f"Imported {self.imported_image_path.name}.")

    def fit_image_to_frame(self, image, frame_size, scale_percent=100.0):
        frame_width, frame_height = frame_size
        image_width, image_height = image.size
        if image_width <= 0 or image_height <= 0:
            return Image.new("RGBA", frame_size, (0, 0, 0, 0))
        fit_scale = min(frame_width / image_width, frame_height / image_height)
        scale = fit_scale * (clamp(float(scale_percent), 5.0, 300.0) / 100.0)
        fitted_width = max(1, int(image_width * scale))
        fitted_height = max(1, int(image_height * scale))
        if (fitted_width, fitted_height) != image.size:
            image = image.resize((fitted_width, fitted_height), Image.Resampling.LANCZOS)
        layer = Image.new("RGBA", frame_size, (0, 0, 0, 0))
        layer.paste(image, ((frame_width - fitted_width) // 2, (frame_height - fitted_height) // 2), image)
        return layer

    def open_import_editor(self, initial_tool="brush", seed_text=False):
        if not self.state:
            return

        editor_output_frame = self.state.current_output_frame
        original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))
        if original_frame is None:
            messagebox.showerror("Edit Frame", "Could not read the frame being edited.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        direct_frame_edit = self.imported_image is None
        if direct_frame_edit:
            imported_source = Image.new("RGBA", original.size, (0, 0, 0, 0))
            imported = imported_source.copy()
            frame_opacity = 100.0
            image_opacity = 0.0
        else:
            imported_source = self.imported_image.copy().convert("RGBA")
            imported = self.fit_image_to_frame(imported_source, original.size)
            frame_opacity = 35.0
            image_opacity = 100.0

        window = tk.Toplevel(self)
        window.title("Edit Frame" if direct_frame_edit else "Edit Imported Image")
        window.geometry("1180x760")
        window.minsize(980, 640)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        canvas = tk.Canvas(window, bg="#151515", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        panel_outer = ttk.Frame(window)
        panel_outer.grid(row=0, column=1, sticky="ns")
        panel_canvas = tk.Canvas(panel_outer, width=260, highlightthickness=0)
        panel_scrollbar = ttk.Scrollbar(panel_outer, orient=tk.VERTICAL, command=panel_canvas.yview)
        panel = ttk.Frame(panel_canvas, padding=10)
        panel_window = panel_canvas.create_window((0, 0), window=panel, anchor="nw")
        panel_canvas.configure(yscrollcommand=panel_scrollbar.set)
        panel_canvas.grid(row=0, column=0, sticky="ns")
        panel_scrollbar.grid(row=0, column=1, sticky="ns")
        panel_outer.rowconfigure(0, weight=1)

        def sync_panel_scroll(_event=None):
            panel_canvas.configure(scrollregion=panel_canvas.bbox("all"))

        def sync_panel_width(event):
            panel_canvas.itemconfigure(panel_window, width=event.width)

        def scroll_panel(event):
            panel_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        panel.bind("<Configure>", sync_panel_scroll)
        panel_canvas.bind("<Configure>", sync_panel_width)
        panel_canvas.bind("<MouseWheel>", scroll_panel)
        panel.bind("<MouseWheel>", scroll_panel)
        panel_canvas.bind("<Enter>", lambda _event: panel_canvas.bind_all("<MouseWheel>", scroll_panel))
        panel_canvas.bind("<Leave>", lambda _event: panel_canvas.unbind_all("<MouseWheel>"))
        panel.bind("<Enter>", lambda _event: panel_canvas.bind_all("<MouseWheel>", scroll_panel))
        panel.bind("<Leave>", lambda _event: panel_canvas.unbind_all("<MouseWheel>"))

        tool_var = tk.StringVar(value=initial_tool)
        text_var = tk.StringVar(value="Text")
        brush_color = {"value": "#ffffff"}
        text_color = {"value": "#ffffff"}
        bg_color = {"value": "#000000"}
        state = {
            "window": window,
            "canvas": canvas,
            "editor_output_frame": editor_output_frame,
            "original": original,
            "imported_source": imported_source,
            "imported_content": imported_source.copy(),
            "imported": imported,
            "direct_frame_edit": direct_frame_edit,
            "background_image": None,
            "draw_layer": Image.new("RGBA", original.size, (0, 0, 0, 0)),
            "text_objects": [],
            "selected_text": None,
            "duplicate_button_bbox": None,
            "undo_stack": [],
            "is_restoring": False,
            "control_undo_active": False,
            "paint_undo_active": False,
            "text_drag_undo_active": False,
            "photo": None,
            "preview_scale": 1.0,
            "preview_offset": (0, 0),
            "frame_opacity": tk.DoubleVar(value=frame_opacity),
            "image_opacity": tk.DoubleVar(value=image_opacity),
            "image_size": tk.DoubleVar(value=100.0),
            "image_rotation": tk.DoubleVar(value=0.0),
            "background_remove_tolerance": tk.DoubleVar(value=38.0),
            "brush_size": tk.DoubleVar(value=24.0),
            "paint_opacity": tk.DoubleVar(value=55.0),
            "text_opacity": tk.DoubleVar(value=100.0),
            "text_camouflage": tk.DoubleVar(value=0.0),
            "text_border_enabled": tk.BooleanVar(value=False),
            "text_size": tk.DoubleVar(value=64.0),
            "text_thickness": tk.DoubleVar(value=0.0),
            "text_rotation": tk.DoubleVar(value=0.0),
            "text_warp": tk.DoubleVar(value=0.0),
            "tool_var": tool_var,
            "text_var": text_var,
            "brush_color": brush_color,
            "text_color": text_color,
            "bg_color": bg_color,
        }
        self.editor_state = state

        ttk.Label(panel, text="Layer Opacity").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Original frame").grid(row=1, column=0, sticky="w")
        ttk.Scale(panel, from_=0, to=100, variable=state["frame_opacity"], command=self.on_editor_layer_control_changed).grid(row=2, column=0, sticky="ew")
        ttk.Label(panel, text="Image layer").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["image_opacity"], command=self.on_editor_layer_control_changed).grid(row=4, column=0, sticky="ew")
        ttk.Label(panel, text="Image layer size").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=5, to=300, variable=state["image_size"], command=self.on_imported_image_size_changed).grid(row=6, column=0, sticky="ew")
        ttk.Label(panel, text="Image layer rotation").grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=-180, to=180, variable=state["image_rotation"], command=self.on_editor_layer_control_changed).grid(row=8, column=0, sticky="ew")

        ttk.Separator(panel).grid(row=9, column=0, sticky="ew", pady=10)
        ttk.Button(panel, text="Background Color", command=self.choose_editor_background_color).grid(row=10, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(panel, text="Background Image", command=self.choose_editor_background_image).grid(row=11, column=0, sticky="ew")

        ttk.Separator(panel).grid(row=12, column=0, sticky="ew", pady=10)
        ttk.Radiobutton(panel, text="Brush", value="brush", variable=tool_var).grid(row=13, column=0, sticky="w")
        ttk.Radiobutton(panel, text="Spray Paint", value="spray", variable=tool_var).grid(row=14, column=0, sticky="w")
        ttk.Radiobutton(panel, text="Text", value="text", variable=tool_var).grid(row=15, column=0, sticky="w")
        ttk.Radiobutton(panel, text="Remove BG Click", value="remove_bg", variable=tool_var).grid(row=16, column=0, sticky="w")
        ttk.Label(panel, text="BG remove tolerance").grid(row=17, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=5, to=120, variable=state["background_remove_tolerance"]).grid(row=18, column=0, sticky="ew")
        ttk.Button(panel, text="Auto Remove Image BG", command=self.auto_remove_imported_background).grid(row=19, column=0, sticky="ew", pady=(8, 4))
        ttk.Label(panel, text="Brush thickness").grid(row=20, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=1, to=120, variable=state["brush_size"]).grid(row=21, column=0, sticky="ew")
        ttk.Label(panel, text="Paint opacity").grid(row=22, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=1, to=100, variable=state["paint_opacity"]).grid(row=23, column=0, sticky="ew")
        ttk.Button(panel, text="Brush Color", command=self.choose_editor_brush_color).grid(row=24, column=0, sticky="ew", pady=(8, 4))

        ttk.Label(panel, text="Text").grid(row=25, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(panel, textvariable=text_var).grid(row=26, column=0, sticky="ew")
        ttk.Button(panel, text="Text Color", command=self.choose_editor_text_color).grid(row=27, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(panel, text="Text opacity").grid(row=28, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["text_opacity"], command=self.update_selected_text_from_controls).grid(row=29, column=0, sticky="ew")
        ttk.Label(panel, text="Text camouflage").grid(row=30, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["text_camouflage"], command=self.update_selected_text_from_controls).grid(row=31, column=0, sticky="ew")
        ttk.Checkbutton(panel, text="Text border", variable=state["text_border_enabled"], command=self.update_selected_text_from_controls).grid(row=32, column=0, sticky="w", pady=(8, 0))
        ttk.Label(panel, text="Text size").grid(row=33, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=8, to=300, variable=state["text_size"], command=self.update_selected_text_from_controls).grid(row=34, column=0, sticky="ew")
        ttk.Label(panel, text="Text thickness").grid(row=35, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=24, variable=state["text_thickness"], command=self.update_selected_text_from_controls).grid(row=36, column=0, sticky="ew")
        ttk.Label(panel, text="Text rotation").grid(row=37, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=-180, to=180, variable=state["text_rotation"], command=self.update_selected_text_from_controls).grid(row=38, column=0, sticky="ew")
        ttk.Label(panel, text="Word warp").grid(row=39, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=-100, to=100, variable=state["text_warp"], command=self.update_selected_text_from_controls).grid(row=40, column=0, sticky="ew")

        ttk.Separator(panel).grid(row=41, column=0, sticky="ew", pady=10)
        ttk.Button(panel, text="Undo", command=self.undo_editor_change).grid(row=42, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(panel, text="Delete Selected Text", command=self.delete_selected_text).grid(row=43, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(panel, text="Clear Paint/Text", command=self.clear_editor_paint).grid(row=44, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(panel, text="Apply Changes", command=self.apply_editor_to_frame).grid(row=45, column=0, sticky="ew")

        panel.columnconfigure(0, weight=1)
        canvas.bind("<Button-1>", self.on_editor_canvas_click)
        canvas.bind("<B1-Motion>", self.on_editor_canvas_drag)
        canvas.bind("<ButtonRelease-1>", self.finish_editor_action)
        canvas.bind("<Configure>", lambda _event: self.refresh_editor_preview())
        text_var.trace_add("write", lambda *_args: self.update_selected_text_from_controls())
        window.protocol("WM_DELETE_WINDOW", self.close_import_editor)
        self.refresh_editor_preview()

    def editor_canvas_to_image(self, event):
        state = self.editor_state
        if not state:
            return None
        ox, oy = state["preview_offset"]
        scale = state["preview_scale"]
        x = int((event.x - ox) / scale)
        y = int((event.y - oy) / scale)
        width, height = state["original"].size
        if x < 0 or y < 0 or x >= width or y >= height:
            return None
        return x, y

    def editor_snapshot(self):
        state = self.editor_state
        if not state:
            return None
        selected = state.get("selected_text")
        selected_index = None
        if selected in state["text_objects"]:
            selected_index = state["text_objects"].index(selected)
        return {
            "draw_layer": state["draw_layer"].copy(),
            "imported": state["imported"].copy(),
            "imported_content": state["imported_content"].copy(),
            "text_objects": [dict(text_obj) for text_obj in state["text_objects"]],
            "selected_index": selected_index,
            "background_image": state["background_image"].copy() if state["background_image"] is not None else None,
            "bg_color": state["bg_color"]["value"],
            "brush_color": state["brush_color"]["value"],
            "text_color": state["text_color"]["value"],
            "frame_opacity": state["frame_opacity"].get(),
            "image_opacity": state["image_opacity"].get(),
            "image_size": state["image_size"].get(),
            "image_rotation": state["image_rotation"].get(),
            "brush_size": state["brush_size"].get(),
            "paint_opacity": state["paint_opacity"].get(),
            "text_opacity": state["text_opacity"].get(),
            "text_camouflage": state["text_camouflage"].get(),
            "text_border_enabled": state["text_border_enabled"].get(),
            "text_size": state["text_size"].get(),
            "text_thickness": state["text_thickness"].get(),
            "text_rotation": state["text_rotation"].get(),
            "text_warp": state["text_warp"].get(),
            "text_value": state["text_var"].get(),
        }

    def push_editor_undo(self):
        state = self.editor_state
        if not state or state.get("is_restoring"):
            return
        snapshot = self.editor_snapshot()
        if snapshot:
            state["undo_stack"].append(snapshot)
            state["undo_stack"] = state["undo_stack"][-50:]

    def restore_editor_snapshot(self, snapshot):
        state = self.editor_state
        if not state or not snapshot:
            return
        state["is_restoring"] = True
        try:
            state["draw_layer"] = snapshot["draw_layer"].copy()
            state["imported"] = snapshot["imported"].copy()
            state["imported_content"] = snapshot["imported_content"].copy()
            state["text_objects"] = [dict(text_obj) for text_obj in snapshot["text_objects"]]
            selected_index = snapshot["selected_index"]
            state["selected_text"] = state["text_objects"][selected_index] if selected_index is not None and selected_index < len(state["text_objects"]) else None
            state["background_image"] = snapshot["background_image"].copy() if snapshot["background_image"] is not None else None
            state["bg_color"]["value"] = snapshot["bg_color"]
            state["brush_color"]["value"] = snapshot["brush_color"]
            state["text_color"]["value"] = snapshot["text_color"]
            state["frame_opacity"].set(snapshot["frame_opacity"])
            state["image_opacity"].set(snapshot["image_opacity"])
            state["image_size"].set(snapshot["image_size"])
            state["image_rotation"].set(snapshot["image_rotation"])
            state["brush_size"].set(snapshot["brush_size"])
            state["paint_opacity"].set(snapshot["paint_opacity"])
            state["text_opacity"].set(snapshot["text_opacity"])
            state["text_camouflage"].set(snapshot["text_camouflage"])
            state["text_border_enabled"].set(snapshot["text_border_enabled"])
            state["text_size"].set(snapshot["text_size"])
            state["text_thickness"].set(snapshot["text_thickness"])
            state["text_rotation"].set(snapshot["text_rotation"])
            state["text_warp"].set(snapshot["text_warp"])
            state["text_var"].set(snapshot["text_value"])
        finally:
            state["is_restoring"] = False
        self.refresh_editor_preview()

    def undo_editor_change(self):
        state = self.editor_state
        if not state or not state["undo_stack"]:
            return
        snapshot = state["undo_stack"].pop()
        self.restore_editor_snapshot(snapshot)

    def finish_editor_action(self, _event=None):
        state = self.editor_state
        if not state:
            return
        state["paint_undo_active"] = False
        state["text_drag_undo_active"] = False
        state["control_undo_active"] = False

    def get_editor_font(self, size):
        size = max(8, int(size))
        for path in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/segoeui.ttf")):
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.load_default()

    def render_text_object(self, text_obj):
        state = self.editor_state
        width, height = state["original"].size
        text = text_obj.get("text", "")
        if not text:
            return Image.new("RGBA", (width, height), (0, 0, 0, 0)), None

        font = self.get_editor_font(text_obj.get("size", 64))
        stroke_width = max(0, int(text_obj.get("thickness", 0))) if text_obj.get("border_enabled", False) else 0
        measure = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        measure_draw = ImageDraw.Draw(measure)
        bbox = measure_draw.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        text_width = max(1, bbox[2] - bbox[0])
        text_height = max(1, bbox[3] - bbox[1])
        padding = max(24, stroke_width * 4)
        fill = self.rgba_from_hex(text_obj.get("color", "#ffffff"), text_obj.get("opacity", 100))
        mask = Image.new("L", (text_width + padding * 2, text_height + padding * 2), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.multiline_text(
            (padding - bbox[0], padding - bbox[1]),
            text,
            font=font,
            fill=fill[3],
            stroke_width=stroke_width,
            stroke_fill=fill[3],
            spacing=max(2, int(text_obj.get("size", 64) * 0.18)),
        )
        camouflage = clamp(float(text_obj.get("camouflage", 0)), 0, 100) / 100
        if camouflage > 0:
            tile = Image.new("RGBA", mask.size, fill)
            tile.putalpha(mask)
        else:
            tile = Image.new("RGBA", mask.size, (0, 0, 0, 0))
            tile_draw = ImageDraw.Draw(tile)
            tile_draw.multiline_text(
                (padding - bbox[0], padding - bbox[1]),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, fill[3]),
                spacing=max(2, int(text_obj.get("size", 64) * 0.18)),
            )

        warp = clamp(float(text_obj.get("warp", 0)), -100, 100) / 100 * 0.65
        if abs(warp) > 0.01:
            x_shift = int(abs(warp) * mask.height)
            new_width = mask.width + x_shift
            offset = x_shift if warp < 0 else 0
            transform_args = (
                (new_width, mask.height),
                Image.Transform.AFFINE,
                (1, warp, -offset, 0, 1, 0),
            )
            mask = mask.transform(
                *transform_args,
                resample=Image.Resampling.BICUBIC,
            )
            tile = tile.transform(*transform_args, resample=Image.Resampling.BICUBIC)

        rotation = float(text_obj.get("rotation", 0))
        if abs(rotation) > 0.01:
            mask = mask.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
            tile = tile.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)

        x = int(text_obj.get("x", 0))
        y = int(text_obj.get("y", 0))
        if camouflage > 0:
            tile = self.camouflage_text_tile(mask, fill, camouflage, x, y)
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.paste(tile, (x, y), tile)
        return layer, (x, y, x + tile.width, y + tile.height)

    def camouflage_text_tile(self, mask, fill, camouflage, x, y):
        state = self.editor_state
        if not state:
            tile = Image.new("RGBA", mask.size, fill)
            tile.putalpha(mask)
            return tile

        base = self.compose_editor_base(include_draw_layer=True).convert("RGB")
        width, height = base.size
        tile_width, tile_height = mask.size
        x1 = max(0, min(width, x))
        y1 = max(0, min(height, y))
        x2 = max(x1, min(width, x + tile_width))
        y2 = max(y1, min(height, y + tile_height))
        if x1 >= width or y1 >= height:
            tile = Image.new("RGBA", mask.size, fill)
            tile.putalpha(mask)
            return tile

        pattern = Image.new("RGB", mask.size, fill[:3])
        crop = base.crop((x1, y1, x2, y2))
        pattern.paste(crop, (x1 - x, y1 - y))
        pattern = pattern.filter(ImageFilter.GaussianBlur(radius=max(2, min(mask.size) // 18)))

        mask_pixels = np.array(mask, dtype=np.float32)
        pattern_pixels = np.array(pattern, dtype=np.float32)
        visible = mask_pixels > 0
        if np.any(visible):
            ys, xs = np.nonzero(visible)
            sample_colors = []
            for dx, dy in ((0, 0), (-6, 0), (6, 0), (0, -6), (0, 6), (-10, -10), (10, -10), (-10, 10), (10, 10)):
                sx = np.clip(xs + dx, 0, tile_width - 1)
                sy = np.clip(ys + dy, 0, tile_height - 1)
                sample_colors.append(pattern_pixels[sy, sx])
            local_average = np.mean(sample_colors, axis=0)
            pattern_pixels[ys, xs] = local_average

        fill_pixels = np.zeros_like(pattern_pixels)
        fill_pixels[:, :] = fill[:3]
        blended = fill_pixels * (1.0 - camouflage) + pattern_pixels * camouflage
        alpha = np.clip(mask_pixels * (fill[3] / 255.0), 0, 255).astype(np.uint8)
        result = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
        result.putalpha(Image.fromarray(alpha, "L"))
        return result
    def find_text_at(self, point):
        state = self.editor_state
        if not state:
            return None
        x, y = point
        for text_obj in reversed(state["text_objects"]):
            _layer, bbox = self.render_text_object(text_obj)
            if bbox and bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return text_obj
        return None

    def sync_text_controls_from_selected(self):
        state = self.editor_state
        text_obj = state.get("selected_text") if state else None
        if not text_obj:
            return
        state["is_restoring"] = True
        try:
            state["text_var"].set(text_obj.get("text", ""))
            state["text_color"]["value"] = text_obj.get("color", "#ffffff")
            state["text_opacity"].set(text_obj.get("opacity", 100))
            state["text_camouflage"].set(text_obj.get("camouflage", 0))
            state["text_border_enabled"].set(text_obj.get("border_enabled", False))
            state["text_size"].set(text_obj.get("size", 64))
            state["text_thickness"].set(text_obj.get("thickness", 0))
            state["text_rotation"].set(text_obj.get("rotation", 0))
            state["text_warp"].set(text_obj.get("warp", 0))
        finally:
            state["is_restoring"] = False

    def update_selected_text_from_controls(self, _value=None):
        state = self.editor_state
        text_obj = state.get("selected_text") if state else None
        if not text_obj:
            return
        if not state["is_restoring"]:
            self.push_editor_undo()
        text_obj["text"] = state["text_var"].get()
        text_obj["color"] = state["text_color"]["value"]
        text_obj["opacity"] = state["text_opacity"].get()
        text_obj["camouflage"] = state["text_camouflage"].get()
        text_obj["border_enabled"] = state["text_border_enabled"].get()
        text_obj["size"] = state["text_size"].get()
        text_obj["thickness"] = state["text_thickness"].get()
        text_obj["rotation"] = state["text_rotation"].get()
        text_obj["warp"] = state["text_warp"].get()
        self.refresh_editor_preview()

    def on_editor_layer_control_changed(self, _value=None):
        state = self.editor_state
        if not state or state["is_restoring"]:
            return
        self.push_editor_undo()
        self.refresh_editor_preview()

    def on_imported_image_size_changed(self, _value=None):
        state = self.editor_state
        if not state or state["is_restoring"]:
            return
        self.push_editor_undo()
        state["imported"] = self.fit_image_to_frame(state["imported_content"].copy(), state["original"].size, state["image_size"].get())
        self.refresh_editor_preview()

    def draw_selected_text_box(self):
        state = self.editor_state
        state["duplicate_button_bbox"] = None
        text_obj = state.get("selected_text") if state else None
        if not text_obj:
            return
        _layer, bbox = self.render_text_object(text_obj)
        if not bbox:
            return
        ox, oy = state["preview_offset"]
        scale = state["preview_scale"]
        x1 = ox + bbox[0] * scale
        y1 = oy + bbox[1] * scale
        x2 = ox + bbox[2] * scale
        y2 = oy + bbox[3] * scale
        canvas = state["canvas"]
        canvas.create_rectangle(x1, y1, x2, y2, outline="#31d6ff", width=2, dash=(6, 4))
        handle = 5
        for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            canvas.create_rectangle(x - handle, y - handle, x + handle, y + handle, fill="#31d6ff", outline="#0b3a44")
        button_x1 = x1
        button_y2 = max(18, y1 - 6)
        button_y1 = max(0, button_y2 - 24)
        button_x2 = button_x1 + 84
        state["duplicate_button_bbox"] = (button_x1, button_y1, button_x2, button_y2)
        canvas.create_rectangle(button_x1, button_y1, button_x2, button_y2, fill="#151515", outline="#31d6ff", width=1)
        canvas.create_text((button_x1 + button_x2) / 2, (button_y1 + button_y2) / 2, text="Duplicate", fill="#ffffff", font=("Segoe UI", 9))

    def refresh_editor_preview(self):
        state = self.editor_state
        if not state:
            return
        canvas = state["canvas"]
        composed = self.compose_editor_image()
        canvas_width = max(1, canvas.winfo_width())
        canvas_height = max(1, canvas.winfo_height())
        preview = composed.copy()
        preview.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
        state["preview_scale"] = preview.width / composed.width
        state["preview_offset"] = ((canvas_width - preview.width) // 2, (canvas_height - preview.height) // 2)
        state["photo"] = ImageTk.PhotoImage(preview)
        canvas.delete("all")
        canvas.create_image(state["preview_offset"][0], state["preview_offset"][1], anchor="nw", image=state["photo"])
        self.draw_selected_text_box()

    def compose_editor_image(self):
        composed = self.compose_editor_base(include_draw_layer=True)
        for text_obj in self.editor_state["text_objects"]:
            text_layer, _bbox = self.render_text_object(text_obj)
            composed = Image.alpha_composite(composed, text_layer)
        return composed

    def compose_editor_base(self, include_draw_layer):
        state = self.editor_state
        width, height = state["original"].size
        background = Image.new("RGBA", (width, height), state["bg_color"]["value"])
        if state["background_image"] is not None:
            background = state["background_image"].copy().resize((width, height), Image.Resampling.LANCZOS)
        frame = state["original"].copy()
        frame = self.apply_layer_opacity(frame, state["frame_opacity"].get())
        imported = self.rotated_imported_image()
        imported = self.apply_layer_opacity(imported, state["image_opacity"].get())
        composed = Image.alpha_composite(background, frame)
        composed = Image.alpha_composite(composed, imported)
        if include_draw_layer:
            composed = Image.alpha_composite(composed, state["draw_layer"])
        return composed

    def apply_layer_opacity(self, image, opacity_percent):
        opacity = clamp(float(opacity_percent), 0, 100) / 100
        image = image.copy().convert("RGBA")
        alpha = np.array(image.getchannel("A"), dtype=np.float32)
        alpha = np.clip(alpha * opacity, 0, 255).astype(np.uint8)
        image.putalpha(Image.fromarray(alpha, mode="L"))
        return image

    def rotated_imported_image(self):
        state = self.editor_state
        width, height = state["original"].size
        imported = state["imported"].copy()
        rotation = float(state["image_rotation"].get())
        if abs(rotation) <= 0.01:
            return imported
        rotated = imported.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.paste(rotated, ((width - rotated.width) // 2, (height - rotated.height) // 2), rotated)
        return layer

    def choose_editor_background_color(self):
        state = self.editor_state
        if not state:
            return
        color = colorchooser.askcolor(color=state["bg_color"]["value"], title="Background Color")
        if color and color[1]:
            self.push_editor_undo()
            state["bg_color"]["value"] = color[1]
            self.refresh_editor_preview()

    def choose_editor_background_image(self):
        state = self.editor_state
        if not state:
            return
        path = filedialog.askopenfilename(
            title="Background Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.push_editor_undo()
            state["background_image"] = Image.open(path).convert("RGBA")
            self.refresh_editor_preview()
        except Exception:
            messagebox.showerror("Background Image", "Could not read that image.")

    def choose_editor_brush_color(self):
        state = self.editor_state
        if not state:
            return
        color = colorchooser.askcolor(color=state["brush_color"]["value"], title="Brush Color")
        if color and color[1]:
            state["brush_color"]["value"] = color[1]

    def choose_editor_text_color(self):
        state = self.editor_state
        if not state:
            return
        color = colorchooser.askcolor(color=state["text_color"]["value"], title="Text Color")
        if color and color[1]:
            self.push_editor_undo()
            state["is_restoring"] = True
            try:
                state["text_color"]["value"] = color[1]
                self.update_selected_text_from_controls()
            finally:
                state["is_restoring"] = False
            self.refresh_editor_preview()

    def rgba_from_hex(self, hex_color, opacity_percent):
        hex_color = hex_color.lstrip("#")
        rgb = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return (*rgb, int(clamp(opacity_percent, 0, 100) / 100 * 255))

    def remove_imported_background_at(self, point):
        state = self.editor_state
        if not state:
            return
        width, height = state["imported"].size
        x = clamp(point[0], 0, width - 1)
        y = clamp(point[1], 0, height - 1)
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        if pixels[y, x, 3] == 0:
            messagebox.showinfo("Remove BG Click", "Click on the visible background color inside the imported image.")
            return
        self.push_editor_undo()
        target = pixels[y, x, :3].astype(np.int16)
        rgb = pixels[:, :, :3].astype(np.int16)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        candidate = (distance <= tolerance) & (pixels[:, :, 3] > 0)
        mask = self.connected_background_mask(candidate, x, y)
        if not np.any(mask):
            self.refresh_editor_preview()
            return
        alpha = pixels[:, :, 3].copy()
        alpha[mask] = 0
        feather = (distance <= tolerance * 1.35) & (pixels[:, :, 3] > 0) & ~mask
        alpha[feather] = np.minimum(alpha[feather], 120)
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        self.refresh_editor_preview()

    def auto_remove_imported_background(self):
        state = self.editor_state
        if not state:
            return
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        height, width = pixels.shape[:2]
        alpha = pixels[:, :, 3]
        visible = alpha > 0
        if not np.any(visible):
            return
        self.push_editor_undo()
        rgb = pixels[:, :, :3].astype(np.int16)
        edge_visible = np.zeros((height, width), dtype=bool)
        edge_visible[0, :] = visible[0, :]
        edge_visible[-1, :] = visible[-1, :]
        edge_visible[:, 0] = visible[:, 0]
        edge_visible[:, -1] = visible[:, -1]
        if np.any(edge_visible):
            samples = rgb[edge_visible]
        else:
            ys, xs = np.nonzero(visible)
            min_x, max_x = xs.min(), xs.max()
            min_y, max_y = ys.min(), ys.max()
            border = np.zeros((height, width), dtype=bool)
            border[min_y, min_x:max_x + 1] = True
            border[max_y, min_x:max_x + 1] = True
            border[min_y:max_y + 1, min_x] = True
            border[min_y:max_y + 1, max_x] = True
            samples = rgb[border & visible]
        target = np.median(samples, axis=0)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        candidate = (distance <= tolerance) & visible
        seed_mask = edge_visible & candidate
        if not np.any(seed_mask):
            seed_mask = candidate
        mask = self.connected_background_mask(candidate, None, None, seed_mask)
        alpha = alpha.copy()
        alpha[mask] = 0
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        self.refresh_editor_preview()
    def connected_background_mask(self, candidate_mask, start_x=None, start_y=None, seed_mask=None):
        height, width = candidate_mask.shape
        visited = np.zeros((height, width), dtype=bool)
        stack = []
        if seed_mask is not None:
            ys, xs = np.nonzero(seed_mask)
            stack.extend(zip(xs.tolist(), ys.tolist()))
        elif start_x is not None and start_y is not None and candidate_mask[start_y, start_x]:
            stack.append((start_x, start_y))
        while stack:
            x, y = stack.pop()
            if x < 0 or y < 0 or x >= width or y >= height or visited[y, x] or not candidate_mask[y, x]:
                continue
            visited[y, x] = True
            stack.append((x + 1, y))
            stack.append((x - 1, y))
            stack.append((x, y + 1))
            stack.append((x, y - 1))
        return visited

    def visible_image_content(self, image):
        bbox = image.getchannel("A").getbbox()
        if not bbox:
            return image
        return image.crop(bbox)

    def current_content_scale_percent(self, content, frame_size):
        frame_width, frame_height = frame_size
        content_width, content_height = content.size
        if content_width <= 0 or content_height <= 0:
            return 100.0
        fit_scale = min(frame_width / content_width, frame_height / content_height)
        if fit_scale <= 0:
            return 100.0
        return clamp(100.0 / fit_scale, 5.0, 300.0)

    def on_editor_canvas_click(self, event):
        state = self.editor_state
        point = self.editor_canvas_to_image(event)
        if not state:
            return
        if state["tool_var"].get() == "text" and self.click_in_duplicate_button(event.x, event.y):
            self.duplicate_selected_text()
            return
        if point is None:
            return
        if state["tool_var"].get() == "text":
            selected = self.find_text_at(point)
            if selected:
                state["selected_text"] = selected
                self.sync_text_controls_from_selected()
            else:
                self.push_editor_undo()
                selected = {
                    "text": state["text_var"].get(),
                    "x": point[0],
                    "y": point[1],
                    "color": state["text_color"]["value"],
                    "opacity": state["text_opacity"].get(),
                    "camouflage": state["text_camouflage"].get(),
                    "border_enabled": state["text_border_enabled"].get(),
                    "size": state["text_size"].get(),
                    "thickness": state["text_thickness"].get(),
                    "rotation": state["text_rotation"].get(),
                    "warp": state["text_warp"].get(),
                }
                state["text_objects"].append(selected)
                state["selected_text"] = selected
            self.refresh_editor_preview()
        elif state["tool_var"].get() == "remove_bg":
            self.remove_imported_background_at(point)
        else:
            state["selected_text"] = None
            self.paint_editor_point(point)

    def click_in_duplicate_button(self, x, y):
        state = self.editor_state
        bbox = state.get("duplicate_button_bbox") if state else None
        if not bbox:
            return False
        return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]

    def duplicate_selected_text(self):
        state = self.editor_state
        selected = state.get("selected_text") if state else None
        if not selected:
            return
        self.push_editor_undo()
        duplicate = dict(selected)
        duplicate["x"] = int(duplicate.get("x", 0)) + 32
        duplicate["y"] = int(duplicate.get("y", 0)) + 32
        state["text_objects"].append(duplicate)
        state["selected_text"] = duplicate
        self.sync_text_controls_from_selected()
        self.refresh_editor_preview()

    def on_editor_canvas_drag(self, event):
        state = self.editor_state
        point = self.editor_canvas_to_image(event)
        if not state or point is None:
            return
        if state["tool_var"].get() == "text":
            selected = state.get("selected_text")
            if selected and self.find_text_at(point) is selected:
                if not state["text_drag_undo_active"]:
                    self.push_editor_undo()
                    state["text_drag_undo_active"] = True
                selected["x"], selected["y"] = point
                self.refresh_editor_preview()
            return
        self.paint_editor_point(point)

    def paint_editor_point(self, point):
        state = self.editor_state
        if not state["paint_undo_active"]:
            self.push_editor_undo()
            state["paint_undo_active"] = True
        draw = ImageDraw.Draw(state["draw_layer"])
        size = max(1, int(state["brush_size"].get()))
        color = self.rgba_from_hex(state["brush_color"]["value"], state["paint_opacity"].get())
        x, y = point
        if state["tool_var"].get() == "spray":
            radius = size // 2
            drops = max(12, size * 2)
            for _ in range(drops):
                dx = random.randint(-radius, radius)
                dy = random.randint(-radius, radius)
                if dx * dx + dy * dy <= radius * radius:
                    dot = max(1, size // 12)
                    draw.ellipse([x + dx - dot, y + dy - dot, x + dx + dot, y + dy + dot], fill=color)
        else:
            radius = size // 2
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
        self.refresh_editor_preview()

    def clear_editor_paint(self):
        state = self.editor_state
        if not state:
            return
        self.push_editor_undo()
        state["draw_layer"] = Image.new("RGBA", state["original"].size, (0, 0, 0, 0))
        state["text_objects"] = []
        state["selected_text"] = None
        self.refresh_editor_preview()

    def delete_selected_text(self):
        state = self.editor_state
        if not state or not state.get("selected_text"):
            return
        self.push_editor_undo()
        selected = state["selected_text"]
        state["text_objects"] = [text_obj for text_obj in state["text_objects"] if text_obj is not selected]
        state["selected_text"] = None
        self.refresh_editor_preview()

    def close_import_editor(self):
        if not self.editor_state:
            return
        answer = messagebox.askyesnocancel("Edit Frame", "Apply these changes to the selected video frame before closing?")
        if answer is None:
            return
        if answer:
            self.apply_editor_to_frame()
            return
        self.editor_state["window"].destroy()
        self.editor_state = None

    def apply_editor_to_frame(self):
        if not self.state or not self.editor_state:
            return
        output_frame = self.editor_state.get("editor_output_frame", self.state.current_output_frame)
        edit_dir = self.state.video_path.with_suffix("").parent / ".frame_edits"
        edit_dir.mkdir(exist_ok=True)
        output = edit_dir / f"{self.state.video_path.stem}_frame_{output_frame}.png"
        self.compose_editor_image().convert("RGB").save(output)
        self.repeat_image_path = output
        self.repeat_editor_template = self.editor_template_from_state(self.editor_state)
        self.state.edits[str(output_frame)] = str(output)
        self.state.current_output_frame = output_frame
        self.show_current_frame()
        self.editor_state["window"].destroy()
        self.editor_state = None
        self.status_var.set(f"Applied edited image to frame {output_frame}. Click Save Edits to keep this change.")

    def editor_template_from_state(self, state):
        return {
            "size": state["original"].size,
            "imported": state["imported"].copy(),
            "background_image": state["background_image"].copy() if state["background_image"] is not None else None,
            "draw_layer": state["draw_layer"].copy(),
            "text_objects": [dict(text_obj) for text_obj in state["text_objects"]],
            "bg_color": state["bg_color"]["value"],
            "frame_opacity": state["frame_opacity"].get(),
            "image_opacity": state["image_opacity"].get(),
            "image_rotation": state["image_rotation"].get(),
        }

    def compose_editor_template_image(self, template, output_frame, cap=None, frame_cache=None):
        source_frame = self.state.source_frame_for_output(output_frame)
        frame = self.frame_from_cache_or_video(source_frame, frame_cache, cap)
        if frame is None:
            return None
        original = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        width, height = original.size

        imported = template["imported"].copy()
        if imported.size != original.size:
            imported = imported.resize(original.size, Image.Resampling.LANCZOS)
        draw_layer = template["draw_layer"].copy()
        if draw_layer.size != original.size:
            draw_layer = draw_layer.resize(original.size, Image.Resampling.LANCZOS)

        temp_state = {
            "original": original,
            "imported": imported,
            "background_image": template["background_image"].copy() if template["background_image"] is not None else None,
            "draw_layer": draw_layer,
            "text_objects": [dict(text_obj) for text_obj in template["text_objects"]],
            "frame_opacity": FixedValue(template["frame_opacity"]),
            "image_opacity": FixedValue(template["image_opacity"]),
            "image_rotation": FixedValue(template["image_rotation"]),
            "bg_color": {"value": template["bg_color"]},
        }
        previous_editor_state = self.editor_state
        try:
            self.editor_state = temp_state
            return self.compose_editor_image()
        finally:
            self.editor_state = previous_editor_state

    def clear_frame(self):
        if not self.state:
            return
        key = str(self.state.current_output_frame)
        if key in self.state.edits:
            del self.state.edits[key]
            self.status_var.set("Frame cleared. Click Save Edits to keep this change.")
        self.show_current_frame()

    def add_music_track(self):
        if not self.state:
            return
        path = filedialog.askopenfilename(
            title="Choose Audio Track",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"),
                ("Video/audio files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        track = AudioTrack(path=str(Path(path)), duration=self.media_duration_seconds(path))
        self.state.audio_tracks.append(track)
        self.state.music_path = track.path
        self.state.music_volume = track.volume
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Audio track added. Click Save Edits to keep this change.")
        self.open_audio_editor()

    def clear_music_track(self):
        if not self.state:
            return
        self.state.audio_tracks.clear()
        self.state.music_path = ""
        self.state.music_tone_match = False
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Audio tracks cleared. Click Save Edits to keep this change.")

    def on_music_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.music_volume = clamp(self.music_volume_var.get() / 100.0, 0.0, 2.0)
        if self.state.audio_tracks:
            self.state.audio_tracks[-1].volume = self.state.music_volume
        self.sync_music_controls()

    def on_source_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.source_volume = clamp(self.source_volume_var.get() / 100.0, 0.0, 2.0)
        self.sync_music_controls()

    def open_audio_editor(self):
        if not self.state:
            return
        if self.audio_editor_window is not None and self.audio_editor_window.winfo_exists():
            self.audio_editor_window.destroy()
        window = tk.Toplevel(self)
        self.audio_editor_window = window
        window.title("Audio Editor")
        window.geometry("720x620")
        window.minsize(620, 460)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas, padding=12)
        body.columnconfigure(0, weight=1)
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        ttk.Label(body, text="Main track audio", font=("", 11, "bold")).grid(row=0, column=0, sticky="w")
        main_volume = tk.DoubleVar(value=self.state.source_volume * 100.0)
        ttk.Label(body, text="Main track volume").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            body,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=main_volume,
            command=lambda _value: self.set_main_audio_volume(main_volume.get()),
        ).grid(row=2, column=0, sticky="ew", pady=(2, 8))
        tone_match = tk.BooleanVar(value=self.state.music_tone_match)
        ttk.Checkbutton(
            body,
            text="Key-match added tracks to the main soundtrack at export",
            variable=tone_match,
            command=lambda: self.set_audio_tone_match(tone_match.get()),
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        first_audio_mask = tk.BooleanVar(value=self.state.first_audio_as_main_mask)
        ttk.Checkbutton(
            body,
            text="If movie has no audio, use first added track as the main masking track",
            variable=first_audio_mask,
            command=lambda: self.set_first_audio_as_main_mask(first_audio_mask.get()),
        ).grid(row=4, column=0, sticky="w", pady=(0, 8))

        button_row = ttk.Frame(body)
        button_row.grid(row=5, column=0, sticky="ew", pady=(2, 10))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        ttk.Button(button_row, text="Add Audio Track", command=self.add_music_track).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(button_row, text="Clear All Tracks", command=self.clear_music_track).grid(row=0, column=1, sticky="ew")

        ttk.Separator(body).grid(row=6, column=0, sticky="ew", pady=8)
        if not self.state.audio_tracks:
            ttk.Label(body, text="No added audio tracks.").grid(row=7, column=0, sticky="w")
        else:
            for index, track in enumerate(self.state.audio_tracks):
                self.add_audio_track_row(body, index, track, 7 + index)

        ttk.Button(body, text="Close", command=window.destroy).grid(row=1000, column=0, sticky="ew", pady=(12, 0))

    def add_audio_track_row(self, parent, index, track, row):
        frame = ttk.LabelFrame(parent, text=f"Track {index + 1}: {track.name}", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        detail = (
            f"Length: {self.format_seconds(track.duration)} | Start: {self.format_seconds(track.start_time)} | "
            f"Volume: {track.volume * 100:.0f}% | Speed: {track.speed:.2f}x\n"
            f"Repeat: {'on' if track.repeat else 'off'} | Every: "
            f"{'track length' if track.repeat_every <= 0 else self.format_seconds(track.repeat_every)} | "
            f"Count: {'to end' if track.repeat_count <= 0 else track.repeat_count}\n"
            f"Track masking: {'on' if track.masking else 'off'} | Below main: {'on' if track.duck_below_main else 'off'}"
        )
        ttk.Label(frame, text=detail, justify=tk.LEFT).grid(row=0, column=0, sticky="w")
        actions = ttk.Frame(frame)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Edit Track", command=lambda i=index: self.open_audio_track_settings(i)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Remove Track", command=lambda i=index: self.remove_audio_track(i)).grid(row=0, column=1, sticky="ew")

    def open_audio_track_settings(self, index):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        track = self.state.audio_tracks[index]
        window = tk.Toplevel(self)
        window.title(f"Audio Track {index + 1}")
        window.geometry("560x600")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas, padding=12)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text=track.name, font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text=f"Length: {self.format_seconds(track.duration)}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        volume_var = tk.DoubleVar(value=track.volume * 100.0)
        start_var = tk.StringVar(value=f"{track.start_time:.3f}")
        repeat_var = tk.BooleanVar(value=track.repeat)
        repeat_every_var = tk.StringVar(value="0" if track.repeat_every <= 0 else f"{track.repeat_every:.3f}")
        repeat_count_var = tk.StringVar(value=str(track.repeat_count))
        speed_var = tk.DoubleVar(value=track.speed * 100.0)
        masking_var = tk.BooleanVar(value=track.masking)
        duck_var = tk.BooleanVar(value=track.duck_below_main)
        speed_label_var = tk.StringVar(value=f"Track speed: {track.speed:.2f}x")

        ttk.Label(body, text="Track volume").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Scale(body, from_=0, to=200, orient=tk.HORIZONTAL, variable=volume_var).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        ttk.Label(body, text="Start time in movie seconds").grid(row=4, column=0, sticky="w")
        ttk.Entry(body, textvariable=start_var).grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(body, text="Repeat this track", variable=repeat_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(body, text="Repeat every seconds (0 = track length after speed)").grid(row=6, column=0, sticky="w")
        ttk.Entry(body, textvariable=repeat_every_var).grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Repeat count (0 = until movie ends)").grid(row=7, column=0, sticky="w")
        ttk.Entry(body, textvariable=repeat_count_var).grid(row=7, column=1, sticky="ew", pady=3)
        ttk.Label(body, textvariable=speed_label_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Scale(
            body,
            from_=20,
            to=500,
            orient=tk.HORIZONTAL,
            variable=speed_var,
            command=lambda value: speed_label_var.set(f"Track speed: {float(value) / 100.0:.2f}x"),
        ).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        ttk.Checkbutton(body, text="Track masking: compress peaks and limit loud spikes", variable=masking_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(body, text="Keep this track dynamically below the main track", variable=duck_var).grid(row=11, column=0, columnspan=2, sticky="w", pady=3)

        buttons = ttk.Frame(body)
        buttons.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Cancel", command=window.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            buttons,
            text="Apply",
            command=lambda: self.apply_audio_track_settings(
                window,
                index,
                volume_var,
                start_var,
                repeat_var,
                repeat_every_var,
                repeat_count_var,
                speed_var,
                masking_var,
                duck_var,
            ),
        ).grid(row=0, column=1, sticky="ew")

    def apply_audio_track_settings(self, window, index, volume_var, start_var, repeat_var, repeat_every_var, repeat_count_var, speed_var, masking_var, duck_var):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        track = self.state.audio_tracks[index]
        try:
            track.volume = clamp(volume_var.get() / 100.0, 0.0, 2.0)
            track.start_time = max(0.0, float(start_var.get() or 0))
            track.repeat = bool(repeat_var.get())
            track.repeat_every = max(0.0, float(repeat_every_var.get() or 0))
            track.repeat_count = max(0, int(float(repeat_count_var.get() or 0)))
            track.speed = clamp(speed_var.get() / 100.0, 0.2, 5.0)
            track.masking = bool(masking_var.get())
            track.duck_below_main = bool(duck_var.get())
        except ValueError:
            messagebox.showerror("Audio Track", "Use numbers for start time, repeat timing, repeat count, and speed.")
            return
        self.state.music_path = track.path
        self.state.music_volume = track.volume
        self.sync_music_controls()
        self.update_info()
        window.destroy()
        self.open_audio_editor()
        self.status_var.set("Audio track updated. Click Save Edits to keep this change.")

    def remove_audio_track(self, index):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        del self.state.audio_tracks[index]
        self.state.music_path = self.state.audio_tracks[-1].path if self.state.audio_tracks else ""
        self.sync_music_controls()
        self.update_info()
        self.open_audio_editor()
        self.status_var.set("Audio track removed. Click Save Edits to keep this change.")

    def set_main_audio_volume(self, value):
        if not self.state:
            return
        self.state.source_volume = clamp(float(value) / 100.0, 0.0, 2.0)
        self.source_volume_var.set(round(self.state.source_volume * 100.0, 1))
        self.sync_music_controls()

    def set_audio_tone_match(self, enabled):
        if not self.state:
            return
        self.state.music_tone_match = bool(enabled)
        self.music_tone_var.set(self.state.music_tone_match)
        self.sync_music_controls()

    def set_first_audio_as_main_mask(self, enabled):
        if not self.state:
            return
        self.state.first_audio_as_main_mask = bool(enabled)
        self.first_audio_mask_var.set(self.state.first_audio_as_main_mask)
        self.sync_music_controls()

    def media_duration_seconds(self, path):
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=high_priority_subprocess_flags(),
            )
            for line in result.stderr.splitlines():
                if "Duration:" in line:
                    text = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                    hours, minutes, seconds = text.split(":")
                    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:
            pass
        return 0.0

    def format_seconds(self, seconds):
        seconds = max(0.0, float(seconds or 0.0))
        minutes = int(seconds // 60)
        remain = int(round(seconds - minutes * 60))
        return f"{minutes}:{remain:02d}"

    def on_color_blend_changed(self, _value=None):
        if not self.state:
            return
        self.state.frame_color_blend = bool(self.color_blend_var.get())
        self.state.frame_color_blend_strength = clamp(self.color_blend_strength_var.get() / 100.0, 0.0, 1.0)
        self.state.frame_frequency_blend_strength = clamp(self.frequency_blend_strength_var.get() / 100.0, 0.0, 1.0)
        self.show_current_frame()

    def apply_tone_match_preset(self):
        if not self.state:
            return
        if not self.state.audio_tracks:
            messagebox.showinfo("Tone Match", "Add an audio track first.")
            return
        for track in self.state.audio_tracks:
            track.volume = 0.5
            track.masking = True
            track.duck_below_main = True
        self.state.music_volume = 0.5
        self.state.music_tone_match = True
        self.sync_music_controls()
        self.status_var.set("Tone match preset enabled, track masking enabled, and added tracks set to 50%. Click Save Edits to keep this change.")

    def export_video(self):
        if not self.state or self.exporting:
            return
        self.stop_playback()
        output = filedialog.asksaveasfilename(
            title="Export Video",
            defaultextension=".mp4",
            initialfile=f"{self.state.video_path.stem}_quad.mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if not output:
            return
        self.exporting = True
        self.open_button.configure(state=tk.DISABLED)
        self._set_controls_enabled(False)
        self.progress.configure(value=0, maximum=self.state.output_frame_count)
        thread = threading.Thread(target=self._export_worker, args=(Path(output),), daemon=True)
        thread.start()

    def select_video_encoder(self, ffmpeg):
        for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
            if self.test_video_encoder(ffmpeg, encoder):
                return encoder
        return "libx264"

    def test_video_encoder(self, ffmpeg, encoder):
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:rate=1",
            "-frames:v",
            "1",
            *encoder_options(encoder),
            "-f",
            "null",
            "-",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=high_priority_subprocess_flags(),
            )
            return True
        except Exception:
            return False

    def _export_worker(self, output_path):
        best_effort_raise_process_priority()
        cap = None
        context_cap = None
        process = None
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            encoder = self.select_video_encoder(ffmpeg)
            self.after(0, self.status_var.set, f"Exporting with {encoder} encoder...")
            cmd = self.build_ffmpeg_command(ffmpeg, output_path, encoder)
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                creationflags=high_priority_subprocess_flags(),
            )

            replacement_cache = self.preload_replacement_images()
            source_cache = None
            if self.source_frame_cache_bytes(self.state.frame_count) <= SOURCE_FRAME_CACHE_LIMIT_BYTES:
                source_cache = self.preload_source_frames(range(self.state.frame_count), "Export")

            context_preload = None
            if source_cache is None and self.state.frame_color_blend:
                context_indices = []
                for output_frame_text in self.state.edits:
                    try:
                        output_frame = int(output_frame_text)
                    except ValueError:
                        continue
                    previous_output = max(0, output_frame - 1)
                    next_output = min(self.state.output_frame_count - 1, output_frame + 1)
                    context_indices.extend(
                        (
                            self.state.source_frame_for_output(previous_output),
                            self.state.source_frame_for_output(next_output),
                        )
                    )
                context_preload = self.preload_source_frames(context_indices, "Export replacements")

            cap = cv2.VideoCapture(str(self.state.video_path))
            context_cap = cv2.VideoCapture(str(self.state.video_path))
            context_cache = {}
            current_source_frame = None
            frame = None

            def cached_context_frame(frame_index):
                frame_index = clamp(frame_index, 0, self.state.frame_count - 1)
                if source_cache is not None and frame_index in source_cache:
                    return source_cache[frame_index]
                if context_preload is not None and frame_index in context_preload:
                    return context_preload[frame_index]
                cached = context_cache.get(frame_index)
                if cached is None:
                    cached = self.read_frame_from_video(frame_index, context_cap)
                    context_cache[frame_index] = cached
                    if len(context_cache) > 256:
                        context_cache.pop(next(iter(context_cache)))
                return cached

            for output_frame in range(self.state.output_frame_count):
                source_frame = self.state.source_frame_for_output(output_frame)
                if source_frame != current_source_frame:
                    if source_cache is not None and source_frame in source_cache:
                        frame = source_cache[source_frame]
                        ok = True
                    elif current_source_frame is not None and source_frame == current_source_frame + 1:
                        ok, frame = cap.read()
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                        ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(f"Could not read source frame {source_frame} while exporting output frame {output_frame}.")
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(output_frame, override, cached_context_frame, replacement_cache)
                else:
                    out_frame = frame
                process.stdin.write(np.ascontiguousarray(out_frame).tobytes())
                if output_frame % 20 == 0:
                    self.after(0, self.progress.configure, {"value": output_frame + 1})
                    self.after(
                        0,
                        self.status_var.set,
                        f"Exporting frame {output_frame + 1} of {self.state.output_frame_count} with {encoder}...",
                    )

            process.stdin.close()
            process.stdin = None
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                error_text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
                raise RuntimeError(error_text.strip() or f"FFmpeg failed with exit code {process.returncode}.")
            self.after(0, self._export_done, output_path, None)
        except Exception as exc:
            self.after(0, self._export_done, output_path, exc)
        finally:
            if cap is not None:
                cap.release()
            if context_cap is not None:
                context_cap.release()
            if process is not None and process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass
    def build_ffmpeg_command(self, ffmpeg, output_path, encoder):
        video_input = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s:v",
            f"{self.state.width}x{self.state.height}",
            "-r",
            f"{self.state.export_fps:.6f}",
            "-i",
            "pipe:0",
        ]
        video_output = encoder_options(encoder)
        audio_tracks = [track for track in self.state.audio_tracks if track.path and Path(track.path).exists()]
        has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
        if not audio_tracks:
            if has_source_audio and abs(self.state.source_volume - 1.0) > 0.001:
                return [
                    *video_input,
                    "-i",
                    str(self.state.video_path),
                    "-filter_complex",
                    f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[aout]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    *video_output,
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(output_path),
                ]
            return [
                *video_input,
                "-i",
                str(self.state.video_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                *video_output,
                "-c:a",
                "aac",
                "-shortest",
                str(output_path),
            ]

        cmd = [*video_input, "-i", str(self.state.video_path)]
        for track in audio_tracks:
            cmd.extend(["-i", track.path])

        use_first_track_as_main = (not has_source_audio) and self.state.first_audio_as_main_mask and bool(audio_tracks)
        main_track = audio_tracks[0] if use_first_track_as_main else None
        export_tracks = audio_tracks[1:] if use_first_track_as_main else audio_tracks

        source_key = None
        if self.state.music_tone_match:
            if has_source_audio:
                self.after(0, self.status_var.set, "Analyzing audio keys...")
                source_key = analyze_audio_key(ffmpeg, self.state.video_path)
            elif main_track is not None:
                self.after(0, self.status_var.set, "Analyzing first audio track key...")
                source_key = analyze_audio_key(ffmpeg, main_track.path)

        filter_parts = []
        main_label = None
        generated_offset = 0
        if has_source_audio:
            filter_parts.append(f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[maina]")
            main_label = "[maina]"
        elif main_track is not None:
            main_labels = self.add_audio_track_filters(
                filter_parts,
                input_index=2,
                track=main_track,
                semitone_shift=0,
                label_offset=generated_offset,
            )
            generated_offset += max(1, len(main_labels))
            main_label = self.mix_audio_labels(filter_parts, main_labels, "firstmain")

        normal_added = []
        ducked_added = []
        status_lines = [f"Audio mix: {len(audio_tracks)} added track(s)"]
        if main_track is not None:
            status_lines.append(f"Main masking track: {main_track.name}")
        for index, track in enumerate(export_tracks):
            semitone_shift = 0
            if source_key is not None:
                track_key = analyze_audio_key(ffmpeg, track.path)
                semitone_shift = shortest_semitone_shift(track_key["pc"], source_key["pc"])
                status_lines.append(
                    f"{track.name}: {key_label(track_key)} to {key_label(source_key)} ({semitone_shift:+d} semitones)"
                )
            labels = self.add_audio_track_filters(
                filter_parts,
                input_index=index + (3 if main_track is not None else 2),
                track=track,
                semitone_shift=semitone_shift,
                label_offset=generated_offset,
            )
            generated_offset += max(1, len(labels))
            if track.duck_below_main and has_source_audio:
                ducked_added.extend(labels)
            else:
                normal_added.extend(labels)

        self.after(0, self.status_var.set, "\n".join(status_lines))
        final_inputs = []
        main_mix_label = main_label
        main_sidechain_label = main_label
        if ducked_added and main_label:
            filter_parts.append(f"{main_label}asplit=2[mainmix][mainside]")
            main_mix_label = "[mainmix]"
            main_sidechain_label = "[mainside]"
        if main_mix_label:
            final_inputs.append(main_mix_label)
        if ducked_added:
            duck_mix = self.mix_audio_labels(filter_parts, ducked_added, "duckmix")
            if main_sidechain_label:
                filter_parts.append(f"{duck_mix}{main_sidechain_label}sidechaincompress=threshold=0.08:ratio=8:attack=20:release=250[ducked]")
                final_inputs.append("[ducked]")
            else:
                final_inputs.append(duck_mix)
        final_inputs.extend(normal_added)

        if not final_inputs:
            return [*video_input, "-map", "0:v:0", *video_output, "-t", f"{self.state.duration:.6f}", str(output_path)]
        audio_out = self.mix_audio_labels(filter_parts, final_inputs, "aout")
        if audio_out != "[aout]":
            filter_parts.append(f"{audio_out}anull[aout]")

        return [
            *cmd,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            *video_output,
            "-c:a",
            "aac",
            "-t",
            f"{self.state.duration:.6f}",
            str(output_path),
        ]

    def add_audio_track_filters(self, filter_parts, input_index, track, semitone_shift, label_offset):
        labels = []
        speed = clamp(track.speed, 0.2, 5.0)
        source_duration = track.duration or self.media_duration_seconds(track.path) or self.state.duration
        adjusted_duration = source_duration / speed if speed else source_duration
        repeat_every = track.repeat_every if track.repeat_every > 0 else adjusted_duration
        occurrences = 1
        if track.repeat:
            occurrences = track.repeat_count if track.repeat_count > 0 else int(np.ceil(max(0.0, self.state.duration - track.start_time) / max(0.1, repeat_every)))
        occurrences = clamp(occurrences, 1, 64)
        split_labels = []
        if occurrences > 1:
            split = f"[{input_index}:a:0]asplit={occurrences}"
            for repeat_index in range(occurrences):
                label = f"[atr{label_offset}_{repeat_index}_src]"
                split += label
                split_labels.append(label)
            filter_parts.append(split)
        for repeat_index in range(occurrences):
            delay = track.start_time + repeat_index * repeat_every
            if delay >= self.state.duration:
                break
            remaining = max(0.01, self.state.duration - delay)
            trim_seconds = max(0.01, min(source_duration, remaining * speed))
            input_label = split_labels[repeat_index] if occurrences > 1 else f"[{input_index}:a:0]"
            output_label = f"[atr{label_offset}_{repeat_index}]"
            chain = (
                f"{input_label}atrim=0:{trim_seconds:.6f},asetpts=PTS-STARTPTS,aresample=44100,"
                f"{self.ffmpeg_speed_filter(speed)}"
                f"{ffmpeg_pitch_filter(semitone_shift)}"
                f"volume={track.volume:.3f}"
            )
            if track.masking:
                chain += ",acompressor=threshold=0.18:ratio=6:attack=5:release=120,alimiter=limit=0.90"
            delay_ms = max(0, int(round(delay * 1000)))
            chain += f",adelay={delay_ms}|{delay_ms}{output_label}"
            filter_parts.append(chain)
            labels.append(output_label)
        return labels

    def mix_audio_labels(self, filter_parts, labels, output_name):
        labels = [label for label in labels if label]
        if not labels:
            return ""
        if len(labels) == 1:
            if output_name == "aout":
                filter_parts.append(f"{labels[0]}alimiter=limit=0.95[aout]")
                return "[aout]"
            return labels[0]
        joined = "".join(labels)
        filter_parts.append(
            f"{joined}amix=inputs={len(labels)}:duration=longest:dropout_transition=0,alimiter=limit=0.95[{output_name}]"
        )
        return f"[{output_name}]"

    def ffmpeg_speed_filter(self, speed):
        parts = []
        remaining = clamp(speed, 0.2, 5.0)
        while remaining > 2.0:
            parts.append("atempo=2.000000")
            remaining /= 2.0
        while remaining < 0.5:
            parts.append("atempo=0.500000")
            remaining /= 0.5
        if abs(remaining - 1.0) > 0.001:
            parts.append(f"atempo={remaining:.6f}")
        return ",".join(parts) + ("," if parts else "")

    def source_has_audio(self, ffmpeg, media_path):
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(media_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return "Audio:" in result.stderr

    def _export_done(self, output_path, error):
        self.exporting = False
        self.replacing_frames = False
        self.open_button.configure(state=tk.NORMAL)
        self._set_controls_enabled(True)
        self.progress.configure(value=0)
        if error:
            self.status_var.set("Export failed.")
            messagebox.showerror("Export Video", str(error))
        else:
            self.status_var.set(f"Exported {output_path}.")
            messagebox.showinfo("Export Video", f"Saved:\n{output_path}")


if __name__ == "__main__":
    app = MovieQuadEditor()
    app.mainloop()
