"""ScreenMagnet — a system-tray panel for throwing this machine's screen at a TV."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCursor,
    QGuiApplication,
    QIcon,
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

from . import startup, updater
from .caster import Caster, preflight
from .appicon import app_icon
from .config import CONFIG, load_config, save_config
from .discovery import DiscoveryThread, Screen
from .monitors import list_monitors
from .settings_window import SettingsWindow
from .spinner import ChasingArrows
from .virtual_display import (
    DEFAULT_SIDE,
    NOT_ATTACHED_YET_MSG,
    NOT_ENABLED_MSG,
    NOT_INSTALLED_MSG,
    VALID_SIDES,
    enable_virtual_display,
    find_virtual_display_name,
    is_installed,
)

# How often to re-check for updates in the background, beyond the one-shot
# check shortly after startup and whenever the user clicks "Check for
# Updates" in the settings window.
UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 hours
UPDATE_CHECK_STARTUP_DELAY_MS = 5_000  # let discovery/caster settle first

APP_NAME = "ScreenMagnet"


def _prepare_extend_display(side: str) -> tuple[str, str | None]:
    """Runs off the Qt GUI thread (see ScreenMagnetTray._start_extend) -- both
    checking install state and, if needed, enabling the device can shell out to
    PowerShell, and enabling can block on a UAC prompt the user hasn't answered yet.

    Returns (outcome, monitor_name):
      - ("not_installed", None)  -- driver was never installed; see NOT_INSTALLED_MSG.
      - ("not_enabled", None)    -- installed, but turning it on failed or the admin
                                    prompt was declined; see NOT_ENABLED_MSG.
      - ("not_attached", None)   -- enabled, but Windows hasn't surfaced it as a
                                    desktop display yet; see NOT_ATTACHED_YET_MSG.
      - ("ready", name)          -- enabled and positioned; `name` is the Win32 device
                                    name to pass straight to Caster.start(monitor=...).
    """
    if not is_installed():
        return "not_installed", None
    if not enable_virtual_display(side):
        return "not_enabled", None
    name = find_virtual_display_name()
    if not name:
        return "not_attached", None
    return "ready", name


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

    def __init__(self, tray: "ScreenMagnetTray"):
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
        # Sized for ~4 rows (ScreenRow.setMinimumHeight(48) + 2px spacing each)
        # so the panel reliably shows several screens at once instead of
        # shrinking down to whatever was found, with room to scroll for more.
        ROW_H, ROW_SPACING, VISIBLE_ROWS = 48, 2, 4
        rows_height = ROW_H * VISIBLE_ROWS + ROW_SPACING * (VISIBLE_ROWS - 1)

        self.results = QWidget()
        self.results_layout = QVBoxLayout(self.results)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(ROW_SPACING)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidget(self.results)
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.results_scroll.setMinimumHeight(rows_height)
        self.results_scroll.setMaximumHeight(rows_height + ROW_H // 2)
        root.addWidget(self.results_scroll)

        # --- cast mode picker -------------------------------------------------
        # Shown after picking a screen, in place of the results list: mirror an
        # existing monitor (the only mode that actually works today) or treat the
        # TV as new desktop space. Extend needs Windows to have a real virtual
        # display surface to capture, which doubletake/GStreamer can't fabricate
        # on their own -- see docs/EXTENDED-DISPLAY.md.
        self.mode_box = QWidget()
        modeb = QVBoxLayout(self.mode_box)
        modeb.setContentsMargins(0, 4, 0, 4)
        modeb.setSpacing(6)
        self.mode_label = QLabel("")
        modeb.addWidget(self.mode_label)
        self.dup_btn = QPushButton("Cast duplicate of current display")
        self.dup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dup_btn.clicked.connect(lambda: self.tray.cast_to(self._mode_screen, mode="duplicate"))
        modeb.addWidget(self.dup_btn)
        self.ext_btn = QPushButton("Cast as additional display")
        self.ext_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ext_btn.setToolTip(
            "Turns the TV into new desktop space instead of mirroring. Needs the "
            "free VirtualDrivers virtual display driver installed once -- clicking "
            "this checks/turns it on and explains what's missing if it isn't ready. "
            "See docs/EXTENDED-DISPLAY.md."
        )
        self.ext_btn.clicked.connect(lambda: self.tray.cast_to(self._mode_screen, mode="extend"))
        modeb.addWidget(self.ext_btn)

        side_row = QHBoxLayout()
        side_row.addWidget(QLabel("Extend side:"))
        self.extend_side_combo = QComboBox()
        self.extend_side_combo.addItem("Right", "right")
        self.extend_side_combo.addItem("Left", "left")
        self.extend_side_combo.currentIndexChanged.connect(
            lambda _i: self.tray.set_extend_side(self.extend_side_combo.currentData())
        )
        side_row.addWidget(self.extend_side_combo, 1)
        modeb.addLayout(side_row)

        back = QPushButton("← Back to screen list")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFlat(True)
        back.clicked.connect(self.hide_mode_picker)
        modeb.addWidget(back)

        self._mode_screen: Screen | None = None
        self.mode_box.hide()
        root.addWidget(self.mode_box)

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
            row.clicked.connect(lambda _=False, sc=s: self.show_mode_picker(sc))
            self.results_layout.addWidget(row)

    def set_status(self, text: str, warn: bool = False):
        self.status.setText(text)
        self.status.setStyleSheet("color: palette(link-visited);" if warn else "")

    # -- cast mode picker ------------------------------------------------------
    def show_mode_picker(self, screen: Screen):
        self._mode_screen = screen
        self.mode_label.setText(f"Cast to {screen.name}:")
        self.extend_side_combo.blockSignals(True)
        idx = self.extend_side_combo.findData(self.tray.cfg.get("extend_side", DEFAULT_SIDE))
        self.extend_side_combo.setCurrentIndex(max(idx, 0))
        self.extend_side_combo.blockSignals(False)
        self.results_scroll.hide()
        self.mode_box.show()
        self.tray.place_panel()

    def hide_mode_picker(self):
        self._mode_screen = None
        self.mode_box.hide()
        self.results_scroll.show()
        self.tray.place_panel()


class ScreenMagnetTray(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(app_icon(), app)
        self.app = app
        self.cfg = load_config()
        self.panel = Panel(self)
        self.caster = Caster(self)
        self._discovery: DiscoveryThread | None = None
        self._pending: Screen | None = None
        self._screens: list[Screen] = []
        self._extend_worker: updater.CallWorker | None = None

        # -- settings window + self-update state ------------------------
        self.settings_window: SettingsWindow | None = None
        self._update_check_worker: updater.CallWorker | None = None
        self._update_pull_worker: updater.CallWorker | None = None
        self._latest_update: updater.UpdateCheckResult | None = None

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
        act_settings = QAction("Settings...", self)
        act_settings.triggered.connect(self.open_settings)
        menu.addAction(act_settings)
        # Hidden until a background check finds a newer commit upstream --
        # see check_for_updates()/_apply_update_result().
        self.act_update_now = QAction("Update now", self)
        self.act_update_now.triggered.connect(self.update_now)
        self.act_update_now.setVisible(False)
        menu.addAction(self.act_update_now)
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

        # -- self-update: background check shortly after startup, then
        # periodically. Both check_for_update() and run_git_pull() shell out
        # to git (and check_for_update() hits the network), so both run on
        # updater.CallWorker off this thread -- see check_for_updates()/
        # update_now() -- rather than blocking tray construction or the Qt
        # event loop on a slow/offline network.
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self.check_for_updates)
        self._update_timer.start(UPDATE_CHECK_INTERVAL_MS)
        QTimer.singleShot(UPDATE_CHECK_STARTUP_DELAY_MS, self.check_for_updates)

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

    def set_extend_side(self, side: str):
        if side not in VALID_SIDES:
            return
        self.cfg["extend_side"] = side
        save_config(self.cfg)

    def cast_to(self, screen: Screen, mode: str = "duplicate"):
        if mode == "extend":
            self._start_extend(screen)
            return
        self._begin_cast(screen)

    def _start_extend(self, screen: Screen):
        """Kick off install/enable/position checks for the virtual display off the GUI
        thread -- enabling it (if needed) can shell out to PowerShell and block on a
        UAC prompt, so this must not run inline on the Qt event loop. See
        virtual_display.py / docs/EXTENDED-DISPLAY.md."""
        if self._extend_worker is not None and self._extend_worker.isRunning():
            return
        side = self.cfg.get("extend_side", DEFAULT_SIDE)
        self.panel.hide_mode_picker()
        self.panel.hide_pin()
        self.panel.set_scanning(True, "Checking the virtual display…")
        self.panel.set_status("")
        worker = updater.CallWorker(_prepare_extend_display, side)
        worker.done.connect(lambda result, sc=screen: self._on_extend_prepared(sc, result))
        worker.finished.connect(worker.deleteLater)
        self._extend_worker = worker
        worker.start()

    def _on_extend_prepared(self, screen: Screen, result: tuple[str, str | None]):
        outcome, monitor_name = result
        self.panel.set_scanning(False)

        if outcome == "not_installed":
            self.panel.set_status(f"⚠ {NOT_INSTALLED_MSG}", warn=True)
            self.place_panel()
            return
        if outcome == "not_enabled":
            self.panel.set_status(f"⚠ {NOT_ENABLED_MSG}", warn=True)
            self.place_panel()
            return
        if outcome != "ready" or not monitor_name:
            self.panel.set_status(f"⚠ {NOT_ATTACHED_YET_MSG}", warn=True)
            self.place_panel()
            return

        # The virtual display is up. It should now show up in monitors.py's
        # generic enumeration exactly like any other screen (confirmed by the
        # research -- no VDD-specific capture code needed); select it and cast
        # to it exactly like "duplicate" mode does today.
        self.panel.refresh_monitors(monitor_name)
        if self.panel.mon_combo.findData(monitor_name) < 0:
            # Windows/Qt haven't caught up yet -- don't cast to the wrong monitor.
            self.panel.set_status(f"⚠ {NOT_ATTACHED_YET_MSG}", warn=True)
            self.place_panel()
            return
        self.set_monitor(monitor_name)
        self._begin_cast(screen)

    def _begin_cast(self, screen: Screen):
        self._pending = screen
        self.cfg["last_screen"] = screen.ip
        save_config(self.cfg)
        self.panel.hide_mode_picker()
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

    # -- settings window -------------------------------------------------
    def _on_icon_theme_changed(self, name: str) -> None:
        """Repaint the live tray icon when the setting changes -- the icon is
        already persisted by the settings window."""
        self.setIcon(app_icon(name))

    def open_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsWindow()
            self.settings_window.icon_theme_changed.connect(self._on_icon_theme_changed)
            self.settings_window.check_for_updates_requested.connect(self.check_for_updates)
            self.settings_window.update_now_requested.connect(self.update_now)
            # Native QCheckBox signal, per settings_window.py's own docs.
            self.settings_window.startup_checkbox.toggled.connect(self._on_startup_toggled)

        # Re-sync every time the window is opened, not just on first
        # construction -- the Registry value (or a prior background update
        # check) may have changed since the window was last shown.
        self.settings_window.set_launch_at_startup(startup.is_enabled())
        if self._latest_update is not None:
            self._apply_update_result(self._latest_update)

        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_startup_toggled(self, enabled: bool):
        try:
            (startup.enable if enabled else startup.disable)()
        except RuntimeError as exc:  # non-Windows only, per startup.py
            self.panel.set_status(f"⚠ {exc}", warn=True)
            if self.settings_window is not None:
                self.settings_window.set_launch_at_startup(not enabled)

    # -- self-update ---------------------------------------------------------
    def check_for_updates(self):
        if getattr(sys, "frozen", False):
            if self.settings_window is not None:
                self.settings_window.set_update_status("Download the latest installer or AppImage from Releases.")
            return
        if self._update_check_worker is not None and self._update_check_worker.isRunning():
            return
        if self.settings_window is not None:
            self.settings_window.set_update_status("Checking for updates…")
        worker = updater.CallWorker(updater.check_for_update)
        worker.done.connect(self._on_update_check_done)
        worker.finished.connect(worker.deleteLater)
        self._update_check_worker = worker
        worker.start()

    def _on_update_check_done(self, result: updater.UpdateCheckResult):
        self._latest_update = result
        self._apply_update_result(result)

    def _apply_update_result(self, result: updater.UpdateCheckResult):
        if not result.ok:
            text = f"Update check failed: {result.error}"
            self.act_update_now.setVisible(False)
            self.setIcon(app_icon())
        elif result.update_available:
            text = f"Update available: {result.remote_short}"
            self.act_update_now.setVisible(True)
            self.setIcon(updater.badge_icon(app_icon()))
        else:
            text = f"Up to date ({result.local_short})."
            self.act_update_now.setVisible(False)
            self.setIcon(app_icon())

        if self.settings_window is not None:
            self.settings_window.set_update_status(
                text, available=result.ok and result.update_available, latest=result.remote_commit,
            )

    def update_now(self):
        if self._update_pull_worker is not None and self._update_pull_worker.isRunning():
            return
        self.act_update_now.setEnabled(False)
        if self.settings_window is not None:
            self.settings_window.update_now_btn.setEnabled(False)
        worker = updater.CallWorker(updater.run_git_pull)
        worker.done.connect(self._on_update_pull_done)
        worker.finished.connect(worker.deleteLater)
        self._update_pull_worker = worker
        worker.start()

    def _on_update_pull_done(self, message: str):
        self.act_update_now.setEnabled(True)
        success = message.startswith("Update pulled successfully")
        if self.settings_window is not None:
            self.settings_window.update_now_btn.setEnabled(True)
            self.settings_window.set_update_result(message, success=success)
            if success:
                self.settings_window.reload_changelog()
        if success:
            self.act_update_now.setVisible(False)
            self.setIcon(app_icon())
        self.panel.set_status(message, warn=not success)

    def quit(self):
        self.caster.stop()
        QTimer.singleShot(200, self.app.quit)
