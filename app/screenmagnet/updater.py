"""Self-update helpers for ScreenMagnet: version check, tray badge, git pull.

This module is self-contained on purpose -- it is imported by the tray and/or
the settings window but does not import either of them, so it can be tested
and reasoned about on its own.

Update-check strategy
----------------------
We compare the local checkout's current commit against origin's latest with
plain ``git`` (``git rev-parse HEAD`` + ``git ls-remote <remote> <ref>``)
rather than calling the GitHub REST API. Reasons:

  * No token needed. GitHub's unauthenticated REST API is capped at 60
    requests/hour *per IP* -- easy to exhaust from a background tray app
    that might poll periodically, especially behind a shared/NAT IP.
  * ``git ls-remote`` isn't GitHub-specific: it talks to whatever
    ``origin`` actually is (GitHub today, a mirror or fork remote
    tomorrow) with no API-shape parsing to keep in sync.
  * It reuses a dependency the app needs anyway: "Update now" already has
    to shell out to ``git pull``, so there is no new tool to install or
    vendor just to check for updates.

The trade-off: this only answers "do the SHAs differ", not "what changed" or
"is this a real release vs. an in-progress commit". That's fine here -- the
settings window's changelog section (reading CHANGELOG.md) is what covers
"what changed"; this module only answers "is there anything new upstream".

Everything here does a network call to `origin` (`check_for_update`) or an
`os.rename`-class filesystem operation with network I/O (`run_git_pull`), so
callers should invoke both off the Qt GUI thread (a QThread/QTimer/etc.) --
this module deliberately does no threading of its own so it stays usable
from a plain script or a test as well as from Qt.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

__all__ = [
    "DEFAULT_REMOTE",
    "DEFAULT_REF",
    "CHECK_TIMEOUT",
    "PULL_TIMEOUT",
    "BADGE_COLOR",
    "BADGE_BORDER_COLOR",
    "TRAY_ICON_SIZES",
    "UpdateCheckResult",
    "find_repo_root",
    "check_for_update",
    "badge_pixmap",
    "badge_icon",
    "run_git_pull",
    "CallWorker",
]

# -- config -------------------------------------------------------------
DEFAULT_REMOTE = "origin"
# "HEAD" asks the remote for its default branch tip, so we don't need to
# know or hardcode the branch name (main/master/whatever) to compare against.
DEFAULT_REF = "HEAD"
CHECK_TIMEOUT = 8.0   # seconds; network call, must not hang a tray app
PULL_TIMEOUT = 60.0   # seconds; a real fetch+merge, give it more room

BADGE_COLOR = QColor(255, 140, 0)        # dark orange "update available" dot
BADGE_BORDER_COLOR = QColor(30, 30, 30)  # thin dark ring so it reads on light glyphs too
TRAY_ICON_SIZES = (16, 20, 24, 32, 48, 64)  # common Windows/Linux tray sizes

# Don't flash a console window behind a windowed (pythonw) GUI app when we
# shell out to git. Only meaningful on Windows; evaluated lazily so this
# module still imports cleanly on Linux (no CREATE_NO_WINDOW attribute there).
_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# -- repo location --------------------------------------------------------
def find_repo_root(start: Path | str | None = None) -> Path | None:
    """Walk upward from `start` (default: this file's own location) looking
    for a `.git` directory. Returns None if not inside a git checkout --
    e.g. a PyInstaller-frozen build that didn't ship its `.git` folder,
    in which case there is nothing to self-update against."""
    here = Path(start).resolve() if start is not None else Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git(args: Sequence[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_CREATIONFLAGS,
    )


# -- update check -----------------------------------------------------------
@dataclass
class UpdateCheckResult:
    """Result of comparing the local checkout against origin.

    `error` is set (and `update_available` forced False) whenever the check
    itself couldn't complete -- no git, no network, not a repo, etc. Callers
    should treat a non-None `error` as "unknown", not as "no update"."""

    update_available: bool
    local_commit: str | None
    remote_commit: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def local_short(self) -> str | None:
        return self.local_commit[:7] if self.local_commit else None

    @property
    def remote_short(self) -> str | None:
        return self.remote_commit[:7] if self.remote_commit else None


def check_for_update(
    repo_dir: Path | str | None = None,
    remote: str = DEFAULT_REMOTE,
    ref: str = DEFAULT_REF,
    timeout: float = CHECK_TIMEOUT,
) -> UpdateCheckResult:
    """Compare the local repo's HEAD against `remote`'s `ref` tip.

    `repo_dir` defaults to the checkout containing this file
    (`find_repo_root()`). Never raises -- network/git/parse failures come
    back as `UpdateCheckResult(error=...)` so a caller can show a status
    line without a try/except.
    """
    repo = Path(repo_dir).resolve() if repo_dir is not None else find_repo_root()
    if repo is None:
        return UpdateCheckResult(
            False, None, None,
            error="Not inside a git checkout -- can't check for updates.",
        )

    try:
        local = _git(["rev-parse", "HEAD"], repo, timeout)
    except FileNotFoundError:
        return UpdateCheckResult(False, None, None, error="git is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        return UpdateCheckResult(False, None, None, error="Timed out reading the local commit.")
    if local.returncode != 0:
        return UpdateCheckResult(
            False, None, None,
            error=(local.stderr or "git rev-parse HEAD failed").strip(),
        )
    local_commit = local.stdout.strip()

    try:
        remote_proc = _git(["ls-remote", remote, ref], repo, timeout)
    except FileNotFoundError:
        return UpdateCheckResult(False, local_commit, None, error="git is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        return UpdateCheckResult(
            False, local_commit, None,
            error="Timed out contacting origin (offline?).",
        )
    if remote_proc.returncode != 0:
        return UpdateCheckResult(
            False, local_commit, None,
            error=(remote_proc.stderr or "git ls-remote failed").strip(),
        )

    out = remote_proc.stdout.strip()
    first_line = out.splitlines()[0] if out else ""
    remote_commit = first_line.split()[0] if first_line else None
    if not remote_commit:
        return UpdateCheckResult(
            False, local_commit, None,
            error=f"origin has no ref matching {ref!r}.",
        )

    return UpdateCheckResult(
        update_available=local_commit != remote_commit,
        local_commit=local_commit,
        remote_commit=remote_commit,
    )


# -- tray icon badge ---------------------------------------------------------
def badge_pixmap(
    pixmap: QPixmap,
    *,
    diameter_ratio: float = 0.4,
    margin_ratio: float = 0.03,
    color: QColor = BADGE_COLOR,
    border_color: QColor | None = BADGE_BORDER_COLOR,
) -> QPixmap:
    """Return a *copy* of `pixmap` with a small solid-color dot composited
    onto its bottom-right corner. The source pixmap is not modified.

    Sized proportionally (not a fixed pixel size) so it stays a small corner
    accent rather than obscuring the icon's glyph at any tray icon size, and
    scales sanely across the 16px-64px range tray icons actually render at.
    """
    if pixmap.isNull():
        return pixmap

    result = QPixmap(pixmap)  # copies the underlying data; safe to paint on
    w, h = result.width(), result.height()
    short_side = min(w, h)
    diameter = max(4, round(short_side * diameter_ratio))
    margin = max(0, round(short_side * margin_ratio))
    x = w - diameter - margin
    y = h - diameter - margin

    painter = QPainter(result)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if border_color is not None:
            pen = QPen(border_color)
            pen.setWidthF(max(1.0, diameter * 0.12))
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(x, y, diameter, diameter)
    finally:
        painter.end()
    return result


def badge_icon(
    icon: QIcon,
    *,
    sizes: Sequence[int] | None = None,
    diameter_ratio: float = 0.4,
    margin_ratio: float = 0.03,
    color: QColor = BADGE_COLOR,
    border_color: QColor | None = BADGE_BORDER_COLOR,
) -> QIcon:
    """Same badge as `badge_pixmap`, applied across an icon's renderings.

    Builds a new QIcon (the input `icon` is left untouched) so the caller can
    swap the tray's icon out and back (`tray.setIcon(...)`) without losing
    the original. Renders at `sizes` (default: the icon's own reported
    sizes, falling back to common tray sizes for scalable/SVG-backed icons
    that report none) so the badge stays crisp at whatever size the tray
    actually draws.
    """
    candidate_sizes = list(sizes) if sizes else [s.width() for s in icon.availableSizes()]
    if not candidate_sizes:
        candidate_sizes = list(TRAY_ICON_SIZES)

    result = QIcon()
    for s in candidate_sizes:
        pm = icon.pixmap(QSize(s, s))
        if pm.isNull():
            continue
        result.addPixmap(
            badge_pixmap(
                pm,
                diameter_ratio=diameter_ratio,
                margin_ratio=margin_ratio,
                color=color,
                border_color=border_color,
            )
        )
    return result if not result.isNull() else icon


# -- update now (git pull) ---------------------------------------------------
def run_git_pull(
    repo_dir: Path | str | None = None,
    remote: str = DEFAULT_REMOTE,
    ref: str | None = None,
    timeout: float = PULL_TIMEOUT,
) -> str:
    """Run `git pull --ff-only` in the repo and return a short, human
    -readable result string describing success or failure.

    Deliberately does **not** restart or relaunch the app -- the caller
    (tray "Update now" handler) is expected to surface this string to the
    user and let them restart ScreenMagnet themselves. `--ff-only` refuses
    to create a merge commit or touch local changes; if the checkout has
    diverged or has local edits, this fails safely instead of doing
    something surprising to the user's working tree.

    `ref` is left as `None` by default so the pull follows the branch's
    already-configured upstream (the normal `git pull` behaviour) rather
    than assuming a branch name; pass one explicitly to override.
    """
    repo = Path(repo_dir).resolve() if repo_dir is not None else find_repo_root()
    if repo is None:
        return "Update failed: no git checkout found -- can't self-update this install."

    args = ["pull", "--ff-only", remote]
    if ref:
        args.append(ref)

    try:
        proc = _git(args, repo, timeout)
    except FileNotFoundError:
        return "Update failed: git is not installed or not on PATH."
    except subprocess.TimeoutExpired:
        return f"Update failed: git pull timed out after {int(timeout)}s."

    if proc.returncode == 0:
        out = proc.stdout.strip()
        summary = out.splitlines()[-1] if out else "Already up to date."
        return f"Update pulled successfully ({summary}). Please restart ScreenMagnet to use the new version."

    detail = (proc.stderr or proc.stdout or "unknown git error").strip()
    return f"Update failed: {detail}"


# -- Qt threading helper ------------------------------------------------------
class CallWorker(QThread):
    """Runs a zero-argument-friendly callable (``check_for_update`` or
    ``run_git_pull``) on a worker thread and emits its return value.

    This module's docstring is explicit that both of those functions must be
    invoked off the Qt GUI thread, but doesn't otherwise ship a way to do
    that -- every caller (the tray icon, and the standalone `--settings`
    launcher) needs the exact same few lines of QThread boilerplate, so it
    lives here once instead of being reinvented at each call site.

    Usage::

        worker = CallWorker(check_for_update)
        worker.done.connect(on_result)          # called with the return value
        worker.finished.connect(worker.deleteLater)
        worker.start()
    """

    done = Signal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        self.done.emit(self._fn(*self._args, **self._kwargs))
