"""Compact recording indicator - One Dark pulsing dot, equalizer bars, timer."""

import math
import random
from collections import deque

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

# Atom One Dark palette
OD_FOREGROUND = "#abb2bf"
OD_MUTED = "#5c6370"
OD_DIM_BAR = "#3b4048"
OD_RED = "#e06c75"  # recording dot
OD_BLUE = "#61afef"  # recording bars
OD_YELLOW = "#e5c07b"  # transcribing
OD_GREEN = "#98c379"  # done


class RecordingBar(QWidget):
    """Single-row dictation indicator: pulsing dot + equalizer bars + timer."""

    NUM_BARS = 14

    def __init__(self, parent=None):
        super().__init__(parent)

        # State: "idle" | "recording" | "transcribing" | "done"
        self._mode = "idle"

        # Audio level (already 0..1 after gain) and smoothed per-bar heights
        self._level = 0.0
        self._bars = [0.05] * self.NUM_BARS
        self._bar_phase = [random.uniform(0, math.tau) for _ in range(self.NUM_BARS)]
        self._level_history = deque(maxlen=30)

        # Pulsing dot phase and a shimmer offset for the transcribing animation
        self._phase = 0.0

        # Elapsed timer (seconds), shown as M:SS while recording/transcribing
        self._elapsed = 0
        self._timer_text = "0:00"

        # Sensitivity -> gain (0..200 maps to 0.0..2.0), matches old waveform
        self._sensitivity_value = 200
        self._gain = self._sensitivity_value / 100.0

        # ~60 FPS animation tick
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.setInterval(16)

        # 1 Hz elapsed-time tick
        self._sec_timer = QTimer(self)
        self._sec_timer.timeout.connect(self._tick_second)
        self._sec_timer.setInterval(1000)

        self.setMinimumHeight(28)

    # --- public API (mirrors the old WaveformWidget surface) ---

    @property
    def sensitivity(self) -> int:
        return self._sensitivity_value

    @sensitivity.setter
    def sensitivity(self, value: int) -> None:
        self._sensitivity_value = max(0, min(200, value))
        self._gain = self._sensitivity_value / 100.0

    def set_recording(self, recording: bool) -> None:
        """Start or stop the recording visualization."""
        if recording:
            self._mode = "recording"
            self._level = 0.0
            self._level_history.clear()
            self._elapsed = 0
            self._timer_text = "0:00"
            self._anim_timer.start()
            self._sec_timer.start()
        else:
            # Stop feeding audio; mode is refined by set_mode (transcribing/idle).
            self._sec_timer.stop()
            self._level = 0.0
        self.update()

    def set_mode(self, mode: str) -> None:
        """Set the visual mode: recording | transcribing | done | idle."""
        self._mode = mode
        if mode in ("recording", "transcribing"):
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        elif mode == "idle":
            self._anim_timer.stop()
            self._sec_timer.stop()
            self._bars = [0.05] * self.NUM_BARS
        self.update()

    def update_waveform(self, level: float, waveform_buffer: list) -> None:
        """Feed a new mic level (0..1); buffer kept for API compatibility."""
        amplified = min(1.0, level * self._gain)
        self._level = amplified
        self._level_history.append(amplified)

    # --- animation ---

    def _tick_second(self) -> None:
        self._elapsed += 1
        self._timer_text = f"{self._elapsed // 60}:{self._elapsed % 60:02d}"
        self.update()

    def _animate(self) -> None:
        self._phase += 0.12

        if self._mode == "recording":
            for i in range(self.NUM_BARS):
                self._bar_phase[i] += 0.18 + self._level * 0.25
                wobble = (math.sin(self._bar_phase[i]) + 1) / 2  # 0..1
                target = 0.06 + self._level * (0.45 + 0.55 * wobble)
                self._bars[i] += (target - self._bars[i]) * 0.35
        elif self._mode == "transcribing":
            # Travelling shimmer to signal "working", independent of mic
            for i in range(self.NUM_BARS):
                wave = (math.sin(self._phase * 1.5 - i * 0.5) + 1) / 2
                target = 0.15 + 0.6 * wave
                self._bars[i] += (target - self._bars[i]) * 0.25
        else:
            for i in range(self.NUM_BARS):
                self._bars[i] += (0.05 - self._bars[i]) * 0.2

        self.update()

    # --- painting ---

    def _accent(self) -> QColor:
        if self._mode == "transcribing":
            return QColor(OD_YELLOW)
        if self._mode == "done":
            return QColor(OD_GREEN)
        if self._mode == "recording":
            return QColor(OD_BLUE)
        return QColor(OD_DIM_BAR)

    def _dot_color(self) -> QColor:
        if self._mode == "transcribing":
            return QColor(OD_YELLOW)
        if self._mode == "done":
            return QColor(OD_GREEN)
        if self._mode == "recording":
            return QColor(OD_RED)
        return QColor(OD_MUTED)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

        w = self.width()
        h = self.height()
        cy = h / 2

        # 1) Pulsing record dot on the left
        dot_color = self._dot_color()
        pulse = (math.sin(self._phase) + 1) / 2  # 0..1
        if self._mode in ("recording", "transcribing"):
            dot_r = 4.0 + pulse * 1.5
            dot_color.setAlpha(int(160 + pulse * 95))
        else:
            dot_r = 4.0
            dot_color.setAlpha(180)
        dot_cx = 14.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(QRectF(dot_cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))

        # 3) Timer text on the right (measure first to bound the bars area)
        painter.setPen(QColor(OD_FOREGROUND))
        font = QFont()
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        timer_w = painter.fontMetrics().horizontalAdvance("00:00") + 6
        timer_rect = QRectF(w - timer_w - 12, 0, timer_w, h)
        painter.drawText(
            timer_rect,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._timer_text,
        )

        # 2) Equalizer bars between the dot and the timer
        bars_left = dot_cx + 14
        bars_right = w - timer_w - 18
        bars_area = max(0.0, bars_right - bars_left)
        if bars_area <= 0:
            painter.end()
            return

        gap = 3.0
        bar_w = max(2.0, (bars_area - gap * (self.NUM_BARS - 1)) / self.NUM_BARS)
        max_bar_h = h - 10
        accent = self._accent()
        for i in range(self.NUM_BARS):
            frac = max(0.04, min(1.0, self._bars[i]))
            bar_h = frac * max_bar_h
            x = bars_left + i * (bar_w + gap)
            y = cy - bar_h / 2
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_w / 2, bar_w / 2)

        painter.end()
