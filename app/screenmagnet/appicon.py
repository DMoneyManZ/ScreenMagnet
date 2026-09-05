"""The app/tray icon, drawn in the colour the user picked.

Two things about this icon are not obvious:

* The shipped SVG strokes with ``currentColor``. Qt's SVG renderer does not
  resolve that keyword, so the colour has to be substituted for a real one
  before rendering or the glyph comes out unpainted.
* A QIcon built straight from an SVG *path* has an empty ``availableSizes()``,
  and Qt's StatusNotifier backend serialises the tray item's IconPixmap from
  exactly that list. Without baked-in sizes GNOME receives a blank image and
  the tray icon is invisible while the item still reports Status=Active.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from .config import load_config

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Label -> stroke colour. Labels are what the settings combo shows.
ICON_THEMES: dict[str, str] = {
    "Default": "#ffffff",   # white: correct on the dark shell panels this sits in
    "Dark": "#000000",      # black: for light panels
}
DEFAULT_ICON_THEME = "Default"

# Tray-relevant sizes, so availableSizes() is populated (see module docstring).
_SIZES = (16, 22, 24, 32, 48, 64)


def icon_theme_name(cfg: dict | None = None) -> str:
    """The configured theme label, falling back to the default if unset/unknown."""
    cfg = load_config() if cfg is None else cfg
    name = cfg.get("icon_theme", DEFAULT_ICON_THEME)
    return name if name in ICON_THEMES else DEFAULT_ICON_THEME


def _render_svg(colour: str) -> QIcon | None:
    svg = ASSETS / "screenmagnet.svg"
    if not svg.exists():
        return None
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None

    markup = svg.read_text().replace("currentColor", colour)
    renderer = QSvgRenderer(QByteArray(markup.encode()))
    if not renderer.isValid():
        return None

    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pm)
    return icon if icon.availableSizes() else None


def _drawn_fallback(colour: str) -> QIcon:
    """Last resort if the SVG is missing or QtSvg is unavailable."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(colour))
    p.drawRoundedRect(6, 14, 52, 36, 7, 7)
    p.setBrush(QColor(Qt.GlobalColor.transparent))
    p.end()
    return QIcon(pm)


def app_icon(theme: str | None = None) -> QIcon:
    """The application icon in the given (or configured) theme."""
    name = theme if theme in ICON_THEMES else icon_theme_name()
    colour = ICON_THEMES[name]
    return _render_svg(colour) or _drawn_fallback(colour)
