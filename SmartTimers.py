# SmartTimers.py
# ---------------------------------------
# A modern, single-file multi-timer desktop app using PySide6.
# - Create multiple named timers (e.g., 10 minutes) with quick presets.
# - Notifies with sound, a full-screen overlay, and a tray notification.
# - Start/Pause/Reset/Delete per timer, optional Repeat (auto-restart).
# - Clean dark UI with rounded "cards" and accent color.
#
# Requirements:
#   pip install PySide6
#
# Run:
#   python SmartTimers.py
#
# Notes:
#   - Works best on Windows 10/11, but should run on macOS/Linux as well.
#   - If system tray is unavailable, app will still show the overlay + play a sound.
#   - Sound uses QtMultimedia.QSoundEffect; if unavailable, falls back to QApplication.beep().
# ---------------------------------------

from __future__ import annotations
import sys, os, math, struct, tempfile, time
from dataclasses import dataclass
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, QTime, QUrl
from PySide6.QtGui import QAction, QIcon, QFont, QPainter, QColor, QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QSpinBox, QScrollArea, QFrame, QProgressBar, QToolButton,
    QSystemTrayIcon, QMenu, QSizePolicy
)

# Try to import QSoundEffect. If it's not available, we'll gracefully degrade to QApplication.beep().
try:
    from PySide6.QtMultimedia import QSoundEffect
    HAS_SOUND = True
except Exception:
    HAS_SOUND = False


# ---------- Utilities ----------

ACCENT = "#7C3AED"  # Purple 600
ACCENT_HOVER = "#8B5CF6"
CARD_BG = "#111318"
SURFACE = "#0B0C10"
TEXT = "#EAEAF0"
SUBTEXT = "#B0B3C3"
DANGER = "#EF4444"
OK = "#10B981"
WARN = "#F59E0B"

def humanize(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def icon_pixmap(emoji: str, size: int = 18) -> QIcon:
    # Create a simple icon from an emoji (no external files needed)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont("Segoe UI Emoji", int(size*0.9))
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignCenter, emoji)
    painter.end()
    return QIcon(pm)


# ---------- Sound Player ----------

