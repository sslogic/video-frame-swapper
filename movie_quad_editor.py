import json
import random
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter as tk

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk


SLOT_COUNT = 4
HIGH_FPS_TARGET = 120.0
PREVIEW_MAX = (960, 540)
TIMELINE_HEIGHT = 86
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
ANALYSIS_SAMPLE_RATE = 22050
ANALYSIS_SECONDS = 90
APP_DIR = Path(__file__).resolve().parent
RECENT_PROJECTS_PATH = APP_DIR / "recent_projects.json"


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
        self.playing = False
        self.play_after_id = None
        self.video_controls = []
        self.imported_image_path = None
        self.imported_image = None
        self.editor_state = None
        self.recent_projects = load_recent_projects()
        self.music_volume_var = tk.DoubleVar(value=50.0)
        self.source_volume_var = tk.DoubleVar(value=100.0)
        self.music_label_var = tk.StringVar(value="No music track")
        self.music_tone_var = tk.BooleanVar(value=False)
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
        topbar.columnconfigure(7, weight=1)

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

        self.video_label = ttk.Label(topbar, text="No video loaded")
        self.video_label.grid(row=0, column=6, columnspan=2, sticky="w")

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

        controls = ttk.Frame(main, padding=10)
        controls.columnconfigure(0, weight=1)
        main.add(controls, weight=2)

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
        self.edit_image_button = ttk.Button(edit_row, text="Edit Imported", command=self.open_import_editor)
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

        ttk.Label(controls, text="Extra Music Track").grid(row=13, column=0, sticky="w")
        music_row = ttk.Frame(controls)
        music_row.grid(row=14, column=0, sticky="ew", pady=(4, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Add Music", command=self.add_music_track)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Music", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(controls, textvariable=self.music_label_var, wraplength=360).grid(row=15, column=0, sticky="ew")
        ttk.Label(controls, text="Original Soundtrack Volume").grid(row=16, column=0, sticky="w", pady=(8, 0))
        self.source_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.source_volume_var,
            command=self.on_source_volume_changed,
        )
        self.source_volume_slider.grid(row=17, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(controls, text="Added Music Volume").grid(row=18, column=0, sticky="w", pady=(8, 0))
        self.music_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.music_volume_var,
            command=self.on_music_volume_changed,
        )
        self.music_volume_slider.grid(row=19, column=0, sticky="ew", pady=(2, 6))
        self.tone_match_button = ttk.Button(
            controls,
            text="Tone Match + Half Volume",
            command=self.apply_tone_match_preset,
        )
        self.tone_match_button.grid(row=20, column=0, sticky="ew", pady=(0, 10))

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(controls, textvariable=self.status_var, wraplength=360, justify=tk.LEFT)
        self.status_label.grid(row=21, column=0, sticky="ew", pady=(0, 12))

        ttk.Separator(controls).grid(row=22, column=0, sticky="ew", pady=8)

        self.info_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.info_var, justify=tk.LEFT, wraplength=360).grid(row=23, column=0, sticky="ew")

        self.progress = ttk.Progressbar(controls, mode="determinate")
        self.progress.grid(row=24, column=0, sticky="ew", pady=(16, 4))

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
            self.source_volume_slider,
            self.music_volume_slider,
            self.tone_match_button,
            self.timeline_zoom_slider,
        ]

    def _set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.video_controls:
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

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
            self.music_label_var.set("No music track")
            self.music_volume_var.set(50.0)
            self.source_volume_var.set(100.0)
            self.music_tone_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_volume_var.set(round(self.state.music_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
        if self.state.music_path:
            name = Path(self.state.music_path).name
            suffix = "tone match on" if self.state.music_tone_match else "tone match off"
            self.music_label_var.set(f"{name} ({self.music_volume_var.get():.0f}%, {suffix})")
        else:
            self.music_label_var.set("No music track")

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
            return self.make_replacement_frame(source_frame, override)
        return self.read_frame(source_frame)

    def read_frame_from_video(self, frame_index):
        cap = cv2.VideoCapture(str(self.state.video_path))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, clamp(frame_index, 0, self.state.frame_count - 1))
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            cap.release()

    def make_replacement_frame(self, frame_index, override_path):
        replacement = image_to_bgr(override_path, (self.state.width, self.state.height))
        if not self.state.frame_color_blend:
            return replacement
        previous_frame = self.read_frame_from_video(max(0, frame_index - 1))
        next_frame = self.read_frame_from_video(min(self.state.frame_count - 1, frame_index + 1))
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
        self.status_var.set(f"Playing preview at {self.state.export_fps:.3f} FPS.")
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
        self.state.current_output_frame += 1
        playback_fps = max(1.0, self.state.export_fps)
        self.play_after_id = self.after(max(1, int(round(1000 / playback_fps))), self.playback_tick)

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
            image.thumbnail((sheet_width - 24, sheet_height - 48), Image.Resampling.LANCZOS)
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
            f"Music track: {'yes' if self.state.music_path else 'no'}\n"
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
        self.state.edits[str(self.state.current_output_frame)] = str(Path(path))
        self.show_current_frame()
        self.status_var.set("Frame replaced. Click Save Edits to keep this change.")

    def replace_every_x_frames(self):
        if not self.state:
            return
        if self.imported_image_path and self.imported_image_path.exists():
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
        count = 0
        for output_frame in range(start_frame, self.state.output_frame_count, interval):
            self.state.edits[str(output_frame)] = str(path)
            count += 1
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

    def open_import_editor(self):
        if not self.state:
            return
        if self.imported_image is None:
            self.import_image()
            if self.imported_image is None:
                return

        editor_output_frame = self.state.current_output_frame
        original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))
        if original_frame is None:
            messagebox.showerror("Edit Imported", "Could not read the frame being replaced.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        imported_source = self.imported_image.copy().convert("RGBA")
        imported = self.fit_image_to_frame(imported_source, original.size)

        window = tk.Toplevel(self)
        window.title("Edit Imported Image")
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

        tool_var = tk.StringVar(value="brush")
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
            "frame_opacity": tk.DoubleVar(value=35.0),
            "image_opacity": tk.DoubleVar(value=100.0),
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
        ttk.Label(panel, text="Imported image").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["image_opacity"], command=self.on_editor_layer_control_changed).grid(row=4, column=0, sticky="ew")
        ttk.Label(panel, text="Imported image size").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=5, to=300, variable=state["image_size"], command=self.on_imported_image_size_changed).grid(row=6, column=0, sticky="ew")
        ttk.Label(panel, text="Imported image rotation").grid(row=7, column=0, sticky="w", pady=(8, 0))
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
        tile = Image.new("RGBA", (text_width + padding * 2, text_height + padding * 2), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile)
        fill = self.text_fill_color(text_obj, (text_width, text_height))
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
            x_shift = int(abs(warp) * tile.height)
            new_width = tile.width + x_shift
            offset = x_shift if warp < 0 else 0
            tile = tile.transform(
                (new_width, tile.height),
                Image.Transform.AFFINE,
                (1, warp, -offset, 0, 1, 0),
                resample=Image.Resampling.BICUBIC,
            )

        rotation = float(text_obj.get("rotation", 0))
        if abs(rotation) > 0.01:
            tile = tile.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)

        x = int(text_obj.get("x", 0))
        y = int(text_obj.get("y", 0))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.paste(tile, (x, y), tile)
        return layer, (x, y, x + tile.width, y + tile.height)

    def text_fill_color(self, text_obj, text_size):
        fill = self.rgba_from_hex(text_obj.get("color", "#ffffff"), text_obj.get("opacity", 100))
        camouflage = clamp(float(text_obj.get("camouflage", 0)), 0, 100) / 100
        if camouflage <= 0:
            return fill
        sample = self.sample_editor_color_under_text(text_obj, text_size)
        blended_rgb = tuple(int(fill[index] * (1 - camouflage) + sample[index] * camouflage) for index in range(3))
        return (*blended_rgb, fill[3])

    def sample_editor_color_under_text(self, text_obj, text_size):
        state = self.editor_state
        if not state:
            return (255, 255, 255)
        base = self.compose_editor_base(include_draw_layer=True).convert("RGB")
        width, height = base.size
        x = int(text_obj.get("x", 0))
        y = int(text_obj.get("y", 0))
        text_width, text_height = text_size
        x1 = max(0, min(width, x))
        y1 = max(0, min(height, y))
        x2 = max(x1 + 1, min(width, x + max(1, text_width)))
        y2 = max(y1 + 1, min(height, y + max(1, text_height)))
        if x1 >= width or y1 >= height:
            return (255, 255, 255)
        crop = np.array(base.crop((x1, y1, x2, y2)))
        if crop.size == 0:
            return (255, 255, 255)
        average = crop.reshape(-1, 3).mean(axis=0)
        return tuple(int(channel) for channel in average)

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
        self.push_editor_undo()
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        target = pixels[y, x, :3].astype(np.int16)
        rgb = pixels[:, :, :3].astype(np.int16)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        mask = self.connected_background_mask(distance <= tolerance, x, y)
        alpha = pixels[:, :, 3]
        alpha[mask] = 0
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        state["image_size"].set(self.current_content_scale_percent(state["imported_content"], state["original"].size))
        state["imported"] = self.fit_image_to_frame(state["imported_content"].copy(), state["original"].size, state["image_size"].get())
        self.refresh_editor_preview()

    def auto_remove_imported_background(self):
        state = self.editor_state
        if not state:
            return
        self.push_editor_undo()
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        height, width = pixels.shape[:2]
        rgb = pixels[:, :, :3].astype(np.int16)
        samples = np.concatenate((rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]), axis=0)
        target = np.median(samples, axis=0)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        edge_mask = np.zeros((height, width), dtype=bool)
        edge_mask[0, :] = distance[0, :] <= tolerance
        edge_mask[-1, :] = distance[-1, :] <= tolerance
        edge_mask[:, 0] = distance[:, 0] <= tolerance
        edge_mask[:, -1] = distance[:, -1] <= tolerance
        mask = self.connected_background_mask(distance <= tolerance, None, None, edge_mask)
        alpha = pixels[:, :, 3]
        alpha[mask] = 0
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        state["image_size"].set(self.current_content_scale_percent(state["imported_content"], state["original"].size))
        state["imported"] = self.fit_image_to_frame(state["imported_content"].copy(), state["original"].size, state["image_size"].get())
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
            elif state.get("selected_text"):
                self.push_editor_undo()
                state["selected_text"]["x"], state["selected_text"]["y"] = point
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
            if selected:
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
        answer = messagebox.askyesnocancel("Edit Imported Image", "Apply these changes to the selected video frame before closing?")
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
        self.state.edits[str(output_frame)] = str(output)
        self.state.current_output_frame = output_frame
        self.show_current_frame()
        self.editor_state["window"].destroy()
        self.editor_state = None
        self.status_var.set(f"Applied edited image to frame {output_frame}. Click Save Edits to keep this change.")

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
            title="Choose Extra Music Track",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"),
                ("Video/audio files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.state.music_path = str(Path(path))
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Music track added. Click Save Edits to keep this change.")

    def clear_music_track(self):
        if not self.state:
            return
        self.state.music_path = ""
        self.state.music_tone_match = False
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Music track cleared. Click Save Edits to keep this change.")

    def on_music_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.music_volume = clamp(self.music_volume_var.get() / 100.0, 0.0, 2.0)
        self.sync_music_controls()

    def on_source_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.source_volume = clamp(self.source_volume_var.get() / 100.0, 0.0, 2.0)
        self.sync_music_controls()

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
        if not self.state.music_path:
            messagebox.showinfo("Tone Match", "Add a music track first.")
            return
        self.state.music_volume = 0.5
        self.state.music_tone_match = True
        self.sync_music_controls()
        self.status_var.set("Tone match preset enabled and music volume set to 50%. Click Save Edits to keep this change.")

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

    def _export_worker(self, output_path):
        temp_dir = Path(tempfile.mkdtemp(prefix="quad_editor_"))
        silent_path = temp_dir / "video_no_audio.mp4"
        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(silent_path),
                fourcc,
                self.state.export_fps,
                (self.state.width, self.state.height),
            )
            if not writer.isOpened():
                raise RuntimeError("Could not start MP4 writer.")

            cap = cv2.VideoCapture(str(self.state.video_path))
            current_source_frame = None
            frame = None
            for output_frame in range(self.state.output_frame_count):
                source_frame = self.state.source_frame_for_output(output_frame)
                if source_frame != current_source_frame:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                    ok, frame = cap.read()
                    if not ok:
                        break
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(source_frame, override)
                else:
                    out_frame = frame
                writer.write(out_frame)
                if output_frame % 20 == 0:
                    self.after(0, self.progress.configure, {"value": output_frame + 1})
                    self.after(
                        0,
                        self.status_var.set,
                        f"Exporting frame {output_frame + 1} of {self.state.output_frame_count}...",
                    )
            cap.release()
            writer.release()

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = self.build_ffmpeg_command(ffmpeg, silent_path, output_path)
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.after(0, self._export_done, output_path, None)
        except Exception as exc:
            self.after(0, self._export_done, output_path, exc)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def build_ffmpeg_command(self, ffmpeg, silent_path, output_path):
        music_path = Path(self.state.music_path) if self.state.music_path else None
        has_music = music_path and music_path.exists()
        if not has_music:
            has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
            if has_source_audio and abs(self.state.source_volume - 1.0) > 0.001:
                return [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(silent_path),
                    "-i",
                    str(self.state.video_path),
                    "-filter_complex",
                    f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[aout]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(output_path),
                ]
            return [
                ffmpeg,
                "-y",
                "-i",
                str(silent_path),
                "-i",
                str(self.state.video_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(output_path),
            ]

        has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
        semitone_shift = 0
        if self.state.music_tone_match and has_source_audio:
            self.after(0, self.status_var.set, "Analyzing audio keys...")
            source_key = analyze_audio_key(ffmpeg, self.state.video_path)
            music_key = analyze_audio_key(ffmpeg, music_path)
            semitone_shift = shortest_semitone_shift(music_key["pc"], source_key["pc"])
            self.after(
                0,
                self.status_var.set,
                f"Key match: music {key_label(music_key)} to video {key_label(source_key)} ({semitone_shift:+d} semitones).",
            )

        music_filter = f"{ffmpeg_pitch_filter(semitone_shift)}volume={self.state.music_volume:.3f}"
        if self.state.music_tone_match:
            music_filter += ",highpass=f=80,lowpass=f=12000,acompressor=threshold=0.25:ratio=2.5:attack=20:release=250"
        export_duration = f"{self.state.duration:.6f}"

        if has_source_audio:
            return [
                ffmpeg,
                "-y",
                "-i",
                str(silent_path),
                "-i",
                str(self.state.video_path),
                "-stream_loop",
                "-1",
                "-i",
                str(music_path),
                "-filter_complex",
                f"[1:a:0]volume={self.state.source_volume:.3f}[maina];[2:a:0]{music_filter}[musica];"
                "[maina][musica]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]",
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-t",
                export_duration,
                str(output_path),
            ]

        return [
            ffmpeg,
            "-y",
            "-i",
            str(silent_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            f"[1:a:0]{music_filter},alimiter=limit=0.95[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            export_duration,
            str(output_path),
        ]

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
