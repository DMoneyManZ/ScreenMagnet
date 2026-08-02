"""ScreenManget — a system-tray panel for throwing this machine's screen at a TV."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .caster import Caster, preflight
from .discovery import DiscoveryThread, Screen
from .monitors import list_monitors
from .spinner import ChasingArrows

APP_NAME = "ScreenManget"
CONFIG = Path.home() / ".config/screenmanget/config.json"
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(data: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def app_icon() -> QIcon:
    """A screen glyph. Prefers the shipped SVG, falls back to a drawn pixmap."""
    svg = ASSETS / "screenmanget.svg"
    if svg.exists():
        icon = QIcon(str(svg))
        if not icon.isNull():
            return icon
    themed = QIcon.fromTheme("video-display")
    if not themed.isNull():
        return themed

    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#dcdcdc"))
    p.drawRoundedRect(6, 12, 52, 34, 5, 5)
    p.setBrush(QColor("#2c2c2c"))
    p.drawRoundedRect(10, 16, 44, 26, 3, 3)
    p.setBrush(QColor("#dcdcdc"))
    p.drawRect(26, 46, 12, 6)
    p.drawRoundedRect(18, 52, 28, 5, 2, 2)
    p.end()
    return QIcon(pm)


class ScreenRow(QPushButton):
    """One discovered screen, as a clickable row."""

    def __init__(self, screen: Screen, parent=None):
        super().__init__(parent)
        self.screen = screen
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setMinimumHeight(48)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(1)

        name = QLabel(screen.label)
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        sub = QLabel(screen.sublabel)
        sub.setEnabled(False)
        sf = sub.font()
        sf.setPointSize(max(7, sf.pointSize() - 2))
        sub.setFont(sf)

        lay.addWidget(name)
        lay.addWidget(sub)
        self.setStyleSheet(
            "QPushButton { text-align:left; border:none; border-radius:6px; }"
            "QPushButton:hover { background: palette(alternate-base); }"
        )


class Panel(QWidget):
    """The flyout that appears when the tray icon is clicked."""

    def __init__(self, tray: "ScreenMangetTray"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.tray = tray
        self.setMinimumWidth(340)
        self.setObjectName("panel")
        self.setStyleSheet(
            "#panel { background: palette(window); border: 1px solid palette(mid);"
            " border-radius: 10px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        title = QLabel(APP_NAME)
        tf = title.font()
        tf.setBold(True)
        tf.setPointSize(tf.pointSize() + 1)
        title.setFont(tf)
        root.addWidget(title)

        # --- scanning state -------------------------------------------------
        self.scan_box = QWidget()
        sb = QHBoxLayout(self.scan_box)
        sb.setContentsMargins(0, 10, 0, 10)
        sb.setSpacing(12)
        self.spinner = ChasingArrows(diameter=40)
        sb.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self.scan_label = QLabel("Looking for screens…")
        sb.addWidget(self.scan_label, 1, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.scan_box)

        # --- results --------------------------------------------------------
        # Scrolled: this LAN routinely turns up 8+ AirPlay receivers, and an
        # unbounded list grows the popup straight off the bottom of the screen.
        self.results = QWidget()
        self.results_layout = QVBoxLayout(self.results)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(2)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidget(self.results)
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.results_scroll.setMaximumHeight(300)
        root.addWidget(self.results_scroll)

        # --- PIN entry ------------------------------------------------------
        self.pin_box = QWidget()
        pb = QHBoxLayout(self.pin_box)
        pb.setContentsMargins(0, 4, 0, 4)
        pb.addWidget(QLabel("PIN on TV:"))
        self.pin_input = QLineEdit()
        self.pin_input.setMaxLength(4)
        self.pin_input.setFixedWidth(70)
        self.pin_input.setPlaceholderText("0000")
        self.pin_input.returnPressed.connect(self._submit_pin)
        pb.addWidget(self.pin_input)
        go = QPushButton("Pair")
        go.clicked.connect(self._submit_pin)
        pb.addWidget(go)
        pb.addStretch(1)
        self.pin_box.hide()
        root.addWidget(self.pin_box)

        # --- monitor selector ----------------------------------------------
        self.mon_box = QWidget()
        mb = QHBoxLayout(self.mon_box)
        mb.setContentsMargins(0, 2, 0, 2)
        mb.addWidget(QLabel("Send"))
        self.mon_combo = QComboBox()
        self.mon_combo.currentIndexChanged.connect(self._monitor_changed)
        mb.addWidget(self.mon_combo, 1)
        root.addWidget(self.mon_box)

        self.lowlat = QCheckBox("Low latency (audio lags ~0.4s)")
        self.lowlat.setChecked(True)
        self.lowlat.setToolTip(
            "Drops the receiver's 500ms audio jitter margin.\n"
            "Measured on this TV: 1.4s -> 1.0s end to end.\n"
            "Uncheck if you care about the sound."
        )
        self.lowlat.toggled.connect(self.tray.set_low_latency)
        root.addWidget(self.lowlat)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setEnabled(False)
        root.addWidget(line)

        # --- status / actions ----------------------------------------------
        self.status = QLabel("")
        self.status.setWordWrap(True)
        sfont = self.status.font()
        sfont.setPointSize(max(7, sfont.pointSize() - 1))
        self.status.setFont(sfont)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.tray.rescan)
        actions.addWidget(self.rescan_btn)
        self.stop_btn = QPushButton("Stop casting")
        self.stop_btn.clicked.connect(self.tray.stop_cast)
        self.stop_btn.hide()
        actions.addWidget(self.stop_btn)
        actions.addStretch(1)
        root.addLayout(actions)

    # -- monitor list --------------------------------------------------------
    def refresh_monitors(self, selected: str | None):
        self.mon_combo.blockSignals(True)
        self.mon_combo.clear()
        mons = list_monitors()
        for m in mons:
            self.mon_combo.addItem(m.label, m.name)
        if selected:
            idx = self.mon_combo.findData(selected)
            if idx >= 0:
                self.mon_combo.setCurrentIndex(idx)
        self.mon_box.setVisible(len(mons) > 1)
        self.mon_combo.blockSignals(False)

    def selected_monitor(self) -> str | None:
        return self.mon_combo.currentData()

    def _monitor_changed(self, _idx):
        self.tray.set_monitor(self.selected_monitor())

    # -- pin -----------------------------------------------------------------
    def ask_pin(self):
        self.pin_box.show()
        self.pin_input.setFocus()

    def hide_pin(self):
        """Drop any pending PIN prompt. A PIN belongs to one receiver, so it must
        not survive picking a different screen or ending a session."""
        self.pin_input.clear()
        self.pin_box.hide()

    def _submit_pin(self):
        pin = self.pin_input.text().strip()
        if len(pin) == 4 and pin.isdigit():
            self.pin_box.hide()
            self.pin_input.clear()
            self.tray.submit_pin(pin)

    # -- results -------------------------------------------------------------
    def set_scanning(self, on: bool, text: str = "Looking for screens…"):
        self.scan_label.setText(text)
        self.scan_box.setVisible(on)
        self.rescan_btn.setEnabled(not on)
        if on:
            self.spinner.start()
        else:
            self.spinner.stop()

    def show_screens(self, screens: list[Screen]):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if not screens:
            empty = QLabel("No screens found.\nMake sure the TV is on and on the network.")
            empty.setEnabled(False)
            empty.setContentsMargins(12, 8, 12, 8)
            self.results_layout.addWidget(empty)
            return

        for s in screens:
            row = ScreenRow(s)
            row.clicked.connect(lambda _=False, sc=s: self.tray.cast_to(sc))
            self.results_layout.addWidget(row)

    def set_status(self, text: str, warn: bool = False):
        self.status.setText(text)
        self.status.setStyleSheet("color: palette(link-visited);" if warn else "")


class ScreenMangetTray(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(app_icon(), app)
        self.app = app
        self.cfg = load_config()
        self.panel = Panel(self)
        self.caster = Caster(self)
        self._discovery: DiscoveryThread | None = None
        self._pending: Screen | None = None
        self._screens: list[Screen] = []

        self.setToolTip(APP_NAME)
        self.activated.connect(self._on_activated)

        menu = QMenu()
        act_show = QAction("Open", self)
        act_show.triggered.connect(self.show_panel)
        menu.addAction(act_show)
        act_rescan = QAction("Rescan", self)
        act_rescan.triggered.connect(self.rescan)
        menu.addAction(act_rescan)
        menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)
        self.setContextMenu(menu)

        self.caster.connected.connect(self._on_connected)
        self.caster.streaming.connect(self._on_streaming)
        self.caster.needs_pin.connect(self._on_needs_pin)
        self.caster.failed.connect(self._on_failed)
        self.caster.stopped.connect(self._on_stopped)

        problems = preflight()
        if problems:
            self.panel.set_status("⚠ " + "; ".join(problems), warn=True)

    # -- tray behaviour ------------------------------------------------------
    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.panel.isVisible():
                self.panel.hide()
            else:
                self.show_panel()

    def show_panel(self):
        self.panel.refresh_monitors(self.cfg.get("monitor"))
        self.panel.lowlat.setChecked(self.cfg.get("low_latency", True))
        # Remember where the click happened: on Plasma 6 the tray is a
        # StatusNotifierItem drawn by the panel, so QSystemTrayIcon.geometry()
        # is frequently empty and the cursor is the only reliable anchor.
        self._click_pos = QCursor.pos()
        self.place_panel()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        if not self.caster.active and not self._screens:
            self.rescan()

    def place_panel(self):
        """Size the panel to its content, then anchor it fully on-screen.

        Must run again after anything changes the panel's height -- the list
        grows when discovery lands, and positioning only at open time let it
        run off the bottom of the display.
        """
        self.panel.adjustSize()
        size = self.panel.size()

        anchor = getattr(self, "_click_pos", None) or QCursor.pos()
        geo = self.geometry()
        if not geo.isEmpty():
            anchor = QPoint(geo.center().x(), geo.top())

        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()

        x = anchor.x() - size.width() // 2
        # Prefer above the cursor/icon (tray usually sits at the bottom); flip
        # below if there isn't room up there.
        y = anchor.y() - size.height() - 10
        if y < avail.top() + 4:
            y = anchor.y() + 10

        x = max(avail.left() + 4, min(x, avail.right() - size.width() - 4))
        y = max(avail.top() + 4, min(y, avail.bottom() - size.height() - 4))
        self.panel.move(QPoint(x, y))

    # -- discovery -----------------------------------------------------------
    def rescan(self):
        if self._discovery and self._discovery.isRunning():
            return
        self.panel.show_screens([])
        self.panel.set_scanning(True)
        self._discovery = DiscoveryThread(self)
        self._discovery.found.connect(self._on_found)
        self._discovery.start()

    def _on_found(self, screens: list):
        self._screens = screens
        self.panel.set_scanning(False)
        self.panel.show_screens(screens)
        if screens:
            self.panel.set_status(f"{len(screens)} screen(s) found. Click one to cast.")
        else:
            self.panel.set_status("Nothing answered. Is the TV powered on?", warn=True)
        self.place_panel()

    # -- casting -------------------------------------------------------------
    def set_low_latency(self, on: bool):
        self.cfg["low_latency"] = on
        save_config(self.cfg)

    def set_monitor(self, name: str | None):
        self.cfg["monitor"] = name
        save_config(self.cfg)
        if self.caster.active and self._pending:
            self.panel.set_status("Monitor changed — restarting cast…")
            self.caster.start(
                self._pending.ip, self.panel.selected_monitor(),
                low_latency=self.panel.lowlat.isChecked(),
            )

    def cast_to(self, screen: Screen):
        self._pending = screen
        self.cfg["last_screen"] = screen.ip
        save_config(self.cfg)
        self.panel.hide_pin()
        self.panel.set_scanning(True, f"Connecting to {screen.name}…")
        self.panel.set_status("")
        self.caster.start(
            screen.ip, self.panel.selected_monitor(),
            low_latency=self.panel.lowlat.isChecked(),
        )

    def submit_pin(self, pin: str):
        if self._pending:
            self.panel.set_scanning(True, "Pairing…")
            self.caster.start(
                self._pending.ip, self.panel.selected_monitor(), pin=pin,
                low_latency=self.panel.lowlat.isChecked(),
            )

    def stop_cast(self):
        self.caster.stop()

    def _on_connected(self, name: str):
        self.panel.set_scanning(True, f"Connected to {name}, starting…")

    def _on_streaming(self):
        self.panel.set_scanning(False)
        self.panel.hide_pin()
        who = self._pending.name if self._pending else "screen"
        self.panel.set_status(f"● Casting to {who}")
        self.setToolTip(f"{APP_NAME} — casting to {who}")
        self.panel.stop_btn.show()
        self.place_panel()

    def _on_needs_pin(self):
        self.panel.set_scanning(False)
        self.panel.set_status("Enter the 4-digit code shown on the TV.")
        self.panel.ask_pin()
        self.place_panel()
        if not self.panel.isVisible():
            self.show_panel()

    def _on_failed(self, msg: str):
        self.panel.set_scanning(False)
        self.panel.set_status(f"⚠ {msg}", warn=True)
        self.panel.stop_btn.hide()
        self.setToolTip(APP_NAME)
        self.place_panel()

    def _on_stopped(self):
        self.panel.set_scanning(False)
        self.panel.hide_pin()
        self.panel.stop_btn.hide()
        self.setToolTip(APP_NAME)
        if not self.panel.status.text().startswith("⚠"):
            self.panel.set_status("Stopped.")

    def quit(self):
        self.caster.stop()
        QTimer.singleShot(200, self.app.quit)
