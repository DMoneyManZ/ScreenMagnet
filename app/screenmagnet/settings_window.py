"""ScreenMagnet settings / about window.

A standalone QDialog: version + creator info, a GitHub/contact section, a
changelog reader, update-check UI, a "launch at startup" checkbox, a
dev-only donation stub, and copyright notices.

Scope note: this file owns UI only. It does NOT check GitHub for updates,
does NOT run git, and does NOT touch the Windows Registry -- whatever
constructs this window (tray.py's context menu, or a future `--settings`
entry point in __main__.py) wires those in through the hooks documented on
SettingsWindow below. Kept deliberately self-contained -- it does not import
tray.py -- so a lightweight `--settings`-only launch path can show just this
window without dragging in the caster/discovery/GStreamer stack.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

from PySide6 import QtSvg  # noqa: F401 -- side-effect import: registers the SVG
# icon-engine plugin (qsvgicon), same reasoning as tray.py's app_icon() --
# without this, QIcon(*.svg) can silently come back null on this PySide6 build.
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QDoubleValidator,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .appicon import ICON_THEMES, app_icon, icon_theme_name
from .config import update_config

# --- identity / links --------------------------------------------------------
APP_NAME = "ScreenMagnet"
CREATOR = "DMoneyManZ"
GITHUB_URL = "https://github.com/DMoneyManZ/ScreenMagnet"
CONTACT_EMAIL = "drmedison@icloud.com"

# app/screenmagnet/settings_window.py -> repo root
CHANGELOG_PATH = Path(__file__).resolve().parent.parent.parent / "CHANGELOG.md"
CHANGELOG_PLACEHOLDER = (
    "*No CHANGELOG.md yet.* Add one at the repo root and it will show up "
    "here automatically -- nothing fabricated in its place."
)

# ------------------------------------------------------------------------
# TEST/DEV-ONLY DONATION STUB. Do not ship this in a real release build.
# No real PayPal.me link exists yet, so this points at an obviously-fake
# placeholder. Nothing here charges or transmits anything -- clicking a
# button just opens this URL in the user's browser.
# TODO(pre-release): replace PAYPAL_DONATE_BASE with a real link, or remove
# the whole donation card, before ScreenMagnet ever ships as v1.0.
# ------------------------------------------------------------------------
PAYPAL_DONATE_BASE = "https://paypal.me/PLACEHOLDER"


def _card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A rounded section frame matching tray.Panel's dark-themed look:
    palette-driven styling only, so it re-themes with the OS instead of
    clashing with the existing popup."""
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(
        "#card { background: palette(alternate-base); border: 1px solid palette(mid);"
        " border-radius: 8px; }"
    )
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(6)
    if title:
        head = QLabel(title)
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        lay.addWidget(head)
    return frame, lay