class SoundPlayer(QtCore.QObject):
    """Plays a short 'ding' using QSoundEffect or falls back to QApplication.beep()."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.temp_wav = self._ensure_beep_wav()
        self.effect = None
        if HAS_SOUND:
            try:
                self.effect = QSoundEffect()
                self.effect.setSource(QUrl.fromLocalFile(self.temp_wav))
                self.effect.setLoopCount(1)
                self.effect.setVolume(0.6)  # 0.0 - 1.0
            except Exception:
                self.effect = None

    def _ensure_beep_wav(self) -> str:
        """Create a simple sine-wave .wav at runtime (no numpy needed)."""
        path = os.path.join(tempfile.gettempdir(), "smart_timers_beep.wav")
        if os.path.exists(path):
            return path

        # WAV parameters
        sample_rate = 44100
        duration_s = 0.45
        freq_a = 880.0
        n_frames = int(sample_rate * duration_s)

        # Build PCM 16-bit mono
        import wave
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            frames = bytearray()
            for i in range(n_frames):
                # Smooth attack/release to avoid clicks
                t = i / sample_rate
                env = min(1.0, t*10) * min(1.0, (duration_s - t)*10)
                sample = int(32767 * env * math.sin(2*math.pi*freq_a*t))
                frames += struct.pack('<h', sample)
            wf.writeframes(frames)
        return path

    def play(self):
        if self.effect:
            try:
                self.effect.stop()
                self.effect.play()
                return
            except Exception:
                pass
        QApplication.beep()


# ---------- Alarm Overlay ----------

class AlarmOverlay(QWidget):
    """Fullscreen semi-transparent overlay shown when a timer finishes."""
    snoozeRequested = QtCore.Signal(int)  # minutes
    dismissed = QtCore.Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowModality(Qt.ApplicationModal)
        self._title = title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Center card
        center = QWidget()
        center.setObjectName("overlayCard")
        center.setMinimumWidth(520)
        center.setMaximumWidth(720)

        v = QVBoxLayout(center)
        v.setSpacing(18)
        v.setContentsMargins(28, 28, 28, 28)

        title_lbl = QLabel("⏰ Time's up!")
        title_lbl.setObjectName("overlayTitle")
        subtitle = QLabel(self._title.strip() or "Timer")
        subtitle.setObjectName("overlaySubtitle")
        subtitle.setWordWrap(True)

        btns = QHBoxLayout()
        snooze5 = QPushButton("Snooze 5 min")
        snooze10 = QPushButton("Snooze 10 min")
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("danger")

        for b in (snooze5, snooze10, dismiss):
            b.setMinimumHeight(40)
            b.setCursor(Qt.PointingHandCursor)

        snooze5.clicked.connect(lambda: self._on_snooze(5))
        snooze10.clicked.connect(lambda: self._on_snooze(10))
        dismiss.clicked.connect(self._on_dismiss)

        btns.addStretch(1)
        btns.addWidget(snooze5)
        btns.addWidget(snooze10)
        btns.addWidget(dismiss)

        v.addWidget(title_lbl)
        v.addWidget(subtitle)
        v.addLayout(btns)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(center, 0, Qt.AlignCenter)

        outer.addWidget(container)

        self._install_style()

    def _install_style(self):
        self.setStyleSheet(f'''
        QWidget#overlayCard {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {ACCENT}33, stop:1 #1C1F29);
            border: 1px solid #2A2F3A;
            border-radius: 20px;
        }}
        QLabel#overlayTitle {{
            color: {TEXT};
            font-size: 28px; font-weight: 800;
        }}
        QLabel#overlaySubtitle {{
            color: {SUBTEXT};
            font-size: 16px;
        }}
        QPushButton {{
            background: {ACCENT};
            border: none; color: white;
            padding: 8px 16px; border-radius: 10px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: {ACCENT_HOVER}; }}
        QPushButton#danger {{ background: {DANGER}; }}
        QPushButton#danger:hover {{ background: #F87171; }}
        ''')

    def show_full(self):
        # Show on the primary screen as full overlay
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)
        self.showFullScreen()

    def paintEvent(self, e: QtGui.QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

    def _on_snooze(self, minutes: int):
        self.hide()
        self.snoozeRequested.emit(minutes)

    def _on_dismiss(self):
        self.hide()
        self.dismissed.emit()


# ---------- Timer Item Widget ----------

class TimerWidget(QFrame):
    finished = QtCore.Signal(object)   # self
    changed = QtCore.Signal()

    def __init__(self, title: str, seconds: int, repeat: bool=False, parent=None):
        super().__init__(parent)
        self.setObjectName("timerCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        self.title_edit = QLineEdit(title or "Timer")
        self.title_edit.setPlaceholderText("Timer title")
        self.title_edit.textChanged.connect(self.changed.emit)

        self.repeat_chk = QCheckBox("Repeat")
        self.repeat_chk.setChecked(repeat)
        self.repeat_chk.stateChanged.connect(self.changed.emit)

        self.remaining = seconds
        self.total = max(1, seconds)
        self.running = False

        self.time_lbl = QLabel(humanize(self.remaining))
        self.time_lbl.setObjectName("timeLbl")

        self.progress = QProgressBar()
        self.progress.setRange(0, self.total)
        self.progress.setValue(self.total - self.remaining)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)

        self.btn_start = QToolButton()
        self.btn_start.setIcon(icon_pixmap("▶️"))
        self.btn_start.setToolTip("Start / Pause")
        self.btn_start.clicked.connect(self.toggle)

        self.btn_reset = QToolButton()
        self.btn_reset.setIcon(icon_pixmap("⟲"))
        self.btn_reset.setToolTip("Reset")
        self.btn_reset.clicked.connect(self.reset)

        self.btn_delete = QToolButton()
        self.btn_delete.setIcon(icon_pixmap("🗑️"))
        self.btn_delete.setToolTip("Delete")
        self.btn_delete.clicked.connect(self._on_delete)

        header = QHBoxLayout()
        header.addWidget(self.title_edit, 1)
        header.addStretch(1)
        header.addWidget(self.repeat_chk)
        header.addSpacing(6)
        header.addWidget(self.btn_start)
        header.addWidget(self.btn_reset)
        header.addWidget(self.btn_delete)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        v.addLayout(header)

        mid = QHBoxLayout()
        mid.addWidget(self.time_lbl)
        mid.addStretch(1)
        v.addLayout(mid)
        v.addWidget(self.progress)

        self._install_style()

        self._tick = QTimer(self)
        self._tick.setInterval(250)  # 4 fps
        self._tick.timeout.connect(self._on_tick)

    def _install_style(self):
        self.setStyleSheet(f'''
        QFrame#timerCard {{
            background: {CARD_BG};
            border: 1px solid #1D2129;
            border-radius: 16px;
        }}
        QLineEdit {{
            background: #0E1016;
            color: {TEXT};
            padding: 8px 10px; border-radius: 10px;
            border: 1px solid #1F2430;
        }}
        QLineEdit:focus {{ border-color: {ACCENT}; }}
        QLabel#timeLbl {{
            color: {TEXT}; font-size: 32px; font-weight: 800;
        }}
        QCheckBox {{ color: {SUBTEXT}; }}
        QProgressBar {{
            background: #0B0C10; border-radius: 6px;
        }}
        QProgressBar::chunk {{
            background: {ACCENT}; border-radius: 6px;
        }}
        QToolButton {{
            background: #0F1218; border: 1px solid #22283A;
            border-radius: 10px; padding: 6px;
        }}
        QToolButton:hover {{ border-color: {ACCENT}; }}
        ''')

    def set_seconds(self, seconds: int):
        self.remaining = seconds
        self.total = max(1, seconds)
        self.progress.setRange(0, self.total)
        self.progress.setValue(self.total - self.remaining)
        self.time_lbl.setText(humanize(self.remaining))
        self.changed.emit()

    def toggle(self):
        if self.running:
            self.pause()
        else:
            self.start()

    def start(self):
        self.running = True
        self._last = time.time()
        self._tick.start()
        self.btn_start.setIcon(icon_pixmap("⏸️"))

    def pause(self):
        self.running = False
        self._tick.stop()
        self.btn_start.setIcon(icon_pixmap("▶️"))

    def reset(self):
        self.pause()
        self.set_seconds(self.total)

    def _on_delete(self):
        # Signal "finished" with self to allow parent to remove it
        self.running = False
        self._tick.stop()
        self.setParent(None)
        self.deleteLater()
        self.changed.emit()

    def _on_tick(self):
        now = time.time()
        dt = now - getattr(self, "_last", now)
        self._last = now
        self.remaining -= dt
        if self.remaining <= 0:
            self.remaining = 0
            self.progress.setValue(self.total)
            self.time_lbl.setText(humanize(0))
            self.pause()
            self.finished.emit(self)
            return
        self.time_lbl.setText(humanize(int(self.remaining)))
        self.progress.setValue(self.total - int(self.remaining))


# ---------- Main Window ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SmartTimers")
        self.setWindowIcon(icon_pixmap("⏱️"))
        self.setMinimumSize(880, 640)
        self.sound = SoundPlayer(self)

        self._install_style()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("SmartTimers")
        title.setObjectName("appTitle")
        subtitle = QLabel("Multi-timer with sound + overlay notifications")
        subtitle.setObjectName("appSubtitle")

        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        header.addStretch(1)

        self.mute_chk = QCheckBox("Mute sound")
        header.addWidget(self.mute_chk)

        root.addLayout(header)

        # Controls bar
        controls = QFrame()
        controls.setObjectName("controls")
        bar = QHBoxLayout(controls)
        bar.setContentsMargins(12, 12, 12, 12)
        bar.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Timer name (e.g., 'Break', 'Pomodoro', 'Tea')")
        self.h_spin = QSpinBox(); self.h_spin.setRange(0, 23); self.h_spin.setPrefix("H "); self.h_spin.setFixedWidth(90)
        self.m_spin = QSpinBox(); self.m_spin.setRange(0, 59); self.m_spin.setPrefix("M "); self.m_spin.setFixedWidth(90)
        self.s_spin = QSpinBox(); self.s_spin.setRange(0, 59); self.s_spin.setPrefix("S "); self.s_spin.setFixedWidth(90)
        self.repeat_new = QCheckBox("Repeat")

        add_btn = QPushButton("Add Timer")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.add_timer_from_inputs)

        bar.addWidget(self.name_edit, 1)
        bar.addWidget(self.h_spin)
        bar.addWidget(self.m_spin)
        bar.addWidget(self.s_spin)
        bar.addWidget(self.repeat_new)
        bar.addWidget(add_btn)

        root.addWidget(controls)

        # Presets
        presets = QFrame()
        presets.setObjectName("presets")
        p = QHBoxLayout(presets)
        p.setContentsMargins(12, 12, 12, 12)
        p.setSpacing(8)
        p.addWidget(QLabel("Quick presets:"))
        for label, mins in [("5 min",5),("10 min",10),("15 min",15),("25 min (Pomodoro)",25),("45 min",45),("60 min",60)]:
            b = QPushButton(label)
            b.clicked.connect(lambda _, m=mins: self.add_timer(f"{label}", 60*m, repeat=False))
            p.addWidget(b)
        p.addStretch(1)
        root.addWidget(presets)

        # List area
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        content = QWidget()
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(4, 4, 4, 4)
        self.list_layout.setSpacing(10)
        self.area.setWidget(content)
        root.addWidget(self.area, 1)

        # Footer
        footer = QHBoxLayout()
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self.clear_all)
        footer.addStretch(1)
        footer.addWidget(self.clear_btn)
        root.addLayout(footer)

        # Tray
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            self.tray.setIcon(icon_pixmap("⏱️"))
            menu = QMenu()
            show_action = QAction("Show")
            quit_action = QAction("Quit")
            show_action.triggered.connect(self.showNormal)
            quit_action.triggered.connect(QApplication.instance().quit)
            menu.addAction(show_action); menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.show()

        # Restore window state
        settings = QtCore.QSettings("SmartTimers", "SmartTimers")
        g = settings.value("geometry")
        if isinstance(g, QtCore.QByteArray):
            self.restoreGeometry(g)

        self._on_list_changed()

    # ----- UI/Style -----

    def _install_style(self):
        self.setStyleSheet(f'''
        QMainWindow {{
            background: {SURFACE};
        }}
        QLabel#appTitle {{
            color: {TEXT}; font-size: 24px; font-weight: 800;
        }}
        QLabel#appSubtitle {{
            color: {SUBTEXT}; font-size: 12px;
        }}
        QFrame#controls, QFrame#presets {{
            background: {CARD_BG};
            border: 1px solid #1D2129;
            border-radius: 16px;
        }}
        QPushButton {{
            background: {ACCENT}; color: white; border: none;
            padding: 8px 14px; border-radius: 10px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {ACCENT_HOVER}; }}
        QPushButton#danger {{ background: {DANGER}; }}
        QPushButton#danger:hover {{ background: #F87171; }}
        QCheckBox {{ color: {SUBTEXT}; }}
        QLineEdit, QSpinBox {{
            background: #0E1016;
            color: {TEXT};
            border: 1px solid #1F2430;
            border-radius: 10px; padding: 8px 10px;
        }}
        QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
        QScrollArea {{ border: none; }}
        ''')

    # ----- Timer Management -----

    def add_timer_from_inputs(self):
        h, m, s = self.h_spin.value(), self.m_spin.value(), self.s_spin.value()
        total = h*3600 + m*60 + s
        if total <= 0:
            self.statusBar().showMessage("Please set a duration greater than 0.", 3000)
            return
        name = self.name_edit.text().strip() or "Timer"
        self.add_timer(name, total, self.repeat_new.isChecked())
        self.name_edit.clear()
        self.h_spin.setValue(0); self.m_spin.setValue(0); self.s_spin.setValue(0)
        self.repeat_new.setChecked(False)

    def add_timer(self, title: str, seconds: int, repeat: bool):
        w = TimerWidget(title, seconds, repeat)
        w.finished.connect(self._on_timer_finished)
        w.changed.connect(self._on_list_changed)
        self.list_layout.addWidget(w)
        self._on_list_changed()

    def clear_all(self):
        for i in reversed(range(self.list_layout.count())):
            item = self.list_layout.itemAt(i)
            w = item.widget()
            if isinstance(w, TimerWidget):
                w.setParent(None); w.deleteLater()
        self._on_list_changed()

    def _on_list_changed(self):
        has_items = any(isinstance(self.list_layout.itemAt(i).widget(), TimerWidget)
                        for i in range(self.list_layout.count()))
        self.clear_btn.setEnabled(has_items)

    # ----- Notifications -----

    def _notify(self, title: str):
        # Play sound (unless muted)
        if not self.mute_chk.isChecked():
            self.sound.play()

        # Tray balloon
        if self.tray:
            try:
                self.tray.showMessage("SmartTimers", f"{title or 'Timer'} is done.", QSystemTrayIcon.Information, 5000)
            except Exception:
                pass

        # Fullscreen overlay
        self._overlay = AlarmOverlay(title)
        self._overlay.snoozeRequested.connect(self._on_snooze)
        self._overlay.dismissed.connect(lambda: None)
        self._overlay.show_full()

    def _on_timer_finished(self, w: TimerWidget):
        title = w.title_edit.text().strip() or "Timer"
        self._notify(title)
        if w.repeat_chk.isChecked():
            # Restart immediately for repeating timers
            w.set_seconds(w.total)
            w.start()

    def _on_snooze(self, minutes: int):
        # Create a new one-off snooze timer
        label = f"Snooze ({minutes} min)"
        self.add_timer(label, minutes*60, repeat=False)

    # ----- Close/State -----

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        settings = QtCore.QSettings("SmartTimers", "SmartTimers")
        settings.setValue("geometry", self.saveGeometry())
        return super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    QtCore.QCoreApplication.setOrganizationName("SmartTimers")
    QtCore.QCoreApplication.setApplicationName("SmartTimers")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
