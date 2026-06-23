import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageTk


SLOT_COUNT = 4
PREVIEW_MAX = (960, 540)
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
ANALYSIS_SAMPLE_RATE = 22050
ANALYSIS_SECONDS = 90


def clamp(value, low, high):
    return max(low, min(high, value))


def image_to_bgr(path, size):
    image = Image.open(path).convert("RGB")
    image = image.resize(size, Image.Resampling.LANCZOS)
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


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
    current_frame: int = 0
    current_slot: int = 0
    edits: dict = field(default_factory=dict)
    source_volume: float = 1.0
    music_path: str = ""
    music_volume: float = 0.5
    music_tone_match: bool = False
    frame_color_blend: bool = True
    frame_color_blend_strength: float = 0.65
    frame_frequency_blend_strength: float = 0.35

    @property
    def duration(self):
        return self.frame_count / self.fps if self.fps else 0

    @property
    def export_fps(self):
        return self.fps * SLOT_COUNT

    def key(self, frame_index, slot_index):
        return f"{frame_index}:{slot_index}"

    def slot_override(self, frame_index=None, slot_index=None):
        frame_index = self.current_frame if frame_index is None else frame_index
        slot_index = self.current_slot if slot_index is None else slot_index
        return self.edits.get(self.key(frame_index, slot_index))


class MovieQuadEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Movie Frame Quad Editor")
        self.geometry("1180x760")
        self.minsize(980, 660)

        self.state = None
        self.capture = None
        self.preview_photo = None
        self.exporting = False
        self.video_controls = []
        self.contact_bounds = None
        self.music_volume_var = tk.DoubleVar(value=50.0)
        self.source_volume_var = tk.DoubleVar(value=100.0)
        self.music_label_var = tk.StringVar(value="No music track")
        self.music_tone_var = tk.BooleanVar(value=False)
        self.color_blend_var = tk.BooleanVar(value=True)
        self.color_blend_strength_var = tk.DoubleVar(value=65.0)
        self.frequency_blend_strength_var = tk.DoubleVar(value=35.0)

        self._build_ui()
        self._set_controls_enabled(False)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        topbar = ttk.Frame(self, padding=(10, 10, 10, 6))
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.columnconfigure(4, weight=1)

        self.open_button = ttk.Button(topbar, text="Open Video", command=self.open_video)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.save_button = ttk.Button(topbar, text="Save Edits", command=self.save_edits)
        self.save_button.grid(row=0, column=1, padx=(0, 8))
        self.export_button = ttk.Button(topbar, text="Export Video", command=self.export_video)
        self.export_button.grid(row=0, column=2, padx=(0, 12))

        self.video_label = ttk.Label(topbar, text="No video loaded")
        self.video_label.grid(row=0, column=3, columnspan=2, sticky="w")

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        preview_panel = ttk.Frame(main, padding=10)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        main.add(preview_panel, weight=4)

        self.preview_canvas = tk.Canvas(preview_panel, bg="#151515", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self.on_preview_click)

        controls = ttk.Frame(main, padding=10)
        controls.columnconfigure(0, weight=1)
        main.add(controls, weight=2)

        ttk.Label(controls, text="Frame").grid(row=0, column=0, sticky="w")
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

        ttk.Label(controls, text="Duplicate Slot").grid(row=3, column=0, sticky="w")
        slot_row = ttk.Frame(controls)
        slot_row.grid(row=4, column=0, sticky="ew", pady=(4, 12))
        self.slot_var = tk.IntVar(value=0)
        self.slot_buttons = []
        for i in range(SLOT_COUNT):
            slot_row.columnconfigure(i, weight=1)
            slot_button = ttk.Radiobutton(
                slot_row,
                text=f"Slot {i + 1}",
                value=i,
                variable=self.slot_var,
                command=self.on_slot_changed,
            )
            slot_button.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            self.slot_buttons.append(slot_button)

        edit_row = ttk.Frame(controls)
        edit_row.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        edit_row.columnconfigure(0, weight=1)
        edit_row.columnconfigure(1, weight=1)
        self.replace_button = ttk.Button(edit_row, text="Replace Slot", command=self.replace_slot)
        self.replace_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_button = ttk.Button(edit_row, text="Clear Slot", command=self.clear_slot)
        self.clear_button.grid(row=0, column=1, sticky="ew")

        self.color_blend_check = ttk.Checkbutton(
            controls,
            text="Color blend replacement images",
            variable=self.color_blend_var,
            command=self.on_color_blend_changed,
        )
        self.color_blend_check.grid(row=6, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(controls, text="Color Blend Strength").grid(row=7, column=0, sticky="w")
        self.color_blend_slider = ttk.Scale(
            controls,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.color_blend_strength_var,
            command=self.on_color_blend_changed,
        )
        self.color_blend_slider.grid(row=8, column=0, sticky="ew", pady=(2, 10))
        ttk.Label(controls, text="Image Frequency Blend").grid(row=9, column=0, sticky="w")
        self.frequency_blend_slider = ttk.Scale(
            controls,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.frequency_blend_strength_var,
            command=self.on_color_blend_changed,
        )
        self.frequency_blend_slider.grid(row=10, column=0, sticky="ew", pady=(2, 10))

        ttk.Separator(controls).grid(row=11, column=0, sticky="ew", pady=8)

        ttk.Label(controls, text="Extra Music Track").grid(row=12, column=0, sticky="w")
        music_row = ttk.Frame(controls)
        music_row.grid(row=13, column=0, sticky="ew", pady=(4, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Add Music", command=self.add_music_track)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Music", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(controls, textvariable=self.music_label_var, wraplength=360).grid(row=14, column=0, sticky="ew")
        ttk.Label(controls, text="Original Soundtrack Volume").grid(row=15, column=0, sticky="w", pady=(8, 0))
        self.source_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.source_volume_var,
            command=self.on_source_volume_changed,
        )
        self.source_volume_slider.grid(row=16, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(controls, text="Added Music Volume").grid(row=17, column=0, sticky="w", pady=(8, 0))
        self.music_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.music_volume_var,
            command=self.on_music_volume_changed,
        )
        self.music_volume_slider.grid(row=18, column=0, sticky="ew", pady=(2, 6))
        self.tone_match_button = ttk.Button(
            controls,
            text="Tone Match + Half Volume",
            command=self.apply_tone_match_preset,
        )
        self.tone_match_button.grid(row=19, column=0, sticky="ew", pady=(0, 10))

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(controls, textvariable=self.status_var, wraplength=360, justify=tk.LEFT)
        self.status_label.grid(row=20, column=0, sticky="ew", pady=(0, 12))

        ttk.Separator(controls).grid(row=21, column=0, sticky="ew", pady=8)

        self.info_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.info_var, justify=tk.LEFT, wraplength=360).grid(row=22, column=0, sticky="ew")

        self.progress = ttk.Progressbar(controls, mode="determinate")
        self.progress.grid(row=23, column=0, sticky="ew", pady=(16, 4))

        self.video_controls = [
            self.save_button,
            self.export_button,
            self.prev_button,
            self.frame_entry,
            self.next_button,
            self.frame_slider,
            self.replace_button,
            self.clear_button,
            self.color_blend_check,
            self.color_blend_slider,
            self.frequency_blend_slider,
            self.add_music_button,
            self.clear_music_button,
            self.source_volume_slider,
            self.music_volume_slider,
            self.tone_match_button,
            *self.slot_buttons,
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
        self.capture = capture

        video_path = Path(path)
        edit_path = video_path.with_suffix(video_path.suffix + ".quad_edits.json")
        self.state = VideoState(video_path, edit_path, fps, frame_count, width, height)
        self.load_edits()

        self.video_label.configure(text=str(video_path))
        self.frame_slider.configure(to=max(0, frame_count - 1))
        self._set_controls_enabled(True)
        self.status_var.set("Loaded video.")
        self.update_info()
        self.show_current_frame()

    def load_edits(self):
        if not self.state or not self.state.edit_path.exists():
            return
        try:
            data = json.loads(self.state.edit_path.read_text(encoding="utf-8"))
            if data.get("video") == str(self.state.video_path):
                self.state.edits = data.get("edits", {})
                self.state.source_volume = float(data.get("source_volume", 1.0))
                self.state.music_path = data.get("music_path", "")
                self.state.music_volume = float(data.get("music_volume", 0.5))
                self.state.music_tone_match = bool(data.get("music_tone_match", False))
                self.state.frame_color_blend = bool(data.get("frame_color_blend", True))
                self.state.frame_color_blend_strength = float(data.get("frame_color_blend_strength", 0.65))
                self.state.frame_frequency_blend_strength = float(data.get("frame_frequency_blend_strength", 0.35))
                self.sync_color_blend_controls()
                self.sync_music_controls()
                self.status_var.set(f"Loaded {len(self.state.edits)} saved slot edits.")
        except Exception as exc:
            messagebox.showwarning("Load Edits", f"Could not load saved edit map:\n{exc}")

    def save_edits(self):
        if not self.state:
            return
        data = {
            "video": str(self.state.video_path),
            "fps": self.state.fps,
            "width": self.state.width,
            "height": self.state.height,
            "slot_count": SLOT_COUNT,
            "edits": self.state.edits,
            "source_volume": self.state.source_volume,
            "music_path": self.state.music_path,
            "music_volume": self.state.music_volume,
            "music_tone_match": self.state.music_tone_match,
            "frame_color_blend": self.state.frame_color_blend,
            "frame_color_blend_strength": self.state.frame_color_blend_strength,
            "frame_frequency_blend_strength": self.state.frame_frequency_blend_strength,
        }
        self.state.edit_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.status_var.set(f"Saved edits to {self.state.edit_path.name}.")

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

    def get_slot_frame(self, frame_index, slot_index):
        override = self.state.slot_override(frame_index, slot_index)
        if override and Path(override).exists():
            return self.make_replacement_frame(frame_index, override)
        return self.read_frame(frame_index)

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
        image = self.make_slot_contact_sheet()
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_canvas.delete("all")
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        x = canvas_width // 2
        y = canvas_height // 2
        self.preview_canvas.create_image(x, y, image=self.preview_photo)
        self.contact_bounds = (
            x - image.width // 2,
            y - image.height // 2,
            image.width // 2,
            image.height // 2,
        )

        self.frame_var.set(str(self.state.current_frame))
        self.frame_slider.set(self.state.current_frame)
        self.slot_var.set(self.state.current_slot)
        self.update_info()

    def make_slot_contact_sheet(self):
        canvas_width = max(640, self.preview_canvas.winfo_width() or PREVIEW_MAX[0])
        canvas_height = max(420, self.preview_canvas.winfo_height() or PREVIEW_MAX[1])
        sheet_width = min(PREVIEW_MAX[0], canvas_width - 24)
        sheet_height = min(PREVIEW_MAX[1], canvas_height - 24)
        tile_width = sheet_width // 2
        tile_height = sheet_height // 2
        sheet = Image.new("RGB", (tile_width * 2, tile_height * 2), "#101010")
        draw = ImageDraw.Draw(sheet)

        for slot_index in range(SLOT_COUNT):
            frame = self.get_slot_frame(self.state.current_frame, slot_index)
            if frame is None:
                tile = Image.new("RGB", (tile_width, tile_height), "#222222")
            else:
                tile = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                tile.thumbnail((tile_width - 18, tile_height - 38), Image.Resampling.LANCZOS)
                background = Image.new("RGB", (tile_width, tile_height), "#181818")
                background.paste(tile, ((tile_width - tile.width) // 2, (tile_height - tile.height) // 2 + 12))
                tile = background

            x = (slot_index % 2) * tile_width
            y = (slot_index // 2) * tile_height
            sheet.paste(tile, (x, y))

            selected = slot_index == self.state.current_slot
            border = "#48a6ff" if selected else "#444444"
            width = 5 if selected else 2
            for inset in range(width):
                draw.rectangle(
                    [x + inset, y + inset, x + tile_width - 1 - inset, y + tile_height - 1 - inset],
                    outline=border,
                )

            override = self.state.slot_override(self.state.current_frame, slot_index)
            label = f"Slot {slot_index + 1}" + ("  custom" if override else "  source")
            draw.rectangle([x + 8, y + 8, x + 168, y + 32], fill="#000000")
            draw.text((x + 14, y + 13), label, fill="#ffffff")

        return sheet

    def on_preview_click(self, event):
        if not self.state or not self.contact_bounds:
            return
        left, top, half_width, half_height = self.contact_bounds
        local_x = event.x - left
        local_y = event.y - top
        if local_x < 0 or local_y < 0 or local_x >= half_width * 2 or local_y >= half_height * 2:
            return
        col = 0 if local_x < half_width else 1
        row = 0 if local_y < half_height else 1
        self.state.current_slot = row * 2 + col
        self.show_current_frame()

    def update_info(self):
        if not self.state:
            self.info_var.set("")
            return
        override = self.state.slot_override()
        slot_text = "custom image" if override else "source frame copy"
        self.info_var.set(
            f"Source frames: {self.state.frame_count}\n"
            f"Source FPS: {self.state.fps:.3f}\n"
            f"Export frames: {self.state.frame_count * SLOT_COUNT}\n"
            f"Export FPS: {self.state.export_fps:.3f}\n"
            f"Duration: {self.state.duration:.2f} seconds\n"
            f"Edited slots: {len(self.state.edits)}\n"
            f"Current slot: {slot_text}\n"
            f"Music track: {'yes' if self.state.music_path else 'no'}\n"
            f"Color blend: {'on' if self.state.frame_color_blend else 'off'}"
        )

    def move_frame(self, delta):
        if not self.state:
            return
        self.state.current_frame = clamp(self.state.current_frame + delta, 0, self.state.frame_count - 1)
        self.show_current_frame()

    def goto_frame_entry(self):
        if not self.state:
            return
        try:
            frame = int(self.frame_var.get())
        except ValueError:
            frame = self.state.current_frame
        self.state.current_frame = clamp(frame, 0, self.state.frame_count - 1)
        self.show_current_frame()

    def on_slider(self, value):
        if not self.state:
            return
        frame = int(float(value))
        if frame != self.state.current_frame:
            self.state.current_frame = frame
            self.show_current_frame()

    def on_slot_changed(self):
        if not self.state:
            return
        self.state.current_slot = self.slot_var.get()
        self.show_current_frame()

    def replace_slot(self):
        if not self.state:
            return
        path = filedialog.askopenfilename(
            title="Choose Replacement Image",
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
            messagebox.showerror("Replace Slot", "That file does not look like a readable image.")
            return
        self.state.edits[self.state.key(self.state.current_frame, self.state.current_slot)] = str(Path(path))
        self.save_edits()
        self.show_current_frame()

    def clear_slot(self):
        if not self.state:
            return
        key = self.state.key(self.state.current_frame, self.state.current_slot)
        if key in self.state.edits:
            del self.state.edits[key]
            self.save_edits()
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
        self.save_edits()
        self.update_info()

    def clear_music_track(self):
        if not self.state:
            return
        self.state.music_path = ""
        self.state.music_tone_match = False
        self.sync_music_controls()
        self.save_edits()
        self.update_info()

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
        self.save_edits()
        self.status_var.set("Tone match preset enabled and music volume set to 50%.")

    def export_video(self):
        if not self.state or self.exporting:
            return
        output = filedialog.asksaveasfilename(
            title="Export Video",
            defaultextension=".mp4",
            initialfile=f"{self.state.video_path.stem}_quad.mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if not output:
            return
        self.save_edits()
        self.exporting = True
        self.open_button.configure(state=tk.DISABLED)
        self._set_controls_enabled(False)
        self.progress.configure(value=0, maximum=self.state.frame_count)
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
            for frame_index in range(self.state.frame_count):
                ok, frame = cap.read()
                if not ok:
                    break
                for slot_index in range(SLOT_COUNT):
                    override = self.state.slot_override(frame_index, slot_index)
                    if override and Path(override).exists():
                        out_frame = self.make_replacement_frame(frame_index, override)
                    else:
                        out_frame = frame
                    writer.write(out_frame)
                if frame_index % 5 == 0:
                    self.after(0, self.progress.configure, {"value": frame_index + 1})
                    self.after(0, self.status_var.set, f"Exporting frame {frame_index + 1} of {self.state.frame_count}...")
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