class SettingsWindow(QDialog):
    """ScreenMagnet's settings/about window.

    This class is UI-only. Whoever constructs it owns:
      - actually checking GitHub for updates (git ls-remote / releases API)
      - actually running `git pull` when the user clicks "Update Now"
      - actually reading/writing the HKCU Run registry key for startup

    Integration hooks
    ------------------
    Update status (integrator drives the actual check):
        window.check_for_updates_requested   Signal()
            Emitted when the user clicks "Check for Updates". Connect this
            to your git ls-remote / GitHub releases-API check, then report
            the result back with set_update_status().
        window.set_update_status(text, *, available=False, latest=None)
            Call with the result of a check. `available=True` reveals the
            "Update Now" button; `text` is shown verbatim (e.g. "Update
            available: v0.90" or "Up to date (v0.84)"). `latest` is stashed
            on self._latest_known for the integrator's own reference.
        window.update_now_requested   Signal()
            Emitted when the user clicks "Update Now" (only reachable once
            set_update_status(available=True) has been called). Connect
            this to your `git pull` (or equivalent), then report back with
            set_update_result(). This window never restarts the app itself
            -- set_update_result()'s message should ask the user to do it
            manually.
        window.set_update_result(message, *, success=True)
            Call after an "Update Now" attempt finishes, success or not.

    Launch at startup (integrator drives the Registry read/write):
        window.startup_checkbox   QCheckBox
            "Launch ScreenMagnet at startup". Connect its native
            `.toggled(bool)` signal to your Run-key add/remove logic.
        window.set_launch_at_startup(enabled)
            Call once after construction, after reading the real Registry
            state, to reflect it in the UI. Uses blockSignals internally so
            this does NOT re-trigger `toggled` (avoids a spurious
            write-back of the value you just read).
        window.launch_at_startup() -> bool
            Convenience getter for the checkbox's current state.

    Changelog:
        window.reload_changelog()
            Re-reads CHANGELOG.md from the repo root. Public in case the
            integrator wants to refresh it after a successful update pull.
    """

    icon_theme_changed = Signal(str)
    check_for_updates_requested = Signal()
    update_now_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._latest_known: str | None = None

        self.setWindowTitle(f"{APP_NAME} Settings — v{__version__}")
        self.setWindowIcon(app_icon())
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(480, 620)
        self.resize(520, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        scroll.setWidget(body)

        root.addLayout(self._build_header())
        root.addWidget(self._build_about_card())
        root.addWidget(self._build_changelog_card())
        root.addWidget(self._build_update_card())
        root.addWidget(self._build_appearance_card())
        root.addWidget(self._build_startup_card())
        root.addWidget(self._build_donation_card())
        root.addWidget(self._build_copyright_card())
        root.addStretch(1)

        close_row = QHBoxLayout()
        close_row.setContentsMargins(16, 4, 16, 14)
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    # -- header ----------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        icon_label = QLabel()
        icon_label.setPixmap(app_icon().pixmap(48, 48))
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(APP_NAME)
        tf = title.font()
        tf.setBold(True)
        tf.setPointSize(tf.pointSize() + 4)
        title.setFont(tf)
        col.addWidget(title)

        # Dev/test version number the user chose explicitly -- v1.0 is
        # reserved for the real official release, so this stays visibly
        # below it (screenmagnet.__version__ in __init__.py).
        version = QLabel(f"v{__version__} (dev/test build)")
        version.setEnabled(False)
        col.addWidget(version)

        row.addLayout(col, 1)
        return row

    # -- about / creator / contact ----------------------------------------
    def _build_about_card(self) -> QFrame:
        frame, lay = _card("About")

        creator = QLabel(f"Created by {CREATOR}")
        lay.addWidget(creator)

        repo = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        repo.setOpenExternalLinks(True)
        repo.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lay.addWidget(repo)

        contact_head = QLabel("Contact")
        cf = contact_head.font()
        cf.setBold(True)
        contact_head.setFont(cf)
        lay.addWidget(contact_head)

        # mailto: link only -- opens the OS default mail client via
        # QDesktopServices under the hood. Nothing is sent programmatically.
        contact = QLabel(f'<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>')
        contact.setOpenExternalLinks(True)
        contact.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lay.addWidget(contact)

        return frame

    # -- changelog ---------------------------------------------------------
    def _build_changelog_card(self) -> QFrame:
        frame, lay = _card("Changelog")
        self.changelog_view = QTextBrowser()
        self.changelog_view.setOpenExternalLinks(True)
        self.changelog_view.setFrameShape(QFrame.Shape.NoFrame)
        self.changelog_view.setStyleSheet("background: transparent;")
        self.changelog_view.setFixedHeight(160)
        lay.addWidget(self.changelog_view)
        self.reload_changelog()
        return frame

    def reload_changelog(self) -> None:
        """Reads CHANGELOG.md from the repo root, if present. Shows a
        placeholder otherwise -- no invented history."""
        try:
            text = CHANGELOG_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        self.changelog_view.setMarkdown(text if text else CHANGELOG_PLACEHOLDER)

    # -- updates -----------------------------------------------------------
    def _build_update_card(self) -> QFrame:
        frame, lay = _card("Updates")

        self.update_status_label = QLabel("Update status unknown.")
        self.update_status_label.setWordWrap(True)
        lay.addWidget(self.update_status_label)

        self.update_result_label = QLabel("")
        self.update_result_label.setWordWrap(True)
        self.update_result_label.hide()
        lay.addWidget(self.update_result_label)

        btn_row = QHBoxLayout()
        self.check_updates_btn = QPushButton("Check for Updates")
        self.check_updates_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_updates_btn.clicked.connect(self.check_for_updates_requested.emit)
        btn_row.addWidget(self.check_updates_btn)

        self.update_now_btn = QPushButton("Update Now")
        self.update_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_now_btn.clicked.connect(self.update_now_requested.emit)
        self.update_now_btn.hide()  # only shown once set_update_status(available=True)
        btn_row.addWidget(self.update_now_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        return frame

    def set_update_status(self, text: str, *, available: bool = False, latest: str | None = None) -> None:
        """Integrator calls this with the result of a git ls-remote /
        GitHub releases-API check against origin."""
        self.update_status_label.setText(text)
        self.update_status_label.setStyleSheet("color: palette(link);" if available else "")
        self.update_now_btn.setVisible(available)
        self._latest_known = latest

    def set_update_result(self, message: str, *, success: bool = True) -> None:
        """Integrator calls this after an "Update Now" git-pull attempt
        finishes. Deliberately does not restart the app -- `message` should
        tell the user to restart manually."""
        self.update_result_label.setText(message)
        self.update_result_label.setStyleSheet("" if success else "color: palette(link-visited);")
        self.update_result_label.show()

    # -- appearance ----------------------------------------------------------
    def _build_appearance_card(self) -> QFrame:
        frame, lay = _card("Appearance")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Icon theme"))
        self.icon_theme_combo = QComboBox()
        self.icon_theme_combo.addItems(ICON_THEMES)
        self.icon_theme_combo.setCurrentText(icon_theme_name())
        self.icon_theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_theme_combo.currentTextChanged.connect(self._on_icon_theme_changed)
        row.addWidget(self.icon_theme_combo)
        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(
            "Colour of the tray and window icon. Default is white, which reads "
            "correctly on the dark panels most desktops use; Dark is for light ones."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        return frame

    def _on_icon_theme_changed(self, name: str) -> None:
        update_config(icon_theme=name)
        self.setWindowIcon(app_icon(name))
        self.icon_theme_changed.emit(name)

    # -- launch at startup ---------------------------------------------------
    def _build_startup_card(self) -> QFrame:
        frame, lay = _card("Startup")
        self.startup_checkbox = QCheckBox(f"Launch {APP_NAME} at startup")
        self.startup_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.startup_checkbox)

        hint = QLabel(
            "Adds or removes a per-user Registry Run key "
            "(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run). "
            "No background service, no scheduled task -- just this same "
            "tray app launching at sign-in."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        return frame

    def set_launch_at_startup(self, enabled: bool) -> None:
        """Integrator calls this once after reading the real Registry
        state, to reflect it in the UI without re-triggering `toggled`."""
        self.startup_checkbox.blockSignals(True)
        self.startup_checkbox.setChecked(enabled)
        self.startup_checkbox.blockSignals(False)

    def launch_at_startup(self) -> bool:
        return self.startup_checkbox.isChecked()

    # -- donations (TEST/DEV ONLY -- see module-level TODO) -----------------
    def _build_donation_card(self) -> QFrame:
        frame, lay = _card("Support ScreenMagnet")

        warn = QLabel(
            "TEST BUILD ONLY -- placeholder donation links below, not wired "
            "to a real PayPal account. Not present in any real release."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #d08a2c; font-weight: bold;")
        lay.addWidget(warn)

        btn_row = QHBoxLayout()
        for amount in (5, 10, 25):
            b = QPushButton(f"${amount}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, a=amount: self._open_donate_link(a))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom:"))
        self.donate_custom_amount = QLineEdit()
        self.donate_custom_amount.setPlaceholderText("Amount, e.g. 15")
        self.donate_custom_amount.setValidator(QDoubleValidator(0.01, 100000.0, 2))
        self.donate_custom_amount.setFixedWidth(90)
        custom_row.addWidget(self.donate_custom_amount)
        custom_btn = QPushButton("Donate")
        custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        custom_btn.clicked.connect(self._open_donate_custom)
        custom_row.addWidget(custom_btn)
        custom_row.addStretch(1)
        lay.addLayout(custom_row)

        self.donate_note = QLineEdit()
        self.donate_note.setPlaceholderText("Optional note")
        lay.addWidget(self.donate_note)

        return frame

    def _open_donate_link(self, amount: int) -> None:
        self._open_paypal_placeholder(str(amount))

    def _open_donate_custom(self) -> None:
        amount = self.donate_custom_amount.text().strip()
        if not amount:
            return
        self._open_paypal_placeholder(amount)

    def _open_paypal_placeholder(self, amount: str) -> None:
        """Opens the placeholder PayPal.me link (see PAYPAL_DONATE_BASE's
        TODO) in the user's default browser. Test/dev stub only -- nothing
        is charged or transmitted by ScreenMagnet itself."""
        url = f"{PAYPAL_DONATE_BASE}/{amount}"
        note = self.donate_note.text().strip()
        if note:
            url += f"?note={quote(note)}"
        QDesktopServices.openUrl(QUrl(url))

    # -- copyright / license -------------------------------------------------
    def _build_copyright_card(self) -> QFrame:
        frame, lay = _card("Copyright & License")

        # --- REAL notice: this is what should ship, matching repo LICENSE. -
        real = QLabel(
            f"Copyright (C) 2026 {CREATOR}. Licensed under the GNU General "
            "Public License v3.0 or later (GPL-3.0-or-later). See LICENSE."
        )
        real.setWordWrap(True)
        lay.addWidget(real)

        # --- GOOFY TEST-ONLY notice --------------------------------------
        # Verbatim per the user's request, for this dev/test build only.
        # It deliberately contradicts the real GPL-3.0 notice above (the
        # joke is the contradiction) and MUST be removed before any public
        # v1.0 release -- it is not a real copyright claim.
        goofy = QLabel("Copyright (C) 2026 ALL RIGHTS RESERVED. Magnetic Cyber Chameleon LLC")
        goofy.setWordWrap(True)
        gf = goofy.font()
        gf.setItalic(True)
        goofy.setFont(gf)
        lay.addWidget(goofy)

        goofy_tag = QLabel("^ test build only, goofy placeholder -- not real, remove before release")
        goofy_tag.setWordWrap(True)
        goofy_tag.setEnabled(False)
        lay.addWidget(goofy_tag)

        return frame


# -- manual smoke test: `py -m screenmagnet.settings_window` -----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SettingsWindow()
    win.set_update_status(f"Up to date (v{__version__}).")
    win.set_launch_at_startup(False)
    win.show()
    sys.exit(app.exec())
