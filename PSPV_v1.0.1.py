#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PSPV.py  —  Power System Plot Visualizer (PSPV)
# v1.0.0
from __future__ import annotations
__version__ = "1.0.1"

import os, sys, json, glob, importlib, re, math, platform, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Tuple

# ── Dependency check (run BEFORE importing third-party modules) ──
# Maps: import-name -> pip-install-name
_REQUIRED = {
    'numpy':      'numpy',
    'pandas':     'pandas',
    'matplotlib': 'matplotlib',
    'PyQt6':      'PyQt6',
}
# Optional — only needed to open PSS(E) .out/.outx files on Windows
_OPTIONAL = {
    'pssepath':   'pssepath',
}

def _pip_hint(packages):
    """Return an OS-appropriate pip install one-liner for the given packages."""
    pkgs = ' '.join(packages)
    system = platform.system()
    if system == 'Windows':
        return f'py -m pip install --upgrade {pkgs}'
    # macOS and Linux
    return f'python3 -m pip install --upgrade --user {pkgs}'

def _check_dependencies():
    missing = []
    for mod, pkg in _REQUIRED.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("─" * 60, file=sys.stderr)
        print("ERROR: Missing required Python packages:", file=sys.stderr)
        for pkg in missing:
            print(f"  • {pkg}", file=sys.stderr)
        print("\nInstall them with:\n", file=sys.stderr)
        print(f"  {_pip_hint(missing)}\n", file=sys.stderr)
        print("Full setup (fresh machine):", file=sys.stderr)
        print(f"  macOS:   {_pip_hint(list(_REQUIRED.values()))}", file=sys.stderr)
        all_win = list(_REQUIRED.values()) + ['pssepath']
        print(f"  Windows: py -m pip install --upgrade {' '.join(all_win)}", file=sys.stderr)
        print("─" * 60, file=sys.stderr)
        sys.exit(1)

    # Report optional (non-fatal)
    opt_missing = []
    for mod, pkg in _OPTIONAL.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            opt_missing.append(pkg)
    if opt_missing and platform.system() == 'Windows':
        print(f"[info] Optional package for PSS(E) .out support is missing: "
              f"{', '.join(opt_missing)}.\n"
              f"       Install with: {_pip_hint(opt_missing)}", file=sys.stderr)

_check_dependencies()

import numpy as np
import pandas as pd

# ── PyQt6 ──
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSplitter, QTabWidget, QListWidget, QListWidgetItem, QComboBox, QLineEdit, QPushButton,
    QLabel, QGroupBox, QRadioButton, QCheckBox, QSpinBox, QDoubleSpinBox,
    QFileDialog, QMessageBox, QInputDialog, QColorDialog, QDialog,
    QDialogButtonBox, QFormLayout, QTreeWidget, QTreeWidgetItem, QMenu,
    QStatusBar, QToolBar, QButtonGroup, QScrollArea, QSizePolicy, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize, QMimeData, QByteArray
from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence, QColor, QDrag

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib import font_manager
import matplotlib.text as mtext
import matplotlib.colors as mcolors
from matplotlib.patches import FancyBboxPatch

# ── PSS(E) dyntools bootstrap (pssepath first, fallback to manual path) ──
_bootstrap_info = {'last_error': None, 'preferred_suffix': None, 'available_versions': [], 'selected_version': None}

def _bootstrap_dyntools_via_pssepath(version=None):
    """Try pssepath (Windows); optionally pick a specific PSS(E) version."""
    try:
        import pssepath
    except ImportError as e:
        _bootstrap_info['last_error'] = f"pssepath not installed: {e}"
        return False
    try:
        versions = pssepath.get_pssepath_versions() if hasattr(pssepath, 'get_pssepath_versions') else []
        _bootstrap_info['available_versions'] = [str(v) for v in versions]
        if version:
            pssepath.add_pssepath(version)
            _bootstrap_info['selected_version'] = str(version)
        else:
            pssepath.add_pssepath()  # latest by default
            if versions:
                _bootstrap_info['selected_version'] = str(versions[-1])
        import dyntools  # noqa: F401
        return True
    except Exception as e:
        _bootstrap_info['last_error'] = f"pssepath failed: {e!r}"
        return False

def _bootstrap_dyntools_manual(psse_root):
    """Fallback: add a user-supplied PSS(E) install folder to sys.path."""
    if not psse_root:
        return False
    ps = f"{sys.version_info.major}{sys.version_info.minor}"
    _bootstrap_info['preferred_suffix'] = ps
    root = psse_root.strip().strip('"')
    candidates = [os.path.join(root, sub)
                  for sub in [f"PSSPY{ps}", "PSSPY311", "PSSPY310", "PSSPY39", "PSSPY38", "PSSPY"]]
    for p in candidates:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import dyntools  # noqa: F401
        return True
    except Exception as e:
        _bootstrap_info['last_error'] = f"manual bootstrap failed: {e!r}"
        return False

def _bootstrap_dyntools(psse_root_override=None, version=None):
    # Already loaded?
    try:
        import dyntools  # noqa: F401
        return True
    except ImportError:
        pass
    if _bootstrap_dyntools_via_pssepath(version=version):
        return True
    return _bootstrap_dyntools_manual(psse_root_override or os.environ.get("PSSE_ROOT", ""))

# Try once at startup (silent — failure only matters when user opens .out)
_bootstrap_dyntools()

# ── Data Sources ──
class DataSource:
    def list_columns(self) -> List[str]: raise NotImplementedError
    def get_series(self, name: str) -> np.ndarray: raise NotImplementedError
    def get_time_like(self) -> Optional[str]: return None
    def label(self) -> str: return "Data"

class CSVDataSource(DataSource):
    def __init__(self, path):
        self.path = path
        try: self.df = pd.read_csv(path, sep=None, engine='python')
        except Exception: self.df = pd.read_csv(path, delim_whitespace=True, engine='python')
        self.df.columns = [str(c).strip() for c in self.df.columns]
    def list_columns(self): return list(self.df.columns)
    def get_series(self, name): return self.df[name].to_numpy(dtype=float)
    def get_time_like(self):
        for c in self.df.columns:
            if str(c).strip().lower() in ("time","t","time[s]","sec","seconds"): return c
        return None
    def label(self): return os.path.basename(self.path)

class OutDataSource(DataSource):
    def __init__(self, path):
        self.path = path
        try: dyntools = importlib.import_module('dyntools')
        except Exception as e:
            raise ImportError(f"dyntools not found: {_bootstrap_info.get('last_error')}") from e
        ext = os.path.splitext(path)[1].lower()
        trials = [1,0] if ext=='.outx' else [0,1]
        chnf = None
        for v in trials:
            try: chnf = dyntools.CHNF(path, outvrsn=v); break
            except Exception: pass
        if chnf is None: raise ValueError("Failed to parse PSS(E) file.")
        self.short_title, self.chanid_dict, self.chandict = chnf.get_data()
        self._columns = (['time'] if 'time' in self.chandict else []) + \
            [f"{ch}: {self.chanid_dict.get(ch,f'Ch{ch}')}" for ch in sorted(
                k for k in self.chandict if isinstance(k,(int,np.integer)))]
    def list_columns(self): return self._columns
    def get_series(self, name):
        if name=='time': return np.asarray(self.chandict['time'],dtype=float)
        return np.asarray(self.chandict[int(name.split(':',1)[0].strip())],dtype=float)
    def get_time_like(self): return 'time' if 'time' in self.chandict else None
    def label(self): return os.path.basename(self.path)

class PLBDataSource(DataSource):
    def __init__(self, path):
        self.path = path
        with open(path,'r',encoding='utf-8',errors='ignore') as f: head=f.read(4096)
        if sum(1 for ch in head if ord(ch)<9 or (13<ord(ch)<32))/max(1,len(head))>0.2:
            raise ValueError("Binary .plb not supported.")
        self.df = pd.read_csv(path, sep=None, engine='python')
        self.df.columns = [str(c).strip() for c in self.df.columns]
    def list_columns(self): return list(self.df.columns)
    def get_series(self, name): return self.df[name].to_numpy(dtype=float)
    def get_time_like(self):
        for c in self.df.columns:
            if str(c).strip().lower() in ("time","t","sec","seconds"): return c
        return None
    def label(self): return os.path.basename(self.path)

# ── Helpers ──
@dataclass
class LineHandle:
    line: Line2D
    label: str
    source_key: str
    axes_index: int
    x_name: Optional[str] = None
    y_name: Optional[str] = None
    symbol: str = ''

LINE_STYLES = {'Solid':'-','Dashed':'--','Dotted':':','Dash-dot':'-.'}
LINE_STYLE_NAMES = {v:k for k,v in LINE_STYLES.items()}

def human_readable(val):
    if abs(val)>=1e6: return f"{val/1e6:.3f}M"
    if abs(val)>=1e3: return f"{val/1e3:.3f}k"
    if val==0 or 1e-3<=abs(val)<1e3: return f"{val:.6g}"
    return f"{val:.3e}"

PREFS_PATH = Path.home()/'.psse_visualizer_prefs.json'

def _next_symbol(existing):
    for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz':
        if ch not in existing: return ch
    return f"c{len(existing)}"

def calc_rise_time(t, y, t0, t1, pct_lo=0.1, pct_hi=0.9):
    m = (t>=t0)&(t<=t1); ts,ys = t[m],y[m]
    if ts.size<3: return None
    d = ys[-1]-ys[0]
    if abs(d)<1e-15: return None
    lo,hi = ys[0]+pct_lo*d, ys[0]+pct_hi*d
    if d>0: il,ih = np.where(ys>=lo)[0], np.where(ys>=hi)[0]
    else: il,ih = np.where(ys<=lo)[0], np.where(ys<=hi)[0]
    if il.size==0 or ih.size==0: return None
    return float(ts[ih[0]]-ts[il[0]])

def calc_settling_time(t, y, t0, t1, band_pct=0.02):
    """Settling time: time after which signal stays within band_pct of final value.
    Band is computed as percentage of the step change (y_final - y_initial),
    not of the absolute final value. Works for positive and negative steps."""
    m = (t >= t0) & (t <= t1)
    ts, ys = t[m], y[m]
    if ts.size < 3:
        return None
    y_init = ys[0]
    y_final = ys[-1]
    step_size = abs(y_final - y_init)
    # Band based on step change magnitude; fallback to absolute band if step is tiny
    if step_size > 1e-15:
        band = step_size * band_pct
    elif abs(y_final) > 1e-15:
        band = abs(y_final) * band_pct
    else:
        band = band_pct
    # Find last time the signal is outside the band around final value
    outside = np.where(np.abs(ys - y_final) > band)[0]
    if outside.size == 0:
        return 0.0  # already settled from the start
    last_outside_idx = outside[-1]
    if last_outside_idx >= ts.size - 1:
        return None  # never settles within the window
    # Settling time = time from start of window to first point after last excursion
    return float(ts[last_outside_idx + 1] - ts[0])

def calc_oscillation_freq(t, y, t0, t1):
    m = (t>=t0)&(t<=t1); ts,ys = t[m],y[m]
    if ts.size<4: return None
    ym = ys-np.mean(ys)
    cx = np.where(np.diff(np.sign(ym)))[0]
    if cx.size<2: return None
    per = np.diff(ts[cx])*2
    if per.size==0: return None
    ap = float(np.mean(per))
    return 1.0/ap if ap>1e-15 else None

class ExcelDataSource(DataSource):
    """Reads .xls / .xlsx. Uses pandas.read_excel which requires openpyxl
    (xlsx) or xlrd (legacy xls). If the file has multiple sheets, the first
    sheet is used. Columns are assumed to be numeric except for the time
    column (auto-detected like CSV)."""
    def __init__(self, path):
        self.path = path
        try:
            # sheet_name=0 → first sheet. Users with multi-sheet files can
            # just export the sheet they care about as CSV; keeping the UI
            # simple here.
            self.df = pd.read_excel(path, sheet_name=0)
        except ImportError as e:
            # Re-raise with a clearer install hint for the user
            raise ImportError(
                f"{e}. Excel support needs an engine package:\n"
                f"  {_pip_hint(['openpyxl'])}\n"
                f"  (for legacy .xls also install 'xlrd')"
            ) from e
        self.df.columns = [str(c).strip() for c in self.df.columns]

    def list_columns(self): return list(self.df.columns)
    def get_series(self, name): return self.df[name].to_numpy(dtype=float)
    def get_time_like(self):
        for c in self.df.columns:
            if str(c).strip().lower() in ("time", "t", "time[s]", "sec", "seconds"):
                return c
        return None
    def label(self): return os.path.basename(self.path)


class MatDataSource(DataSource):
    """Reads MATLAB .mat files (scipy-compatible, v7.2 or older).
    Exposes every numeric 1-D variable as a column. If a column named 'time',
    't', or 'Time' is present, it's used as the X axis."""
    def __init__(self, path):
        self.path = path
        try:
            from scipy.io import loadmat
        except ImportError as e:
            raise ImportError(
                f"MATLAB .mat support needs scipy:\n  {_pip_hint(['scipy'])}"
            ) from e
        try:
            raw = loadmat(path, squeeze_me=True, struct_as_record=False)
        except NotImplementedError as e:
            raise ValueError(
                "This .mat file looks like MATLAB v7.3 (HDF5-based). "
                "Either re-save it with '-v7' in MATLAB, or install h5py "
                "and use HDF5 support (not implemented here)."
            ) from e
        self._columns = {}
        for key, val in raw.items():
            if key.startswith('__'):
                continue
            arr = np.asarray(val)
            if arr.ndim == 2 and 1 in arr.shape:
                arr = arr.ravel()
            if arr.ndim == 1 and np.issubdtype(arr.dtype, np.number):
                self._columns[key] = arr
        if not self._columns:
            raise ValueError("No 1-D numeric variables found in the .mat file.")

    def list_columns(self): return list(self._columns.keys())
    def get_series(self, name): return np.asarray(self._columns[name], dtype=float)
    def get_time_like(self):
        for k in self._columns:
            if str(k).strip().lower() in ("time", "t", "sec", "seconds"):
                return k
        return None
    def label(self): return os.path.basename(self.path)


class ComtradeDataSource(DataSource):
    """Reads COMTRADE (.cfg + .dat pair, or combined .cff).
    Uses the 'comtrade' pip package.
    https://pypi.org/project/comtrade/
    The path may be either the .cfg or the .dat; both point to the same
    record, and the comtrade library resolves the other half automatically."""
    def __init__(self, path):
        self.path = path
        try:
            import comtrade as _comtrade
        except ImportError as e:
            raise ImportError(
                f"COMTRADE support needs the 'comtrade' package:\n"
                f"  {_pip_hint(['comtrade'])}"
            ) from e
        # comtrade.load() figures out the .cfg/.dat pairing from either path
        rec = _comtrade.load(path)
        self._rec = rec
        # Build column dict: time + every analog + every digital signal
        cols = {'time': np.asarray(rec.time, dtype=float)}
        for i, ch in enumerate(rec.analog_channel_ids or []):
            cols[str(ch)] = np.asarray(rec.analog[i], dtype=float)
        for i, ch in enumerate(rec.status_channel_ids or []):
            cols[str(ch)] = np.asarray(rec.status[i], dtype=float)
        self._columns = cols

    def list_columns(self): return list(self._columns.keys())
    def get_series(self, name): return np.asarray(self._columns[name], dtype=float)
    def get_time_like(self): return 'time'
    def label(self): return os.path.basename(self.path)


def _create_ds(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.out', '.outx'):
        return OutDataSource(path)
    if ext == '.plb':
        return PLBDataSource(path)
    if ext in ('.xls', '.xlsx'):
        return ExcelDataSource(path)
    if ext == '.mat':
        return MatDataSource(path)
    if ext in ('.cfg', '.dat', '.cff'):
        return ComtradeDataSource(path)
    # .csv, .txt, or anything else falls through to the CSV reader
    return CSVDataSource(path)


# ── Theme palettes ──
THEMES = {
    'dark': {
        'bg':         '#1e1e2e',
        'bg_alt':     '#181825',
        'panel':      '#313244',
        'border':     '#45475a',
        'text':       '#cdd6f4',
        'muted':      '#a6adc8',
        'accent':     '#89b4fa',
        'warn':       '#f9e2af',
        'error':      '#f38ba8',
        'gridline':   '#585b70',
    },
    'light': {
        'bg':         '#ffffff',
        'bg_alt':     '#f5f5f7',
        'panel':      '#eceef3',
        'border':     '#c9ccd3',
        'text':       '#1a1a1a',
        'muted':      '#555b66',
        'accent':     '#1f6feb',
        'warn':       '#b54708',
        'error':      '#c41e3a',
        'gridline':   '#d0d4dc',
    },
}

def _make_qss(pal):
    """Build the full Qt stylesheet for the given theme palette.

    Compact version: smaller fonts, tighter padding, working spin-box arrows.
    This prevents the left panel from dominating the screen on Windows,
    where default widget sizes are larger than on macOS.
    """
    return (
        f"QMainWindow {{ background: {pal['bg']}; }}"
        f"QWidget {{ background: {pal['bg']}; color: {pal['text']}; "
        f"font-size: 11px; }}"
        f"QGroupBox {{ border: 1px solid {pal['border']}; border-radius: 5px; "
        f"margin-top: 9px; padding: 6px 4px 3px 4px; font-weight: bold; color: {pal['accent']}; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}"
        f"QPushButton {{ background: {pal['panel']}; border: 1px solid {pal['border']}; "
        f"border-radius: 4px; padding: 3px 8px; color: {pal['text']}; "
        f"min-height: 18px; min-width: 40px; }}"
        f"QPushButton:hover {{ background: {pal['border']}; border-color: {pal['accent']}; }}"
        f"QPushButton:pressed {{ background: {pal['muted']}; }}"
        f"QPushButton[accent=\"true\"] {{ background: {pal['accent']}; color: {pal['bg']}; font-weight: bold; }}"
        f"QPushButton[accent=\"true\"]:hover {{ background: {pal['accent']}; }}"
        f"QLineEdit, QComboBox {{ background: {pal['panel']}; "
        f"border: 1px solid {pal['border']}; border-radius: 4px; padding: 3px 6px; "
        f"color: {pal['text']}; selection-background-color: {pal['accent']}; "
        f"min-height: 18px; min-width: 30px; }}"
        # Spin boxes: explicit up/down buttons with visible arrows
        # (default Qt on Windows sometimes renders blank up-arrows against dark bg)
        f"QSpinBox, QDoubleSpinBox {{ background: {pal['panel']}; "
        f"border: 1px solid {pal['border']}; border-radius: 4px; padding: 2px 4px; "
        f"color: {pal['text']}; min-height: 18px; min-width: 40px; }}"
        f"QSpinBox::up-button, QDoubleSpinBox::up-button {{"
        f" subcontrol-origin: border; subcontrol-position: top right;"
        f" width: 16px; border-left: 1px solid {pal['border']};"
        f" border-top-right-radius: 4px; background: {pal['border']}; }}"
        f"QSpinBox::down-button, QDoubleSpinBox::down-button {{"
        f" subcontrol-origin: border; subcontrol-position: bottom right;"
        f" width: 16px; border-left: 1px solid {pal['border']};"
        f" border-bottom-right-radius: 4px; background: {pal['border']}; }}"
        f"QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,"
        f" QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover "
        f"{{ background: {pal['muted']}; }}"
        # Custom CSS-drawn triangles so arrows render reliably on Windows
        f"QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{"
        f" image: none; width: 0; height: 0;"
        f" border-left: 4px solid transparent;"
        f" border-right: 4px solid transparent;"
        f" border-bottom: 5px solid {pal['text']}; }}"
        f"QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{"
        f" image: none; width: 0; height: 0;"
        f" border-left: 4px solid transparent;"
        f" border-right: 4px solid transparent;"
        f" border-top: 5px solid {pal['text']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QComboBox QAbstractItemView {{ background: {pal['panel']}; color: {pal['text']}; "
        f"selection-background-color: {pal['border']}; }}"
        f"QListWidget {{ background: {pal['panel']}; border: 1px solid {pal['border']}; "
        f"border-radius: 4px; color: {pal['text']}; }}"
        f"QListWidget::item {{ padding: 1px 4px; }}"
        f"QListWidget::item:selected {{ background: {pal['border']}; color: {pal['accent']}; }}"
        f"QListWidget::item:hover {{ background: {pal['border']}; }}"
        f"QTabWidget::pane {{ border: 1px solid {pal['border']}; border-radius: 4px; background: {pal['bg']}; }}"
        f"QTabBar::tab {{ background: {pal['panel']}; border: 1px solid {pal['border']}; "
        f"border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; "
        f"padding: 4px 12px; margin-right: 2px; color: {pal['muted']}; }}"
        f"QTabBar::tab:selected {{ background: {pal['bg']}; color: {pal['accent']}; "
        f"font-weight: bold; border-bottom: 2px solid {pal['accent']}; }}"
        f"QTabBar::tab:hover {{ background: {pal['border']}; }}"
        f"QStatusBar {{ background: {pal['bg_alt']}; color: {pal['muted']}; "
        f"border-top: 1px solid {pal['panel']}; padding: 2px; }}"
        f"QSplitter::handle {{ background: {pal['border']}; width: 3px; }}"
        f"QSplitter::handle:hover {{ background: {pal['accent']}; }}"
        f"QScrollArea {{ border: none; }}"
        f"QRadioButton, QCheckBox {{ color: {pal['text']}; spacing: 4px; }}"
        # NOTE: don't override QRadioButton/QCheckBox ::indicator width/height.
        # Qt disables native drawing once you do, and the selection dot/check
        # disappears on Windows unless you provide full image assets for
        # every state (:checked, :unchecked, :hover, etc.). Native is fine.
        f"QTreeWidget {{ background: {pal['panel']}; border: 1px solid {pal['border']}; "
        f"border-radius: 4px; color: {pal['text']}; }}"
        f"QTreeWidget::item:selected {{ background: {pal['border']}; }}"
        f"QHeaderView::section {{ background: {pal['panel']}; color: {pal['accent']}; "
        f"border: 1px solid {pal['border']}; padding: 3px; font-weight: bold; }}"
        f"QMenuBar {{ background: {pal['bg_alt']}; color: {pal['text']}; }}"
        f"QMenuBar::item {{ padding: 3px 10px; }}"
        f"QMenuBar::item:selected {{ background: {pal['border']}; }}"
        f"QMenu {{ background: {pal['panel']}; color: {pal['text']}; border: 1px solid {pal['border']}; padding: 4px; }}"
        f"QMenu::item {{ padding: 4px 16px 4px 16px; }}"
        f"QMenu::item:selected {{ background: {pal['border']}; }}"
        f"QLabel {{ padding: 1px; }}"
        f"QLabel#sectionLabel {{ color: {pal['accent']}; font-weight: bold; font-size: 10px; }}"
        f"QToolBar {{ background: {pal['bg_alt']}; border: none; spacing: 3px; padding: 2px; }}"
    )

def _detect_system_theme():
    """Return 'dark' or 'light' based on the OS preference, or 'dark' on failure."""
    try:
        system = platform.system()
        if system == 'Darwin':
            out = subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                                 capture_output=True, text=True, timeout=1)
            # Returns "Dark" (with exit 0) if dark; non-zero / empty if light
            if out.returncode == 0 and 'dark' in out.stdout.strip().lower():
                return 'dark'
            return 'light'
        if system == 'Windows':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return 'light' if val == 1 else 'dark'
            except Exception:
                return 'dark'
        # Linux / other — default to dark
        return 'dark'
    except Exception:
        return 'dark'

# ── Dark theme stylesheet (kept for initial load; full theme handled at runtime) ──
DARK_QSS = _make_qss(THEMES['dark'])


# ══════════════════════════════════════════════════════════════
# DRAGGABLE Y-AXIS LIST — drags column names onto subplots
# ══════════════════════════════════════════════════════════════
Y_MIME = 'application/x-graphviz-ycolumns'

class DraggableYList(QListWidget):
    def __init__(self, viz):
        super().__init__()
        self.viz = viz
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def mimeData(self, items):
        md = QMimeData()
        names = [it.text() for it in items]
        md.setData(Y_MIME, QByteArray('\n'.join(names).encode('utf-8')))
        md.setText('\n'.join(names))  # human-readable fallback
        return md


# ══════════════════════════════════════════════════════════════
# COLLAPSIBLE GROUP — section with ▼/▶ toggle header
# ══════════════════════════════════════════════════════════════
class CollapsibleGroup(QWidget):
    """A lightweight replacement for QGroupBox that can be collapsed via a
    header toggle button. The content area is a QWidget you can give any
    layout to via .content_layout."""
    def __init__(self, title, expanded=False, parent=None):
        super().__init__(parent)
        self._toggle = QPushButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._title = title
        self._content = QWidget()
        self._content.setVisible(expanded)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 6, 8, 8)
        self._content_layout.setSpacing(4)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 2)
        outer.setSpacing(2)
        outer.addWidget(self._toggle)
        outer.addWidget(self._content)
        self._toggle.toggled.connect(self._on_toggle)
        # Default style — overwritten by apply_theme once palette is available
        self.apply_theme(THEMES['dark'])
        self._update_label()

    def apply_theme(self, pal):
        self._toggle.setStyleSheet(
            f"QPushButton {{ text-align:left; padding:6px 10px; "
            f"background:{pal['bg_alt']}; border:1px solid {pal['border']}; "
            f"border-radius:6px; color:{pal['accent']}; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{pal['panel']}; }}"
            f"QPushButton:checked {{ background:{pal['panel']}; }}"
        )

    def _update_label(self):
        arrow = "▼" if self._toggle.isChecked() else "▶"
        self._toggle.setText(f"{arrow}  {self._title}")

    def _on_toggle(self, checked):
        self._content.setVisible(checked)
        self._update_label()

    @property
    def content_layout(self):
        return self._content_layout

    def setExpanded(self, expanded):
        self._toggle.setChecked(expanded)


# ══════════════════════════════════════════════════════════════
# PLOT TAB — holds figure, canvas, toolbar, line handles
# ══════════════════════════════════════════════════════════════
class PlotTab(QWidget):
    def __init__(self, parent_viz):
        super().__init__()
        self.viz = parent_viz
        # Pick current theme colours; fallback to dark if the visualiser
        # hasn't finished constructing yet.
        pal = THEMES.get(getattr(parent_viz, '_effective_theme', 'dark'), THEMES['dark'])
        self.fig = Figure(figsize=(10, 7), dpi=100, facecolor=pal['bg'])
        self.axes_list = [self.fig.add_subplot(111)]
        for ax in self.axes_list:
            self._style_ax(ax)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        # Style: keep bg transparent so theme shows through; when a custom
        # toggle action (Select/Hover) is checked, make the label bold with
        # an accent-colored underline — never change the fill color (that
        # breaks in light mode because the default "pressed" fill is too
        # light).
        self._apply_toolbar_style()
        # Add our custom tools to the matplotlib nav toolbar so they live
        # alongside the built-in Pan / Zoom buttons.
        self.toolbar.addSeparator()
        self.act_select = QAction("Select", self)
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)
        self.act_select.setToolTip("Click curves/legends without changing the view")
        self.act_select.triggered.connect(lambda _=False: parent_viz._tool_select())
        self.toolbar.addAction(self.act_select)
        self.act_hover = QAction("Hover", self)
        self.act_hover.setCheckable(True)
        self.act_hover.setChecked(False)
        self.act_hover.setToolTip("Show values on the curves while hovering")
        self.act_hover.triggered.connect(lambda checked: parent_viz._toggle_hover(checked))
        self.toolbar.addAction(self.act_hover)
        # Help button — opens shortcuts dialog
        self.act_help = QAction("Help", self)
        self.act_help.setToolTip("Keyboard shortcuts, requirements, and about")
        self.act_help.triggered.connect(lambda _=False: parent_viz._show_help_menu())
        self.toolbar.addAction(self.act_help)
        self.grid_shape = (1,1)
        self.lines: List[LineHandle] = []
        self.band_patches = []
        self.show_legend = True
        # Legend interaction state
        self.selected_legend_label: Optional[str] = None
        self.selected_legend_ax = None
        self._legend_close_artists = []  # list of (artist, ax, label) for the ✕ buttons
        # Hover + annotations
        self.hover_enabled = False
        self.hover_overlays = {}  # per-axes overlays: {ax: {'texts':{}, 'markers':{}, 'xhairs':[]}}
        self.annotations = []
        self.awaiting_annotation_click = False
        # Annotation drag state
        self._ann_drag = None          # currently-dragged annotation artist
        self._ann_drag_start = None    # (mouse_display_xy, initial xytext)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        # Enable drops from the Y-axis list onto this tab's canvas
        self.canvas.setAcceptDrops(True)
        self.canvas.dragEnterEvent = self._drag_enter
        self.canvas.dragMoveEvent = self._drag_move
        self.canvas.dropEvent = self._drop

        self.canvas.mpl_connect('button_press_event', self.viz._on_click)
        self.canvas.mpl_connect('button_release_event', self.viz._on_release)
        self.canvas.mpl_connect('scroll_event', self.viz._on_scroll)
        self.canvas.mpl_connect('motion_notify_event', self.viz._on_mouse_move)
        self.canvas.mpl_connect('pick_event', self.viz._on_pick)
        self.canvas.mpl_connect('key_press_event', self.viz._on_key)

    def _apply_toolbar_style(self):
        """Style the navigation toolbar so our custom checkable actions stay
        readable in both light and dark modes: checked buttons get bold text
        instead of a filled background."""
        self.toolbar.setStyleSheet(
            "QToolBar { background: transparent; border: none; spacing: 2px; }"
            "QToolButton { padding: 3px 8px; margin: 0; background: transparent; border: none; }"
            "QToolButton:hover { background: rgba(127,127,127,0.15); border-radius: 4px; }"
            "QToolButton:checked { font-weight: bold; "
            "border-bottom: 2px solid palette(highlight); background: transparent; }"
        )

    def _drag_enter(self, event):
        if event.mimeData().hasFormat(Y_MIME):
            event.acceptProposedAction()

    def _drag_move(self, event):
        if event.mimeData().hasFormat(Y_MIME):
            event.acceptProposedAction()

    def _drop(self, event):
        if not event.mimeData().hasFormat(Y_MIME):
            return
        raw = bytes(event.mimeData().data(Y_MIME)).decode('utf-8', errors='ignore')
        names = [n for n in raw.split('\n') if n]
        if not names:
            return
        # Map drop position (widget pixels) to the axes it falls on.
        # Use the Qt event position and scale by the canvas's device pixel ratio
        # so coordinates match matplotlib's renderer pixel space (HiDPI/Retina).
        try:
            pos = event.position()  # QPointF (widget-local)
            wx, wy = pos.x(), pos.y()
        except AttributeError:
            pos = event.pos()
            wx, wy = pos.x(), pos.y()
        target_ax = self._axes_at_widget_pos(wx, wy)
        if target_ax is None:
            target_ax = self.axes_list[0]
        self.viz._focused_axes = target_ax
        self.viz._update_focus()
        for n in names:
            self.viz._plot_one(n, target_ax)
        event.acceptProposedAction()

    def _axes_at_widget_pos(self, wx, wy):
        """Find which subplot the given canvas widget (Qt) coordinate falls in.

        Strategy: partition the canvas into grid cells that cover every pixel
        (including whitespace between subplots), then snap the drop to whichever
        cell contains (wx, wy). This way every drop has an unambiguous target,
        and axes-label / gutter regions are still assigned to the nearest plot.
        """
        if not self.axes_list:
            return None
        widget_w = self.canvas.width()
        widget_h = self.canvas.height()
        if widget_w <= 0 or widget_h <= 0:
            return None
        rows, cols = getattr(self, 'grid_shape', (1, 1))
        # Clamp indices to the valid range
        col = int(wx / widget_w * cols)
        row = int(wy / widget_h * rows)
        col = max(0, min(col, cols - 1))
        row = max(0, min(row, rows - 1))
        idx = row * cols + col
        if 0 <= idx < len(self.axes_list):
            return self.axes_list[idx]
        # Fallback: first axes
        return self.axes_list[0]

    def _style_ax(self, ax):
        pal = THEMES.get(getattr(self.viz, '_effective_theme', 'dark'), THEMES['dark'])
        ax.set_facecolor(pal['bg'])
        for sp in ax.spines.values():
            sp.set_color(pal['border'])
        ax.tick_params(colors=pal['muted'], which='both')
        ax.xaxis.label.set_color(pal['text'])
        ax.yaxis.label.set_color(pal['text'])
        ax.title.set_color(pal['text'])
        ax.grid(True, which='both', ls='--', lw=0.4, alpha=0.3, color=pal['gridline'])


# ══════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════
class Visualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Power System Plot Visualizer (PSPV) v{__version__}")
        self.resize(1560, 960)
        self.setMinimumSize(1000, 650)

        # State
        self.sources: Dict[str, DataSource] = {}
        self.active_source_key: Optional[str] = None
        self._focused_axes = None
        self._undo_stack = []
        self._drag_lh = None
        self._drag_src_ax = None
        # Theme: 'dark' | 'light' | 'system'. Effective theme resolved from this.
        self._theme_choice = 'system'
        self._effective_theme = _detect_system_theme()

        self._build_ui()
        self._build_menu()
        self._apply_theme()  # uses effective theme
        # Accept dropped files anywhere on the window
        self.setAcceptDrops(True)
        self.statusBar().showMessage(
            "Open a data file to begin (File → Open, or drag files onto the window).")

    # ── Helper to make styled group boxes ──
    def _group(self, title):
        g = QGroupBox(title)
        g.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return g

    @staticmethod
    def _tighten(layout):
        """Apply tight spacing/margins to a layout created inside a QGroupBox
        so the left-panel options sit close together."""
        layout.setSpacing(2)
        layout.setContentsMargins(4, 2, 4, 2)
        return layout

    def _accent_btn(self, text, callback):
        b = QPushButton(text)
        b.setProperty("accent", True)
        b.clicked.connect(callback)
        return b

    # ── Drag & drop of data files from the OS ─────────────────
    # Any path with one of these extensions is accepted.
    _DROP_EXTS = ('.csv', '.txt', '.out', '.outx', '.plb',
                  '.xls', '.xlsx', '.mat', '.cfg', '.dat', '.cff')

    def _urls_to_paths(self, urls):
        """Extract local file paths with supported extensions from a list of QUrls."""
        paths = []
        for u in urls:
            try:
                if not u.isLocalFile():
                    continue
                p = u.toLocalFile()
            except Exception:
                continue
            if not p:
                continue
            if os.path.splitext(p)[1].lower() in self._DROP_EXTS and os.path.isfile(p):
                paths.append(p)
        return paths

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() and self._urls_to_paths(md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() and self._urls_to_paths(md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()
        paths = self._urls_to_paths(md.urls()) if md.hasUrls() else []
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        loaded = []
        errors = []
        for p in paths:
            try:
                self._open_path(p)
                loaded.append(os.path.basename(p))
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        # Summary status
        if loaded and not errors:
            self.statusBar().showMessage(f"Loaded {len(loaded)} file(s): {', '.join(loaded)}")
        elif loaded and errors:
            self.statusBar().showMessage(
                f"Loaded {len(loaded)}, {len(errors)} failed. See dialog for details.")
            QMessageBox.warning(self, "Some files failed to load",
                                "\n".join(errors))
        elif errors:
            QMessageBox.critical(self, "Could not open dropped files",
                                 "\n".join(errors))

    # ══════════════════════════════════════════════════════════
    # BUILD UI
    # ══════════════════════════════════════════════════════════
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter = splitter
        self.setCentralWidget(splitter)

        # ── LEFT PANEL (scrollable) ──
        left_scroll = QScrollArea()
        self._left_scroll = left_scroll
        left_scroll.setWidgetResizable(True)
        # Allow the panel to be quite narrow on Windows where default widget
        # minimums (from native QPushButton, etc.) inflate the panel width.
        left_scroll.setMinimumWidth(320)
        # Windows default DPI (96) inflates widget sizeHints ~33% vs macOS.
        # Cap the left panel so it cannot consume a large fraction of the
        # window. User can still drag the splitter wider if they want.
        left_scroll.setMaximumWidth(350)
        left_w = QWidget()
        # Force a small minimum width on the inner widget so the scroll area
        # can actually shrink it (otherwise the sum of widget minimum sizes
        # keeps the panel wide on Windows).
        left_w.setMinimumWidth(180)
        left_lay = QVBoxLayout(left_w)
        left_lay.setSpacing(2)
        left_lay.setContentsMargins(4, 4, 4, 4)

        # Files
        g = self._group("Files")
        gl = self._tighten(QVBoxLayout(g))
        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(70)
        gl.addWidget(self.files_list)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)
        b = QPushButton("Open...")
        b.clicked.connect(self.open_file)
        btn_row.addWidget(b)
        b2 = QPushButton("Close")
        b2.setToolTip("Close the selected file")
        b2.clicked.connect(self._close_selected_file)
        btn_row.addWidget(b2)
        gl.addLayout(btn_row)
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(3)
        b3 = QPushButton("Reload")
        b3.setToolTip("Re-read the file from disk (data may have changed)")
        b3.clicked.connect(self._reload_selected_file)
        btn_row2.addWidget(b3)
        b4 = QPushButton("Refresh Curves")
        b4.setToolTip("Update plotted curves with reloaded data")
        b4.clicked.connect(self._refresh_curves_for_selected)
        btn_row2.addWidget(b4)
        gl.addLayout(btn_row2)
        left_lay.addWidget(g)

        # Active source
        g = self._group("Active Data File")
        gl = self._tighten(QVBoxLayout(g))
        self.source_combo = QComboBox()
        self.source_combo.currentTextChanged.connect(self._switch_source)
        gl.addWidget(self.source_combo)
        left_lay.addWidget(g)

        # X axis
        g = self._group("X-axis")
        gl = self._tighten(QVBoxLayout(g))
        self.x_combo = QComboBox()
        gl.addWidget(self.x_combo)
        left_lay.addWidget(g)

        # Y axis
        g = self._group("Y-axis  (drag onto subplot, or double-click)")
        gl = self._tighten(QVBoxLayout(g))
        self.y_list = DraggableYList(self)
        self.y_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.y_list.setMaximumHeight(140)
        self.y_list.setMinimumHeight(80)
        self.y_list.doubleClicked.connect(self._on_y_dblclick)
        gl.addWidget(self.y_list)
        left_lay.addWidget(g)

        # Plot mode — vertical stack of radio buttons to keep width narrow
        g = self._group("Plot Mode & Target")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(3)
        gl.setVerticalSpacing(2)
        gl.setContentsMargins(4, 2, 4, 2)
        self.mode_overlap = QRadioButton("Overlap"); self.mode_overlap.setChecked(True)
        self.mode_newtab = QRadioButton("New Tab")
        self.mode_grid = QRadioButton("Grid →")
        self.target_combo = QComboBox(); self.target_combo.setMinimumWidth(40)
        gl.addWidget(self.mode_overlap, 0, 0, 1, 2)
        gl.addWidget(self.mode_newtab, 1, 0, 1, 2)
        gl.addWidget(self.mode_grid, 2, 0)
        gl.addWidget(self.target_combo, 2, 1)
        gl.addWidget(self._accent_btn("Add Plot", self._add_plot), 3, 0, 1, 2)
        left_lay.addWidget(g)

        # Grid layout — two rows so we don't overflow
        g = self._group("Subplot Grid")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(3)
        gl.setVerticalSpacing(2)
        gl.setContentsMargins(4, 2, 4, 2)
        # Equal column stretches so Apply + Link X share the width evenly
        for _col in range(4):
            gl.setColumnStretch(_col, 1)
        gl.addWidget(QLabel("Rows:"), 0, 0)
        self.grid_rows = QSpinBox(); self.grid_rows.setRange(1, 4); self.grid_rows.setValue(1)
        self.grid_rows.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        gl.addWidget(self.grid_rows, 0, 1)
        gl.addWidget(QLabel("Cols:"), 0, 2)
        self.grid_cols = QSpinBox(); self.grid_cols.setRange(1, 4); self.grid_cols.setValue(1)
        self.grid_cols.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        gl.addWidget(self.grid_cols, 0, 3)
        b = QPushButton("Apply"); b.clicked.connect(self._apply_grid)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        gl.addWidget(b, 1, 0, 1, 3)
        self.link_x_cb = QCheckBox("Link X")
        self.link_x_cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        gl.addWidget(self.link_x_cb, 1, 3, 1, 2)
        left_lay.addWidget(g)

        # Curves list
        g = self._group("Curves — current tab")
        gl = self._tighten(QVBoxLayout(g))
        self.lines_list = QListWidget()
        self.lines_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lines_list.setMaximumHeight(140)
        self.lines_list.setMinimumHeight(70)
        self.lines_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lines_list.customContextMenuRequested.connect(self._lines_context)
        self.lines_list.doubleClicked.connect(self._line_dblclick)
        gl.addWidget(self.lines_list)
        # Buttons in a single tight row — slim padding lets all 5 fit
        br = QHBoxLayout()
        br.setSpacing(2)
        br.setContentsMargins(0, 0, 0, 0)
        for txt, fn in [("Show", lambda: self._set_vis(True)),
                        ("Hide", lambda: self._set_vis(False)),
                        ("Remove", self._remove_lines),
                        ("Color", self._change_color),
                        ("Style", self._change_style)]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            # Let buttons shrink as the panel narrows
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            br.addWidget(b)
        gl.addLayout(br)
        left_lay.addWidget(g)

        left_lay.addStretch()
        left_scroll.setWidget(left_w)
        splitter.addWidget(left_scroll)

        # ── CENTER (tabs) ──
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(lambda: (self._refresh_lines(), self._update_targets(), self._sync_legend_cb()))
        # Corner button: add a new empty plot tab
        new_tab_btn = QPushButton("+ New Tab")
        new_tab_btn.setToolTip("Create a new empty plot tab")
        new_tab_btn.clicked.connect(self._new_tab)
        new_tab_btn.setProperty("accent", True)
        self.tabs.setCornerWidget(new_tab_btn, Qt.Corner.TopRightCorner)
        splitter.addWidget(self.tabs)

        # ── RIGHT PANEL (scrollable) ──
        right_scroll = QScrollArea()
        self._right_scroll = right_scroll
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(230)
        # Cap right panel on Windows DPI for the same reason as left.
        right_scroll.setMaximumWidth(340)
        # No hard maximum — let the user resize via the splitter
        right_w = QWidget()
        right_w.setMinimumWidth(210)
        right_lay = QVBoxLayout(right_w)
        right_lay.setSpacing(4)
        right_lay.setContentsMargins(8,8,8,8)

        # Helper: wrap a widget in a CollapsibleGroup (default collapsed per user request)
        def _cg(title, expanded=False):
            cg = CollapsibleGroup(title, expanded=expanded)
            right_lay.addWidget(cg)
            return cg

        # Titles (start expanded since it has the legend toggles users hit often)
        cg = _cg("Titles & Labels", expanded=True)
        inner = QWidget(); gl = QFormLayout(inner); gl.setContentsMargins(0,0,0,0)
        self.title_edit = QLineEdit(); gl.addRow("Title:", self.title_edit)
        self.xlabel_edit = QLineEdit(); gl.addRow("X:", self.xlabel_edit)
        self.ylabel_edit = QLineEdit(); gl.addRow("Y:", self.ylabel_edit)
        b = QPushButton("Apply Titles"); b.clicked.connect(self._apply_titles); gl.addRow(b)
        # Legend toggles on a single row
        legend_row = QWidget(); lr = QHBoxLayout(legend_row)
        lr.setContentsMargins(0, 0, 0, 0); lr.setSpacing(10)
        self.show_legend_cb = QCheckBox("Show legend")
        self.show_legend_cb.setChecked(True)
        self.show_legend_cb.toggled.connect(self._toggle_legend)
        self.include_filename_cb = QCheckBox("Include filename")
        self.include_filename_cb.setChecked(True)
        self.include_filename_cb.toggled.connect(lambda _=False: self._update_legend())
        lr.addWidget(self.show_legend_cb)
        lr.addWidget(self.include_filename_cb)
        lr.addStretch()
        gl.addRow(legend_row)
        # Legend position selector
        self.legend_loc_combo = QComboBox()
        # Display name → matplotlib loc string
        self._legend_locs = [
            ("Best (auto)",     'best'),
            ("Upper right",     'upper right'),
            ("Upper left",      'upper left'),
            ("Lower left",      'lower left'),
            ("Lower right",     'lower right'),
            ("Right",           'right'),
            ("Center left",     'center left'),
            ("Center right",    'center right'),
            ("Lower center",    'lower center'),
            ("Upper center",    'upper center'),
            ("Center",          'center'),
            ("Outside right",   '__outside_right__'),
        ]
        for name, _ in self._legend_locs:
            self.legend_loc_combo.addItem(name)
        self.legend_loc_combo.setCurrentIndex(0)  # Best
        self.legend_loc_combo.currentIndexChanged.connect(lambda _=0: self._update_legend())
        gl.addRow("Legend position:", self.legend_loc_combo)
        cg.content_layout.addWidget(inner)

        # Fonts
        cg = _cg("Fonts")
        inner = QWidget(); gl = QFormLayout(inner); gl.setContentsMargins(0,0,0,0)
        self.font_size_spin = QSpinBox(); self.font_size_spin.setRange(6,36); self.font_size_spin.setValue(10)
        gl.addRow("Size:", self.font_size_spin)
        # Lazy-populate font families on first drop-down open.
        # Enumerating every font on the system (font_manager.ttflist) at startup
        # takes ~200–400 ms on Windows; deferring saves that from the launch path.
        self.font_combo = QComboBox()
        self.font_combo.addItem('DejaVu Sans')        # default matplotlib font
        self.font_combo.setCurrentText('DejaVu Sans')
        self._font_combo_populated = False
        _orig_show = self.font_combo.showPopup
        def _populate_and_show():
            if not self._font_combo_populated:
                try:
                    names = sorted(set(f.name for f in font_manager.fontManager.ttflist))
                    current = self.font_combo.currentText()
                    self.font_combo.blockSignals(True)
                    self.font_combo.clear()
                    self.font_combo.addItems(names)
                    if current in names:
                        self.font_combo.setCurrentText(current)
                    self.font_combo.blockSignals(False)
                except Exception:
                    pass
                self._font_combo_populated = True
            _orig_show()
        self.font_combo.showPopup = _populate_and_show
        gl.addRow("Family:", self.font_combo)
        b = QPushButton("Apply Fonts"); b.clicked.connect(self._apply_fonts); gl.addRow(b)
        cg.content_layout.addWidget(inner)

        # Axis range
        cg = _cg("Axis Range (blank = auto)")
        inner = QWidget(); gl = QGridLayout(inner); gl.setContentsMargins(0,0,0,0)
        self.xmin_e = QLineEdit(); self.xmax_e = QLineEdit()
        self.ymin_e = QLineEdit(); self.ymax_e = QLineEdit()
        gl.addWidget(QLabel("X min:"),0,0); gl.addWidget(self.xmin_e,0,1)
        gl.addWidget(QLabel("max:"),0,2); gl.addWidget(self.xmax_e,0,3)
        gl.addWidget(QLabel("Y min:"),1,0); gl.addWidget(self.ymin_e,1,1)
        gl.addWidget(QLabel("max:"),1,2); gl.addWidget(self.ymax_e,1,3)
        b = QPushButton("Apply Range"); b.clicked.connect(self._apply_range); gl.addWidget(b,2,0,1,2)
        b2 = QPushButton("Reset Auto"); b2.clicked.connect(self._reset_range); gl.addWidget(b2,2,2,1,2)
        cg.content_layout.addWidget(inner)

        # Math
        cg = _cg("Math / Derived Curves")
        inner = QWidget(); gl = QVBoxLayout(inner); gl.setContentsMargins(0,0,0,0)
        gl.addWidget(QLabel("Symbols [A,B,...] shown in curves list."))
        gl.addWidget(QLabel("Expression (e.g. A+B, sqrt(A), A*2.5):"))
        self.math_edit = QLineEdit()
        gl.addWidget(self.math_edit)
        mr = QHBoxLayout()
        mr.addWidget(QLabel("Target:"))
        self.math_target = QComboBox(); self.math_target.setMinimumWidth(40); mr.addWidget(self.math_target)
        b = QPushButton("New Tab"); b.clicked.connect(self._math_newtab); mr.addWidget(b)
        gl.addLayout(mr)
        gl.addWidget(self._accent_btn("Create Derived Curve", self._apply_math))
        cg.content_layout.addWidget(inner)

        # Annotations (see _build_annotations_panel — added below)
        cg = _cg("Annotations")
        inner = self._build_annotations_panel()
        cg.content_layout.addWidget(inner)

        # Band shading
        cg = _cg("Tolerance Band")
        inner = QWidget(); gl = QVBoxLayout(inner); gl.setContentsMargins(0,0,0,0)
        self.band_center_rb = QRadioButton("Center value:"); self.band_center_rb.setChecked(True)
        self.band_center_edit = QLineEdit("1.0"); self.band_center_edit.setMaximumWidth(80)
        r1 = QHBoxLayout(); r1.addWidget(self.band_center_rb); r1.addWidget(self.band_center_edit); r1.addStretch()
        gl.addLayout(r1)
        self.band_curve_rb = QRadioButton("Around curve (final value)")
        gl.addWidget(self.band_curve_rb)
        bg = QButtonGroup(self); bg.addButton(self.band_center_rb); bg.addButton(self.band_curve_rb)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("± %:")); self.band_pct_edit = QLineEdit("5.0"); self.band_pct_edit.setMaximumWidth(60); r2.addWidget(self.band_pct_edit)
        b = QPushButton("Apply"); b.clicked.connect(self._apply_band); r2.addWidget(b)
        b2 = QPushButton("Remove"); b2.clicked.connect(self._remove_band); r2.addWidget(b2)
        gl.addLayout(r2)
        cg.content_layout.addWidget(inner)

        # Measurements
        cg = _cg("Measurements")
        inner = QWidget(); gl = QVBoxLayout(inner); gl.setContentsMargins(0,0,0,0)
        mr = QHBoxLayout()
        mr.addWidget(QLabel("t₀:")); self.t0_edit = QLineEdit(); self.t0_edit.setMaximumWidth(80); mr.addWidget(self.t0_edit)
        mr.addWidget(QLabel("t₁:")); self.t1_edit = QLineEdit(); self.t1_edit.setMaximumWidth(80); mr.addWidget(self.t1_edit)
        gl.addLayout(mr)
        mr2 = QHBoxLayout()
        for txt,fn in [("Rise Time",lambda:self._measure('rise')),("Settling",lambda:self._measure('settle')),
                       ("Osc Freq",lambda:self._measure('freq')),("Stats",self._show_stats)]:
            b = QPushButton(txt); b.clicked.connect(fn); mr2.addWidget(b)
        gl.addLayout(mr2)
        cg.content_layout.addWidget(inner)

        # Export
        cg = _cg("Export")
        inner = QWidget(); gl = QFormLayout(inner); gl.setContentsMargins(0,0,0,0)
        self.dpi_spin = QSpinBox(); self.dpi_spin.setRange(100,1200); self.dpi_spin.setValue(300); self.dpi_spin.setSingleStep(50)
        gl.addRow("DPI:", self.dpi_spin)
        b = QPushButton("Save Image..."); b.clicked.connect(lambda: self._save_image(False)); gl.addRow(b)
        b2 = QPushButton("Export CSV..."); b2.clicked.connect(self._export_csv); gl.addRow(b2)
        cg.content_layout.addWidget(inner)

        right_lay.addStretch()
        right_scroll.setWidget(right_w)
        splitter.addWidget(right_scroll)

        splitter.setSizes([320, 900, 320])
        splitter.setStretchFactor(0, 0)   # left: fixed-ish
        splitter.setStretchFactor(1, 1)   # center: grow
        splitter.setStretchFactor(2, 0)   # right: fixed-ish
        # Allow collapse so the View menu toggles can hide panels entirely.
        splitter.setChildrenCollapsible(True)
        # Force sensible initial splitter sizes that work on both macOS (72 DPI)
        # and Windows (96 DPI). Ignore sizeHint() which reports very different
        # widths on the two OSes.
        left_default = 270
        right_default = 290
        total = 1560
        splitter.setSizes([left_default, total - left_default - right_default, right_default])

        # After the first paint, release the max-width caps so the user
        # can resize the panels wider if they want (via splitter drag).
        def _release_panel_caps():
            try:
                self._left_scroll.setMaximumWidth(16777215)    # Qt "unlimited"
                self._right_scroll.setMaximumWidth(16777215)
            except Exception:
                pass
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, _release_panel_caps)

        self._new_tab()

    # ── Pane visibility toggles ──
    def _toggle_left_panel(self):
        """Hide or show the left panel via the splitter."""
        try:
            sizes = self._splitter.sizes()
            if sizes[0] > 0:
                # Remember current width so we can restore it
                self._left_saved_width = sizes[0]
                sizes[1] += sizes[0]
                sizes[0] = 0
                self._act_toggle_left.setText("Show Left Panel")
            else:
                restore = getattr(self, '_left_saved_width', 260)
                sizes[1] = max(200, sizes[1] - restore)
                sizes[0] = restore
                self._act_toggle_left.setText("Hide Left Panel")
            self._splitter.setSizes(sizes)
        except Exception:
            pass

    def _toggle_right_panel(self):
        """Hide or show the right panel via the splitter."""
        try:
            sizes = self._splitter.sizes()
            if sizes[-1] > 0:
                self._right_saved_width = sizes[-1]
                sizes[1] += sizes[-1]
                sizes[-1] = 0
                self._act_toggle_right.setText("Show Right Panel")
            else:
                restore = getattr(self, '_right_saved_width', 300)
                sizes[1] = max(200, sizes[1] - restore)
                sizes[-1] = restore
                self._act_toggle_right.setText("Hide Right Panel")
            self._splitter.setSizes(sizes)
        except Exception:
            pass

    # ── Theme ──
    def _set_theme(self, choice):
        self._theme_choice = choice
        if choice == 'system':
            self._effective_theme = _detect_system_theme()
        else:
            self._effective_theme = choice
        self._apply_theme()

    def _apply_theme(self):
        pal = THEMES[self._effective_theme]
        # Update app stylesheet
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(_make_qss(pal))
        # Restyle every CollapsibleGroup header
        for cg in self.findChildren(CollapsibleGroup):
            cg.apply_theme(pal)
        # Re-style every tab's figure, axes, and any visible artefacts
        for i in range(self.tabs.count() if hasattr(self, 'tabs') else 0):
            tab = self.tabs.widget(i)
            if tab is None:
                continue
            tab.fig.set_facecolor(pal['bg'])
            for ax in tab.axes_list:
                ax.set_facecolor(pal['bg'])
                for sp in ax.spines.values():
                    sp.set_color(pal['border'])
                ax.tick_params(colors=pal['muted'], which='both')
                ax.xaxis.label.set_color(pal['text'])
                ax.yaxis.label.set_color(pal['text'])
                ax.title.set_color(pal['text'])
                ax.grid(True, which='both', ls='--', lw=0.4, alpha=0.3, color=pal['gridline'])
                # Rebuild legend colors if it exists
                leg = ax.get_legend()
                if leg is not None:
                    leg.get_frame().set_facecolor(pal['panel'])
                    leg.get_frame().set_edgecolor(pal['border'])
                    for txt in leg.get_texts():
                        # Keep selection highlight if this was selected
                        if getattr(tab, 'selected_legend_label', None) and \
                                tab.selected_legend_ax is ax:
                            display_map = getattr(leg, '_display_to_real', {})
                            real = display_map.get(txt.get_text(), txt.get_text())
                            if real == tab.selected_legend_label:
                                txt.set_color(pal['error'])
                                continue
                        txt.set_color(pal['text'])
            tab._apply_toolbar_style()
            tab.canvas.draw_idle()
        # Refresh focus highlight (uses accent color)
        self._update_focus()
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(
                f"Theme: {self._theme_choice.title()} "
                f"({self._effective_theme})")

    # ── Tool / mode buttons (pan / zoom / select) ──
    def _toolbar_mode(self, tab):
        """Normalised current toolbar mode name ('PAN', 'ZOOM', or '')."""
        m = tab.toolbar.mode
        s = getattr(m, 'name', None) or str(m)
        return s.upper()

    def _tool_pan(self):
        tab = self._tab()
        if tab is None: return
        tab.act_select.setChecked(False)
        tab.act_hover.setChecked(False)  # don't need to toggle hover state when switching tools
        if 'PAN' not in self._toolbar_mode(tab):
            tab.toolbar.pan()
        self.statusBar().showMessage("Pan mode: drag to move the view")

    def _tool_zoom(self):
        tab = self._tab()
        if tab is None: return
        tab.act_select.setChecked(False)
        if 'ZOOM' not in self._toolbar_mode(tab):
            tab.toolbar.zoom()
        self.statusBar().showMessage("Zoom mode: drag a rectangle to zoom in (right-drag to zoom out)")

    def _tool_select(self):
        tab = self._tab()
        if tab is None: return
        tab.act_select.setChecked(True)
        mode = self._toolbar_mode(tab)
        if 'PAN' in mode:
            tab.toolbar.pan()
        elif 'ZOOM' in mode:
            tab.toolbar.zoom()
        self.statusBar().showMessage("Select mode: click curves / legends without changing the view")

    # ── Hover values (snap cursor) ──
    def _toggle_hover(self, checked):
        tab = self._tab()
        if tab is None:
            return
        tab.hover_enabled = bool(checked)
        if hasattr(tab, 'act_hover'):
            tab.act_hover.setChecked(bool(checked))
        if not checked:
            self._clear_all_overlays(tab)
            tab.canvas.draw_idle()

    def _get_ax_overlays(self, tab, ax):
        if not hasattr(tab, 'hover_overlays') or tab.hover_overlays is None:
            tab.hover_overlays = {}
        ov = tab.hover_overlays.get(ax)
        if ov is None:
            ov = {'texts': {}, 'markers': {}, 'xhairs': []}
            tab.hover_overlays[ax] = ov
        ov.setdefault('texts', {})
        ov.setdefault('markers', {})
        ov.setdefault('xhairs', [])
        return ov

    def _clear_ax_overlays(self, tab, ax):
        ov = self._get_ax_overlays(tab, ax)
        for t in list(ov['texts'].values()):
            try: t.remove()
            except Exception: pass
        for m in list(ov['markers'].values()):
            try: m.remove()
            except Exception: pass
        for ln in list(ov['xhairs']):
            try: ln.remove()
            except Exception: pass
        ov['texts'].clear()
        ov['markers'].clear()
        ov['xhairs'].clear()

    def _clear_all_overlays(self, tab):
        if not hasattr(tab, 'hover_overlays') or tab.hover_overlays is None:
            return
        for ax in list(tab.hover_overlays.keys()):
            self._clear_ax_overlays(tab, ax)

    def _clear_hover_markers(self, tab):
        self._clear_all_overlays(tab)

    def _set_overlay_visible(self, ov, visible):
        for mk in ov.get('markers', {}).values():
            try: mk.set_visible(visible)
            except Exception: pass
        for t in ov.get('texts', {}).values():
            try: t.set_visible(visible)
            except Exception: pass
        for xh in ov.get('xhairs', []):
            try: xh.set_visible(visible)
            except Exception: pass

    def _hide_all_overlays(self, tab):
        for ov in getattr(tab, 'hover_overlays', {}).values():
            self._set_overlay_visible(ov, False)

    # ── Annotations ──
    def _build_annotations_panel(self):
        """Build and return the right-panel annotations widget."""
        w = QWidget(); gl = QVBoxLayout(w); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(4)

        # Type selector
        gl.addWidget(QLabel("Annotation type:"))
        tr = QHBoxLayout()
        self.ann_text_rb = QRadioButton("Text"); self.ann_text_rb.setChecked(True)
        self.ann_coord_rb = QRadioButton("Coordinates")
        ann_bg = QButtonGroup(self); ann_bg.addButton(self.ann_text_rb); ann_bg.addButton(self.ann_coord_rb)
        tr.addWidget(self.ann_text_rb); tr.addWidget(self.ann_coord_rb); tr.addStretch()
        gl.addLayout(tr)

        # Text content
        gl.addWidget(QLabel("Text (for Text annotation):"))
        self.ann_text_edit = QLineEdit()
        self.ann_text_edit.setPlaceholderText("e.g. Event at step response")
        gl.addWidget(self.ann_text_edit)

        # X coordinate (optional for text, required for coord)
        rx = QHBoxLayout()
        rx.addWidget(QLabel("At x ="))
        self.ann_x_edit = QLineEdit(); self.ann_x_edit.setPlaceholderText("leave blank to click")
        self.ann_x_edit.setMaximumWidth(120)
        rx.addWidget(self.ann_x_edit)
        rx.addStretch()
        gl.addLayout(rx)

        # Scope: selected subplot vs all subplots on the page
        gl.addWidget(QLabel("Apply to subplots:"))
        sr = QHBoxLayout()
        self.ann_scope_focus_rb = QRadioButton("Focused subplot"); self.ann_scope_focus_rb.setChecked(True)
        self.ann_scope_all_rb = QRadioButton("All subplots (same x)")
        scope_bg = QButtonGroup(self); scope_bg.addButton(self.ann_scope_focus_rb); scope_bg.addButton(self.ann_scope_all_rb)
        sr.addWidget(self.ann_scope_focus_rb); sr.addWidget(self.ann_scope_all_rb)
        gl.addLayout(sr)

        # Curve scope: which curves get annotated within each chosen subplot
        gl.addWidget(QLabel("Apply to curves:"))
        cr = QHBoxLayout()
        self.ann_curve_all_rb = QRadioButton("All visible"); self.ann_curve_all_rb.setChecked(True)
        self.ann_curve_nearest_rb = QRadioButton("Nearest only")
        self.ann_curve_pick_rb = QRadioButton("Pick…")
        curve_bg = QButtonGroup(self)
        curve_bg.addButton(self.ann_curve_all_rb)
        curve_bg.addButton(self.ann_curve_nearest_rb)
        curve_bg.addButton(self.ann_curve_pick_rb)
        cr.addWidget(self.ann_curve_all_rb)
        cr.addWidget(self.ann_curve_nearest_rb)
        cr.addWidget(self.ann_curve_pick_rb)
        gl.addLayout(cr)

        # Buttons
        br = QHBoxLayout()
        b1 = self._accent_btn("Add", self._add_annotation)
        b2 = QPushButton("Click-to-place"); b2.clicked.connect(self._start_click_annotation)
        b3 = QPushButton("Clear all"); b3.clicked.connect(self._clear_annotations)
        br.addWidget(b1); br.addWidget(b2); br.addWidget(b3)
        gl.addLayout(br)

        gl.addWidget(QLabel("Tip: annotations snap to each chosen curve's\n"
                            "nearest data point at the given x."))
        return w

    def _add_annotation(self):
        """Add an annotation at the given x coordinate (from text box)."""
        tab = self._tab()
        if tab is None: return
        x_txt = self.ann_x_edit.text().strip()
        if not x_txt:
            QMessageBox.information(self, "Annotation",
                "Enter an x value, or click 'Click-to-place' to pick on the plot.")
            return
        try:
            x = float(x_txt)
        except ValueError:
            QMessageBox.warning(self, "Annotation", "Invalid x value.")
            return
        self._place_annotation(tab, x)

    def _start_click_annotation(self):
        """Switch to click-to-place mode. Next canvas click will drop the annotation."""
        tab = self._tab()
        if tab is None: return
        tab.awaiting_annotation_click = True
        self.statusBar().showMessage("Click on a plot to place the annotation (Esc to cancel)")

    def _curves_for_annotation(self, ax, x, tab):
        """Return the list of line handles that should be annotated on `ax`
        based on the current curve-scope radio button selection."""
        visible = [lh for lh in tab.lines
                   if lh.line.axes is ax and lh.line.get_visible()]
        if not visible:
            return []
        # Nearest: single curve whose snapped x is closest to the requested x
        if getattr(self, 'ann_curve_nearest_rb', None) is not None \
                and self.ann_curve_nearest_rb.isChecked():
            best = None
            best_d = float('inf')
            for lh in visible:
                xd = np.asarray(lh.line.get_xdata(), dtype=float)
                if xd.size == 0:
                    continue
                idx = int(np.argmin(np.abs(xd - x)))
                d = abs(float(xd[idx]) - x)
                if d < best_d:
                    best_d = d
                    best = lh
            return [best] if best is not None else []
        # Pick: show a multi-select dialog with the curves on this subplot
        if getattr(self, 'ann_curve_pick_rb', None) is not None \
                and self.ann_curve_pick_rb.isChecked():
            return self._ask_user_pick_curves(visible)
        # Default: all visible curves
        return visible

    def _ask_user_pick_curves(self, visible_handles):
        """Show a small modal to pick which curves to annotate."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Pick curves to annotate")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Select one or more curves:"))
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for lh in visible_handles:
            lst.addItem(lh.line.get_label())
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return []
        # Map selected labels back to line handles
        chosen = {i.row() for i in lst.selectedIndexes()}
        return [visible_handles[i] for i in sorted(chosen)]

    def _place_annotation(self, tab, x, click_y=None, click_ax=None):
        is_text = self.ann_text_rb.isChecked()
        text = self.ann_text_edit.text().strip()
        scope_all = self.ann_scope_all_rb.isChecked()
        # Collect target axes
        if scope_all:
            target_axes = list(tab.axes_list)
        else:
            ax = click_ax or self._focused_axes or (tab.axes_list[0] if tab.axes_list else None)
            target_axes = [ax] if ax is not None else []
        if not target_axes:
            return
        pal = THEMES[self._effective_theme]
        ann_color = pal['warn']   # 'callout' color
        ann_bg = pal['panel']
        fs = max(8, self.font_size_spin.value() - 1)
        total_added = 0
        for ax in target_axes:
            curves = self._curves_for_annotation(ax, x, tab)
            if not curves:
                # No curves visible on this subplot — still drop a plain text
                # annotation at the requested x so the user's marker is visible.
                y0, y1 = ax.get_ylim()
                ax_x = x
                ax_y = (y0 + y1) / 2 if click_y is None else click_y
                label = text or f"x={human_readable(x)}"
                ann = ax.annotate(label, xy=(ax_x, ax_y), xytext=(10, 10),
                                  textcoords='offset points', fontsize=fs,
                                  color=ann_color,
                                  bbox=dict(boxstyle='round,pad=0.3',
                                            facecolor=ann_bg, edgecolor=ann_color, alpha=0.9))
                ann._is_annotation = True
                ann._annotation_ax = ax
                tab.annotations.append(ann)
                total_added += 1
                continue
            # One annotation per chosen curve, snapped to that curve's nearest x
            for lh in curves:
                xd = np.asarray(lh.line.get_xdata(), dtype=float)
                yd = np.asarray(lh.line.get_ydata(), dtype=float)
                if xd.size == 0:
                    continue
                idx = int(np.argmin(np.abs(xd - x)))
                x0, y0 = float(xd[idx]), float(yd[idx])
                col = lh.line.get_color()
                if is_text and text:
                    # Text mode with custom text: show the user's text and the
                    # coords in the curve's colour so you can tell which curve.
##                    label = f"{text}\n{lh.line.get_label()}: ({human_readable(x0)}, {human_readable(y0)})"
                    label = f"{text}\n({human_readable(x0)}, {human_readable(y0)})"
                else:
##                    label = f"{lh.line.get_label()}\n({human_readable(x0)}, {human_readable(y0)})"
                    label = f"({human_readable(x0)}, {human_readable(y0)})"
                ann = ax.annotate(label,
                                  xy=(x0, y0), xytext=(12, 12),
                                  textcoords='offset points', fontsize=fs,
                                  color=col,
                                  arrowprops=dict(arrowstyle='->', color=col, lw=0.9),
                                  bbox=dict(boxstyle='round,pad=0.3',
                                            facecolor=ann_bg, edgecolor=col, alpha=0.9))
                ann._is_annotation = True
                ann._annotation_ax = ax
                # Marker dot on the curve at the snapped point
                dot = ax.plot([x0], [y0], marker='o', markersize=6,
                              color=col, zorder=15)[0]
                tab.annotations.append(dot)
                tab.annotations.append(ann)
                total_added += 1
        tab.canvas.draw_idle()
        self.statusBar().showMessage(
            f"Added {total_added} annotation(s) at x={human_readable(x)}. "
            f"Drag any label to reposition its callout.")

    def _nearest_point(self, ax, x, tab):
        """Find the nearest data point (by x) among visible curves on `ax`.
        Returns (x, y, line_handle) or (None, None, None).
        Kept for callers outside the annotation panel (e.g. measurements)."""
        best_d = float('inf'); best = (None, None, None)
        for lh in tab.lines:
            if lh.line.axes is not ax or not lh.line.get_visible():
                continue
            xd = np.asarray(lh.line.get_xdata(), dtype=float)
            yd = np.asarray(lh.line.get_ydata(), dtype=float)
            if xd.size == 0:
                continue
            idx = int(np.argmin(np.abs(xd - x)))
            d = abs(xd[idx] - x)
            if d < best_d:
                best_d = d
                best = (float(xd[idx]), float(yd[idx]), lh)
        return best

    def _annotation_at_event(self, tab, event):
        """Return the annotation whose text label the cursor is over, or None."""
        for ann in getattr(tab, 'annotations', []):
            if not getattr(ann, '_is_annotation', False):
                continue
            try:
                bb = ann.get_window_extent(renderer=tab.canvas.get_renderer())
            except Exception:
                continue
            pad = 4
            if (bb.x0 - pad) <= event.x <= (bb.x1 + pad) and (bb.y0 - pad) <= event.y <= (bb.y1 + pad):
                return ann
        return None

    def _clear_annotations(self):
        tab = self._tab()
        if tab is None: return
        for artist in getattr(tab, 'annotations', []):
            try: artist.remove()
            except Exception: pass
        tab.annotations = []
        tab.canvas.draw_idle()

    def _sync_legend_cb(self):
        """Keep the 'Show legend' checkbox reflecting the current tab's state."""
        tab = self._tab()
        if tab is None or not hasattr(self, 'show_legend_cb'):
            return
        self.show_legend_cb.blockSignals(True)
        self.show_legend_cb.setChecked(getattr(tab, 'show_legend', True))
        self.show_legend_cb.blockSignals(False)

    def _pick_psse_version(self):
        """Let the user pick a PSS(E) version via pssepath (Windows) or a folder."""
        try:
            import pssepath
            versions = pssepath.get_pssepath_versions() if hasattr(pssepath, 'get_pssepath_versions') else []
        except Exception:
            versions = []
        if versions:
            items = [str(v) for v in versions]
            choice, ok = QInputDialog.getItem(self, "PSS(E) Version",
                                              "Select an installed PSS(E) version:",
                                              items, 0, False)
            if not ok:
                return
            if _bootstrap_dyntools(version=choice):
                QMessageBox.information(self, "PSS(E)",
                    f"Loaded PSS(E) {choice}\ndyntools is now available.")
            else:
                QMessageBox.warning(self, "PSS(E)",
                    f"Failed: {_bootstrap_info.get('last_error')}")
            return
        # No pssepath or no versions — fall back to manual folder selection
        folder = QFileDialog.getExistingDirectory(self, "Select PSS(E) install folder "
                                                        "(e.g. C:\\Program Files\\PTI\\PSSE35\\35.6)")
        if not folder:
            return
        if _bootstrap_dyntools(psse_root_override=folder):
            QMessageBox.information(self, "PSS(E)", "dyntools loaded successfully.")
        else:
            QMessageBox.warning(self, "PSS(E)",
                f"Could not load dyntools.\n\n{_bootstrap_info.get('last_error')}\n\n"
                f"Ensure you selected the PSS(E) root folder that contains a "
                f"PSSPY{sys.version_info.major}{sys.version_info.minor} subdirectory.")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("File")
        fm.addAction("Open...", QKeySequence("Ctrl+O"), self.open_file)
        fm.addAction("New Plot Tab", QKeySequence("Ctrl+T"), self._new_tab)
        fm.addSeparator()
        fm.addAction("Save Image...", lambda: self._save_image(False))
        fm.addAction("Export CSV...", self._export_csv)
        fm.addSeparator()
        fm.addAction("Configure PSS(E)...", self._pick_psse_version)
        fm.addSeparator()
        fm.addAction("Exit", self.close)

        em = mb.addMenu("Edit")
        em.addAction("Undo", QKeySequence("Ctrl+Z"), self._undo)
        # Add two delete shortcuts so both Del (full keyboards) and
        # Backspace (Mac compact keyboards) work as "delete selected".
        act_del1 = QAction("Delete Selected", self)
        act_del1.setShortcut(QKeySequence("Delete"))
        act_del1.triggered.connect(self._remove_lines)
        em.addAction(act_del1)
        act_del2 = QAction("Delete Selected (Backspace)", self)
        act_del2.setShortcut(QKeySequence("Backspace"))
        act_del2.triggered.connect(self._remove_lines)
        em.addAction(act_del2)
        em.addSeparator()
        act_rename = QAction("Rename Selected Legend...", self)
        act_rename.setShortcut(QKeySequence("F2"))
        act_rename.triggered.connect(self._rename_selected_legend)
        em.addAction(act_rename)

        vm = mb.addMenu("View")
        vm.addAction("Fit X-axis", QKeySequence("X"), self._fit_x)
        vm.addAction("Fit Y-axis", QKeySequence("Y"), self._fit_y)
        vm.addAction("Marquee Zoom", QKeySequence("M"), self._marquee)
        vm.addSeparator()
        # Pane toggles
        self._act_toggle_left = QAction("Hide Left Panel", self, checkable=True)
        self._act_toggle_left.setShortcut(QKeySequence("Ctrl+L"))
        self._act_toggle_left.triggered.connect(self._toggle_left_panel)
        vm.addAction(self._act_toggle_left)
        self._act_toggle_right = QAction("Hide Right Panel", self, checkable=True)
        self._act_toggle_right.setShortcut(QKeySequence("Ctrl+R"))
        self._act_toggle_right.triggered.connect(self._toggle_right_panel)
        vm.addAction(self._act_toggle_right)
        vm.addSeparator()
        theme_menu = vm.addMenu("Theme")
        from PyQt6.QtGui import QActionGroup
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for choice in ('dark', 'light', 'system'):
            a = QAction(choice.title(), self, checkable=True)
            if choice == self._theme_choice:
                a.setChecked(True)
            a.triggered.connect(lambda _=False, c=choice: self._set_theme(c))
            theme_group.addAction(a)
            theme_menu.addAction(a)

        hm = mb.addMenu("Help")
        hm.addAction("Shortcuts", self._show_shortcuts)
        hm.addAction("Requirements && Install", self._show_requirements)
        hm.addAction("About", lambda: QMessageBox.about(self, "About",
            f"Power System Plot Visualizer (PSPV) v{__version__}\n\n"
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
            f"OS: {platform.system()} {platform.release()}"))

    def _build_toolbar_REMOVED(self):
        """Removed — Select/Hover now live in each plot tab's navigation toolbar."""
        return

    # ── Tab management ──
    def _new_tab(self):
        tab = PlotTab(self)
        # Inherit legend visibility from current UI state if available
        if hasattr(self, 'show_legend_cb'):
            tab.show_legend = self.show_legend_cb.isChecked()
        self.tabs.addTab(tab, f"Plot {self.tabs.count()+1}")
        self.tabs.setCurrentWidget(tab)
        self._focused_axes = tab.axes_list[0]
        self._update_targets()
        # Make sure the new tab inherits the current theme (figure + toolbar).
        if hasattr(self, '_effective_theme'):
            self._apply_theme()
        return tab

    def _close_tab(self, idx):
        if self.tabs.count() > 1:
            self.tabs.removeTab(idx)
        self._refresh_lines()

    def _tab(self) -> PlotTab:
        return self.tabs.currentWidget()

    def _ax(self):
        tab = self._tab()
        if tab is None: return None
        if self._focused_axes in tab.axes_list: return self._focused_axes
        return tab.axes_list[0] if tab.axes_list else None

    def _update_targets(self):
        tab = self._tab()
        if tab is None: return
        r, c = tab.grid_shape
        vals = [f"{i},{j}" for i in range(1,r+1) for j in range(1,c+1)]
        self.target_combo.clear(); self.target_combo.addItems(vals)
        self.math_target.clear(); self.math_target.addItems(vals)

    def _get_target_ax(self, rc_str):
        tab = self._tab()
        try:
            r, c = map(int, rc_str.split(','))
            idx = (r-1)*tab.grid_shape[1] + (c-1)
            return tab.axes_list[max(0, min(idx, len(tab.axes_list)-1))]
        except Exception:
            return self._ax()

    def _apply_grid(self):
        tab = self._tab()
        if tab is None: return
        rows, cols = self.grid_rows.value(), self.grid_cols.value()
        if rows*cols > 16: QMessageBox.warning(self, "Grid", "Max 16 subplots."); return
        tab.band_patches = []
        tab.fig.clear(); tab.axes_list = []
        link_x = self.link_x_cb.isChecked() if hasattr(self, 'link_x_cb') else False
        shared = None
        for i in range(1, rows*cols+1):
            if link_x and shared is not None:
                ax = tab.fig.add_subplot(rows, cols, i, sharex=shared)
            else:
                ax = tab.fig.add_subplot(rows, cols, i)
                if link_x and shared is None:
                    shared = ax
            tab._style_ax(ax)
            tab.axes_list.append(ax)
        tab.grid_shape = (rows, cols)
        # Remember whether this tab is linking its x-axes so later range /
        # zoom / fit operations can apply to all subplots consistently.
        tab.link_x = bool(link_x)
        tab.canvas.draw_idle()
        self._focused_axes = tab.axes_list[0]
        self._update_targets()
        self._update_focus()

    def _update_focus(self):
        tab = self._tab()
        if tab is None: return
        pal = THEMES[self._effective_theme]
        for ax in tab.axes_list:
            for sp in ax.spines.values():
                if ax is self._focused_axes:
                    sp.set_linewidth(2.2); sp.set_color(pal['accent'])
                else:
                    sp.set_linewidth(0.8); sp.set_color(pal['border'])
        tab.canvas.draw_idle()

    # ── File operations ──
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Data File", "",
            "All supported (*.csv *.txt *.out *.outx *.plb *.xls *.xlsx *.mat *.cfg *.dat *.cff);;"
            "CSV / Text (*.csv *.txt);;"
            "Excel (*.xls *.xlsx);;"
            "PSS(E) (*.out *.outx *.plb);;"
            "MATLAB (*.mat);;"
            "COMTRADE (*.cfg *.dat *.cff);;"
            "All files (*)")
        if path: self._open_path(path)

    def _open_path(self, path):
        try:
            ds = _create_ds(path)
        except ImportError as e:
            # Missing optional reader package (scipy, comtrade, openpyxl, pssepath).
            # The exception message already contains a pip install hint.
            ext = os.path.splitext(path)[1].lower()
            extra = ""
            if ext in ('.out', '.outx'):
                extra = ("\n\nOn Windows, File → Configure PSS(E)... can also "
                         "pick an installed PSS(E) version automatically.")
            QMessageBox.critical(self, "Missing package",
                                 f"{e}{extra}")
            return
        except Exception as e:
            QMessageBox.critical(self, "Open", str(e)); return
        key = os.path.abspath(path)
        self.sources[key] = ds
        self._refresh_file_list()
        self._switch_source(key)
        self.statusBar().showMessage(f"Loaded: {ds.label()} — {len(ds.list_columns())} columns")

    def _refresh_file_list(self):
        self.files_list.clear()
        for k in self.sources: self.files_list.addItem(os.path.basename(k))
        self.source_combo.clear()
        self.source_combo.addItems(list(self.sources.keys()))
        if self.active_source_key: self.source_combo.setCurrentText(self.active_source_key)

    def _switch_source(self, key):
        if key not in self.sources: return
        self.active_source_key = key
        ds = self.sources[key]
        cols = ds.list_columns()
        self.x_combo.clear(); self.x_combo.addItems(cols)
        tc = ds.get_time_like()
        if tc and tc in cols: self.x_combo.setCurrentText(tc)
        self.y_list.clear(); self.y_list.addItems(cols)

    def _close_selected_file(self):
        items = self.files_list.selectedItems()
        if not items: return
        name = items[0].text()
        key = None
        for k in self.sources:
            if os.path.basename(k) == name: key = k; break
        if key is None: return
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            tab.lines = [lh for lh in tab.lines if lh.source_key != key or not (lh.line.remove() or True) or True]
            # Simplified: remove lines belonging to this file
            keep = []
            for lh in tab.lines:
                if lh.source_key == key:
                    try: lh.line.remove()
                    except: pass
                else: keep.append(lh)
            tab.lines = keep
            for ax in tab.axes_list: ax.relim(); ax.autoscale(True)
            tab.canvas.draw_idle()
        del self.sources[key]
        if self.active_source_key == key: self.active_source_key = None
        self._refresh_file_list(); self._refresh_lines()

    def _get_selected_file_key(self):
        """Return the full path key of the selected file in the files list, or None."""
        items = self.files_list.selectedItems()
        if not items: return None
        name = items[0].text()
        for k in self.sources:
            if os.path.basename(k) == name: return k
        return None

    def _reload_selected_file(self):
        """Re-read the selected file from disk (e.g. after simulation re-run)."""
        key = self._get_selected_file_key()
        if key is None:
            QMessageBox.information(self, "Reload", "Select a file first.")
            return
        try:
            ds = _create_ds(key)
            self.sources[key] = ds
            if self.active_source_key == key:
                self._switch_source(key)
            self.statusBar().showMessage(
                f"Reloaded: {os.path.basename(key)} — use 'Refresh Curves' to update plots")
        except Exception as e:
            QMessageBox.critical(self, "Reload", f"Failed to reload:\n{e}")

    def _refresh_curves_for_selected(self):
        """Update all plotted curves that came from the selected file with fresh data."""
        key = self._get_selected_file_key()
        if key is None:
            QMessageBox.information(self, "Refresh", "Select a file first.")
            return
        if key not in self.sources:
            QMessageBox.warning(self, "Refresh", "File not loaded.")
            return
        ds = self.sources[key]
        total = 0
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            updated = False
            for lh in getattr(tab, 'lines', []):
                if lh.source_key == key and lh.x_name and lh.y_name:
                    try:
                        x = ds.get_series(lh.x_name)
                        y = ds.get_series(lh.y_name)
                        lh.line.set_data(x, y)
                        total += 1
                        updated = True
                    except Exception:
                        pass
            if updated:
                for ax in tab.axes_list:
                    ax.relim(); ax.autoscale(True)
                self._update_legend()
                tab.canvas.draw_idle()
        self.statusBar().showMessage(f"Refreshed {total} curve(s) from {os.path.basename(key)}")

    # ── Plotting ──
    def _on_y_dblclick(self):
        ax = self._focused_axes
        if ax is None:
            # Fallback: plot to the first subplot of the current tab
            tab = self._tab()
            if tab and tab.axes_list:
                ax = tab.axes_list[0]
                self._focused_axes = ax
                self._update_focus()
            else:
                return
        for item in self.y_list.selectedItems():
            self._plot_one(item.text(), ax)

    def _add_plot(self):
        if not self.active_source_key:
            QMessageBox.warning(self, "Plot", "Open a data file first."); return
        sel = [item.text() for item in self.y_list.selectedItems()]
        if not sel or not self.x_combo.currentText():
            QMessageBox.warning(self, "Plot", "Select X and at least one Y."); return
        if self.mode_newtab.isChecked():
            tab = self._new_tab(); ax = tab.axes_list[0]
        elif self.mode_grid.isChecked():
            ax = self._get_target_ax(self.target_combo.currentText())
        else:
            ax = self._ax()
        if ax is None: return
        self._focused_axes = ax
        for y in sel: self._plot_one(y, ax)

    def _plot_one(self, y_name, ax):
        if not self.active_source_key: return
        ds = self.sources[self.active_source_key]
        x_name = self.x_combo.currentText()
        if not x_name or y_name == x_name: return
        tab = self._tab()
        try: x = ds.get_series(x_name); y = ds.get_series(y_name)
        except Exception as e: QMessageBox.critical(self, "Data", str(e)); return
        ax_idx = tab.axes_list.index(ax) if ax in tab.axes_list else 0
        file_label = ds.label()
        ln, = ax.plot(x, y, lw=1.5, label=f"{file_label} {y_name}")
        # Tag the line with structured metadata so legend filename stripping
        # works no matter what the (user-renamable) label becomes.
        ln._gv_file_label = file_label
        ln._gv_column = y_name
        sym = _next_symbol([lh.symbol for lh in tab.lines if lh.symbol])
        tab.lines.append(LineHandle(line=ln, label=ln.get_label(), source_key=self.active_source_key,
                                    axes_index=ax_idx, x_name=x_name, y_name=y_name, symbol=sym))
        ax.relim(); ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle()
        self._refresh_lines(); self._update_focus()
        self.statusBar().showMessage(f"Plotted {y_name} as [{sym}]")

    # ── Lines panel ──
    def _refresh_lines(self):
        self.lines_list.clear()
        tab = self._tab()
        if tab is None: return
        for lh in tab.lines:
            vis = '●' if lh.line.get_visible() else '○'
            sty = LINE_STYLE_NAMES.get(lh.line.get_linestyle(), '?')
            self.lines_list.addItem(f"[{lh.symbol}] {vis} Ax{lh.axes_index+1} {sty} | {lh.line.get_label()}")

    def _sel_lines(self):
        tab = self._tab()
        if tab is None: return []
        return [tab.lines[r.row()] for r in self.lines_list.selectedIndexes() if r.row() < len(tab.lines)]

    def _set_vis(self, v):
        for lh in self._sel_lines(): lh.line.set_visible(v)
        self._update_legend(); self._tab().canvas.draw_idle(); self._refresh_lines()

    def _rename_selected_legend(self):
        """Rename whichever legend entry is currently selected (if any).
        Also works if the user has a single row selected in the curves list."""
        tab = self._tab()
        if tab is None: return
        ax = tab.selected_legend_ax
        label = tab.selected_legend_label
        # Fallback: use the single-row selection from the left-side curves list
        if not (ax and label):
            sel = self._sel_lines()
            if len(sel) == 1:
                ax = sel[0].line.axes
                label = sel[0].line.get_label()
        if not (ax and label):
            QMessageBox.information(self, "Rename",
                "Click a legend entry once (or select a single row in the "
                "Curves list) first, then use Edit → Rename Selected Legend "
                "or press F2.")
            return
        new, ok = QInputDialog.getText(self, "Edit Legend", "New label:", text=label)
        if not (ok and new):
            return
        for lh in tab.lines:
            if lh.line.axes is ax and lh.line.get_label() == label:
                lh.line.set_label(new)
                lh.label = new
                break
        if tab.selected_legend_label == label:
            tab.selected_legend_label = new
        self._update_legend()
        self._refresh_lines()

    def _remove_lines(self):
        tab = self._tab()
        if tab is None: return
        # If a legend entry is currently selected (by clicking on it), delete
        # the corresponding curve rather than whatever is highlighted in the
        # left-side curves list. This gives the user a "click legend → Del"
        # workflow they asked for.
        sel_label = tab.selected_legend_label
        sel_ax = tab.selected_legend_ax
        if sel_label and sel_ax is not None:
            # Snapshot for undo
            for lh in tab.lines:
                if lh.line.axes is sel_ax and lh.line.get_label() == sel_label:
                    self._undo_stack.append({
                        'xd': lh.line.get_xdata().copy(), 'yd': lh.line.get_ydata().copy(),
                        'label': lh.line.get_label(), 'ax_idx': lh.axes_index,
                        'src': lh.source_key, 'color': lh.line.get_color(),
                        'ls': lh.line.get_linestyle(), 'lw': lh.line.get_linewidth(),
                        'sym': lh.symbol})
                    break
            self._remove_by_label(sel_ax, sel_label)
            tab.selected_legend_label = None
            tab.selected_legend_ax = None
            return
        idxs = sorted([r.row() for r in self.lines_list.selectedIndexes()], reverse=True)
        for i in idxs:
            if i >= len(tab.lines): continue
            lh = tab.lines[i]
            self._undo_stack.append({'xd':lh.line.get_xdata().copy(),'yd':lh.line.get_ydata().copy(),
                'label':lh.line.get_label(),'ax_idx':lh.axes_index,'src':lh.source_key,
                'color':lh.line.get_color(),'ls':lh.line.get_linestyle(),'lw':lh.line.get_linewidth(),'sym':lh.symbol})
            try: lh.line.remove()
            except: pass
            del tab.lines[i]
        for ax in tab.axes_list: ax.relim(); ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _undo(self):
        if not self._undo_stack: self.statusBar().showMessage("Nothing to undo."); return
        a = self._undo_stack.pop()
        tab = self._tab()
        ax_idx = min(a['ax_idx'], len(tab.axes_list)-1)
        ax = tab.axes_list[ax_idx]
        ln, = ax.plot(a['xd'],a['yd'],color=a['color'],ls=a['ls'],lw=a['lw'],label=a['label'])
        tab.lines.append(LineHandle(line=ln,label=a['label'],source_key=a['src'],axes_index=ax_idx,symbol=a.get('sym','')))
        ax.relim(); ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _lines_context(self, pos):
        m = QMenu(self)
        m.addAction("Show", lambda: self._set_vis(True))
        m.addAction("Hide", lambda: self._set_vis(False))
        m.addSeparator()
        m.addAction("Color...", self._change_color)
        m.addAction("Style...", self._change_style)
        m.addAction("Rename...", self._rename_line)
        m.addAction("Move to subplot...", self._move_line)
        m.addSeparator()
        m.addAction("Remove", self._remove_lines)
        m.exec(self.lines_list.mapToGlobal(pos))

    def _line_dblclick(self):
        sel = self._sel_lines()
        if sel: self._line_props(sel[0])

    def _line_props(self, lh):
        dlg = QDialog(self); dlg.setWindowTitle("Line Properties"); dlg.setMinimumWidth(380)
        lay = QFormLayout(dlg)
        le = QLineEdit(lh.line.get_label()); lay.addRow("Label:", le)
        ce = QLineEdit(mcolors.to_hex(lh.line.get_color())); lay.addRow("Color (hex):", ce)
        sc = QComboBox(); sc.addItems(list(LINE_STYLES.keys()))
        sc.setCurrentText(LINE_STYLE_NAMES.get(lh.line.get_linestyle(),'Solid')); lay.addRow("Style:", sc)
        we = QLineEdit(str(lh.line.get_linewidth())); lay.addRow("Width:", we)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); lay.addRow(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lh.line.set_label(le.text().strip() or lh.line.get_label()); lh.label = lh.line.get_label()
            try: lh.line.set_color(ce.text())
            except: pass
            lh.line.set_linestyle(LINE_STYLES.get(sc.currentText(),'-'))
            try: lh.line.set_linewidth(float(we.text()))
            except: pass
            self._update_legend(); self._tab().canvas.draw_idle(); self._refresh_lines()

    def _change_color(self):
        for lh in self._sel_lines():
            c = QColorDialog.getColor(QColor(mcolors.to_hex(lh.line.get_color())), self)
            if c.isValid(): lh.line.set_color(c.name())
        self._update_legend(); self._tab().canvas.draw_idle(); self._refresh_lines()

    def _change_style(self):
        sel = self._sel_lines()
        if not sel: return
        style, ok = QInputDialog.getItem(self, "Style", "Line style:", list(LINE_STYLES.keys()), 0, False)
        if ok:
            for lh in sel: lh.line.set_linestyle(LINE_STYLES[style])
            self._tab().canvas.draw_idle(); self._refresh_lines()

    def _rename_line(self):
        sel = self._sel_lines()
        if not sel: return
        n, ok = QInputDialog.getText(self, "Rename", "New label:", text=sel[0].line.get_label())
        if ok and n:
            sel[0].line.set_label(n); sel[0].label = n
            self._update_legend(); self._tab().canvas.draw_idle(); self._refresh_lines()

    def _move_line(self):
        sel = self._sel_lines()
        if not sel: return
        tab = self._tab()
        r,c = tab.grid_shape
        choices = [f"{i},{j}" for i in range(1,r+1) for j in range(1,c+1)]
        t, ok = QInputDialog.getItem(self, "Move", "Target (r,c):", choices, 0, False)
        if not ok: return
        target_ax = self._get_target_ax(t)
        new_idx = tab.axes_list.index(target_ax) if target_ax in tab.axes_list else 0
        for lh in sel:
            xd,yd = lh.line.get_xdata().copy(), lh.line.get_ydata().copy()
            col,ls,lw,lab = lh.line.get_color(),lh.line.get_linestyle(),lh.line.get_linewidth(),lh.line.get_label()
            try: lh.line.remove()
            except: pass
            ln, = target_ax.plot(xd,yd,color=col,ls=ls,lw=lw,label=lab)
            lh.line = ln; lh.axes_index = new_idx
        for ax in tab.axes_list: ax.relim(); ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _toggle_legend(self, checked):
        tab = self._tab()
        if tab is None:
            return
        tab.show_legend = bool(checked)
        if not checked:
            # Clear selection state and close buttons
            tab.selected_legend_label = None
            tab.selected_legend_ax = None
        self._update_legend()

    def _refresh_legend_selection_style(self, tab):
        """Apply selection highlighting WITHOUT rebuilding the legend.
        Used on single-click toggle so dblclick timing is preserved."""
        sel_label = tab.selected_legend_label
        sel_ax = tab.selected_legend_ax
        pal = THEMES[self._effective_theme]
        for ax in tab.axes_list:
            leg = ax.get_legend()
            if leg is None:
                continue
            display_map = getattr(leg, '_display_to_real', {})
            for txt in leg.get_texts():
                disp = txt.get_text()
                real = display_map.get(disp, disp)
                if sel_ax is ax and sel_label == real:
                    txt.set_color(pal['error'])
                    txt.set_fontweight('bold')
                else:
                    txt.set_color(pal['text'])
                    txt.set_fontweight('normal')
            # Highlight the legend frame when any of its entries is selected
            if sel_ax is ax and sel_label:
                leg.get_frame().set_edgecolor(pal['error'])
                leg.get_frame().set_linewidth(1.4)
            else:
                leg.get_frame().set_edgecolor(pal['border'])
                leg.get_frame().set_linewidth(1.0)
        tab.canvas.draw_idle()

    # ── Legend ──
    def _update_legend(self):
        """Redraw legends on every axes. Legend interaction is handled by hit-testing
        in _on_click, not via matplotlib picker events (which are flaky with legends)."""
        tab = self._tab()
        if tab is None: return

        # (Legacy close-button artists — clear any still present from older runs)
        for artist in getattr(tab, '_legend_close_artists', []):
            try: artist.remove()
            except Exception: pass
        tab._legend_close_artists = []

        show = getattr(tab, 'show_legend', True)
        include_file = getattr(self, 'include_filename_cb', None)
        include_file = include_file.isChecked() if include_file is not None else True
        pal = THEMES[self._effective_theme]

        for ax in tab.axes_list:
            existing = ax.get_legend()
            if existing is not None:
                try: existing.remove()
                except Exception: pass

            if not show:
                continue

            pairs = []
            for ln in ax.lines:
                if not ln.get_visible(): continue
                label = ln.get_label()
                if not label or label.startswith('_'): continue
                pairs.append((ln, label))
            if not pairs:
                continue

            # Build display labels (optionally strip file-name prefix).
            # Prefer per-line metadata tagged in _plot_one over string parsing
            # so file names with spaces still work correctly.
            display_pairs = []
            for ln, label in pairs:
                disp = label
                if not include_file:
                    file_label = getattr(ln, '_gv_file_label', None)
                    if file_label and label.startswith(file_label + ' '):
                        disp = label[len(file_label) + 1:]
                    else:
                        # Fallback: split on first space if first token has a dot
                        parts = label.split(' ', 1)
                        if len(parts) == 2 and ('.' in parts[0]):
                            disp = parts[1]
                display_pairs.append((ln, disp))

            handles = [p[0] for p in display_pairs]
            labels = [p[1] for p in display_pairs]

            # Get user-selected legend location
            try:
                loc_name, loc_val = self._legend_locs[self.legend_loc_combo.currentIndex()]
            except Exception:
                loc_val = 'best'

            legend_kwargs = dict(
                fontsize=max(6, self.font_size_spin.value()),
                framealpha=0.85,
                facecolor=pal['panel'],
                edgecolor=pal['border'],
                labelcolor=pal['text'],
            )
            if loc_val == '__outside_right__':
                # Anchor outside the axes on the right; caller will need space
                legend_kwargs['loc'] = 'center left'
                legend_kwargs['bbox_to_anchor'] = (1.02, 0.5)
                legend_kwargs['borderaxespad'] = 0.0
            else:
                legend_kwargs['loc'] = loc_val

            leg = ax.legend(handles, labels, **legend_kwargs)
            if leg is None:
                continue

            leg._display_to_real = dict(zip(labels, [p[1] for p in pairs]))
            # Re-apply selection styling if a legend entry was previously selected
            sel_real = tab.selected_legend_label
            for txt in leg.get_texts():
                real = leg._display_to_real.get(txt.get_text(), txt.get_text())
                if tab.selected_legend_ax is ax and sel_real == real:
                    txt.set_color(pal['error'])
                    txt.set_fontweight('bold')
            if tab.selected_legend_ax is ax and sel_real:
                leg.get_frame().set_edgecolor(pal['error'])
                leg.get_frame().set_linewidth(1.4)

        tab.canvas.draw_idle()

    def _legend_hit_test(self, event):
        """Return (axes, real_label) if the click landed on a legend entry,
        otherwise (None, None). The hit area is inflated generously so that
        bold/weight changes on selection don't cause subsequent clicks to miss."""
        tab = self._tab()
        if tab is None:
            return None, None
        # Use a renderer-aware hit box. Pad a bit more horizontally so that
        # when a text becomes bold on selection it is still hittable.
        H_PAD = 10
        V_PAD = 6
        for ax in tab.axes_list:
            leg = ax.get_legend()
            if leg is None:
                continue
            try:
                leg_bb = leg.get_window_extent()
            except Exception:
                continue
            # Quickly reject events outside the legend box (inflated)
            if not ((leg_bb.x0 - H_PAD) <= event.x <= (leg_bb.x1 + H_PAD)
                    and (leg_bb.y0 - V_PAD) <= event.y <= (leg_bb.y1 + V_PAD)):
                continue
            # Best-match by vertical proximity (text rows), then horizontal containment
            best = None
            best_dy = float('inf')
            for txt in leg.get_texts():
                try:
                    tbb = txt.get_window_extent(renderer=tab.canvas.get_renderer())
                except Exception:
                    continue
                ty = (tbb.y0 + tbb.y1) / 2
                dy = abs(ty - event.y)
                # Accept this text if the click's y is near its row and x is
                # within a generously padded horizontal band
                if dy < (tbb.y1 - tbb.y0) / 2 + V_PAD and \
                        (tbb.x0 - H_PAD) <= event.x <= (leg_bb.x1 + H_PAD):
                    if dy < best_dy:
                        best_dy = dy
                        display = txt.get_text()
                        real = getattr(leg, '_display_to_real', {}).get(display, display)
                        best = (ax, real)
            if best is not None:
                return best
        return None, None

    def _add_legend_close_button(self, tab, ax, leg, real_label):
        """(Deprecated) previously drew a ✕ near the selected legend entry.
        Delete-on-Del has replaced it; this is kept as a no-op for safety."""
        return

    # ── Mouse / keyboard interactions ──
    def _fit_x(self):
        ax = self._ax(); tab = self._tab()
        if ax is None or tab is None: return
        # When Link X is on, fit across every visible curve on every subplot
        # so all subplots share the same (full) x range.
        if getattr(tab, 'link_x', False):
            xmins, xmaxs = [], []
            for lh in tab.lines:
                if lh.line.get_visible():
                    xd = np.asarray(lh.line.get_xdata(), dtype=float)
                    xd = xd[np.isfinite(xd)]
                    if xd.size:
                        xmins.append(xd.min()); xmaxs.append(xd.max())
            if xmins:
                pad = (max(xmaxs)-min(xmins))*0.02 or 0.1
                lo, hi = min(xmins) - pad, max(xmaxs) + pad
                for a in tab.axes_list:
                    a.set_xlim(lo, hi)
            tab.canvas.draw_idle()
            self.statusBar().showMessage("Fit X to all visible curves (linked)")
            return
        xmins, xmaxs = [], []
        for lh in tab.lines:
            if lh.line.axes is ax and lh.line.get_visible():
                xd = np.asarray(lh.line.get_xdata(),dtype=float); xd = xd[np.isfinite(xd)]
                if xd.size: xmins.append(xd.min()); xmaxs.append(xd.max())
        if xmins:
            pad = (max(xmaxs)-min(xmins))*0.02 or 0.1
            ax.set_xlim(min(xmins)-pad, max(xmaxs)+pad)
        tab.canvas.draw_idle(); self.statusBar().showMessage("Fit X to visible curves")

    def _fit_y(self):
        ax = self._ax(); tab = self._tab()
        if ax is None or tab is None: return
        ymins, ymaxs = [], []
        for lh in tab.lines:
            if lh.line.axes is ax and lh.line.get_visible():
                yd = np.asarray(lh.line.get_ydata(),dtype=float); yd = yd[np.isfinite(yd)]
                if yd.size: ymins.append(yd.min()); ymaxs.append(yd.max())
        if ymins:
            pad = (max(ymaxs)-min(ymins))*0.02 or 0.1
            ax.set_ylim(min(ymins)-pad, max(ymaxs)+pad)
        tab.canvas.draw_idle(); self.statusBar().showMessage("Fit Y to visible curves")

    def _marquee(self):
        tab = self._tab()
        if tab: tab.toolbar.zoom()

    def _on_scroll(self, event):
        ax = event.inaxes
        if ax is None: return
        key = event.key or ''
        zoom_in = event.button == 'up'
        x0,x1 = ax.get_xlim(); y0,y1 = ax.get_ylim()
        cx = event.xdata if event.xdata is not None else (x0+x1)/2
        cy = event.ydata if event.ydata is not None else (y0+y1)/2
        if 'control' in key:
            zf = 0.85 if zoom_in else 1.18
            def z(lo,hi,c,f): s=(hi-lo)*f; return c-(c-lo)*(s/(hi-lo)), c+(hi-c)*(s/(hi-lo))
            if 'shift' in key: y0,y1 = z(y0,y1,cy,zf)
            else: x0,x1 = z(x0,x1,cx,zf); y0,y1 = z(y0,y1,cy,zf)
        else:
            f = 0.08; d = 1 if zoom_in else -1
            if 'shift' in key: s=(y1-y0)*f*d; y0+=s; y1+=s
            else: s=(x1-x0)*f*d; x0+=s; x1+=s
        ax.set_xlim(x0,x1); ax.set_ylim(y0,y1)
        self._tab().canvas.draw_idle()
        self._focused_axes = ax; self._update_focus()

    def _on_click(self, event):
        if event.inaxes is None: return
        tab = self._tab()
        if tab is None: return

        # Annotation click-to-place: intercept before anything else
        if getattr(tab, 'awaiting_annotation_click', False) and event.button == 1:
            tab.awaiting_annotation_click = False
            self._place_annotation(tab, event.xdata, click_y=event.ydata, click_ax=event.inaxes)
            return

        # Check if user clicked on an existing annotation — start drag
        if event.button == 1:
            ann = self._annotation_at_event(tab, event)
            if ann is not None:
                tab._ann_drag = ann
                tab._ann_drag_start = (
                    (event.x, event.y),   # mouse position in display coords
                    tuple(ann.get_position())  # current xytext (offset in points)
                )
                return

        # Legend hit-test first (select on single-click, rename on double-click)
        hit_ax, hit_label = self._legend_hit_test(event)
        if hit_ax is not None and hit_label is not None:
            # Double-click: rename the legend label
            if event.dblclick:
                default = hit_label
                for lh in tab.lines:
                    if lh.line.axes is hit_ax and lh.line.get_label() == hit_label:
                        default = lh.line.get_label()
                        break
                new, ok = QInputDialog.getText(self, "Edit Legend", "New label:", text=default)
                if ok and new:
                    for lh in tab.lines:
                        if lh.line.axes is hit_ax and lh.line.get_label() == hit_label:
                            lh.line.set_label(new)
                            lh.label = new
                            break
                    if tab.selected_legend_label == hit_label:
                        tab.selected_legend_label = new
                    self._update_legend()
                    self._refresh_lines()
                return
            if event.button == 3:
                # Right-click: remove immediately (fast path for mouse-only users)
                self._remove_by_label(hit_ax, hit_label)
                return
            # Left single-click: select the entry (press Del to delete)
            tab.selected_legend_label = hit_label
            tab.selected_legend_ax = hit_ax
            self._refresh_legend_selection_style(tab)
            self.statusBar().showMessage(
                f"Selected legend: '{hit_label}'. Press Del to delete the curve, "
                f"double-click to rename.")
            return

        # No legend hit — focus the clicked subplot and deselect any legend entry
        self._focused_axes = event.inaxes
        self._update_focus()
        if tab.selected_legend_label:
            tab.selected_legend_label = None
            tab.selected_legend_ax = None
            self._refresh_legend_selection_style(tab)

        if event.button == 1:
            ax = event.inaxes
            best_lh = None; best_d = float('inf')
            for lh in tab.lines:
                if lh.line.axes is not ax or not lh.line.get_visible(): continue
                xd = np.asarray(lh.line.get_xdata(),dtype=float)
                yd = np.asarray(lh.line.get_ydata(),dtype=float)
                if xd.size == 0: continue
                idx = np.argmin(np.abs(xd - event.xdata))
                d = abs(yd[idx] - event.ydata) if event.ydata is not None else float('inf')
                if d < best_d: best_d = d; best_lh = lh
            if best_lh:
                self._drag_lh = best_lh; self._drag_src_ax = ax

    def _on_release(self, event):
        tab = self._tab()
        # End annotation drag (if any)
        if tab is not None and getattr(tab, '_ann_drag', None) is not None:
            tab._ann_drag = None
            tab._ann_drag_start = None
            self.statusBar().showMessage("Annotation moved")
            return
        if self._drag_lh is None: return
        lh = self._drag_lh; self._drag_lh = None
        if event.inaxes is None or event.inaxes is self._drag_src_ax: return
        tab = self._tab(); target_ax = event.inaxes
        if target_ax not in tab.axes_list: return
        new_idx = tab.axes_list.index(target_ax)
        xd,yd = lh.line.get_xdata().copy(), lh.line.get_ydata().copy()
        col,ls,lw,lab = lh.line.get_color(),lh.line.get_linestyle(),lh.line.get_linewidth(),lh.line.get_label()
        try: lh.line.remove()
        except: pass
        ln, = target_ax.plot(xd,yd,color=col,ls=ls,lw=lw,label=lab)
        lh.line = ln; lh.axes_index = new_idx
        for ax in tab.axes_list: ax.relim(); ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _on_pick(self, event):
        # Reserved for future use — legend interaction is handled by hit-test
        # in _on_click (more reliable). Kept as a no-op to avoid breaking
        # canvas.mpl_connect('pick_event', ...).
        return

    def _on_key(self, event):
        tab = self._tab()
        if tab is None: return
        if event.key == 'escape' and getattr(tab, 'awaiting_annotation_click', False):
            tab.awaiting_annotation_click = False
            self.statusBar().showMessage("Annotation placement cancelled")

    def _remove_by_label(self, ax, label):
        tab = self._tab()
        for i,lh in enumerate(tab.lines):
            if lh.line.axes is ax and lh.line.get_label() == label:
                try: lh.line.remove()
                except: pass
                del tab.lines[i]; break
        for a in tab.axes_list: a.relim(); a.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _on_mouse_move(self, event):
        tab = self._tab()
        if tab is None:
            return
        # Dragging an annotation? Update its xytext offset (in points) based on delta.
        # This path must run even when the cursor briefly leaves the axes.
        if getattr(tab, '_ann_drag', None) is not None and event.x is not None:
            ann = tab._ann_drag
            (start_x, start_y), (ox, oy) = tab._ann_drag_start
            dpi = ann.figure.dpi if ann.figure is not None else 100
            # 1 point = 1/72 inch; event.x/y are in display pixels
            dx_pts = (event.x - start_x) * 72.0 / dpi
            dy_pts = (event.y - start_y) * 72.0 / dpi
            ann.set_position((ox + dx_pts, oy + dy_pts))
            tab.canvas.draw_idle()
            return
        if event.inaxes is None or event.xdata is None:
            # Off-axes: hide overlays (set_visible rather than remove)
            if tab is not None and getattr(tab, 'hover_enabled', False):
                self._hide_all_overlays(tab)
                tab.canvas.draw_idle()
            return
        if not getattr(tab, 'hover_enabled', False):
            self.statusBar().showMessage(
                f"x={human_readable(event.xdata)}, y={human_readable(event.ydata)}")
            return
        # Snap cursor using persistent artists per curve.
        # Each motion event updates positions + text IN PLACE and calls
        # draw_idle() once. No remove/recreate.
        ax = event.inaxes
        x = event.xdata
        ov = self._get_ax_overlays(tab, ax)
        fs = max(8, self.font_size_spin.value() - 1)
        ff = self.font_combo.currentText() if hasattr(self, 'font_combo') else 'DejaVu Sans'
        best = None
        count = 0
        active_lines = set()
        for line in list(ax.lines):
            if not line.get_visible():
                continue
            # Skip our own overlay artists so we don't recurse
            if getattr(line, '_is_hover_overlay', False):
                continue
            try:
                xd = np.asarray(line.get_xdata(), dtype=float)
                yd = np.asarray(line.get_ydata(), dtype=float)
                if xd.size == 0:
                    continue
                idx = int(np.argmin(np.abs(xd - x)))
                x0 = float(xd[idx]); y0 = float(yd[idx])
                col = line.get_color()
                active_lines.add(line)

                mk = ov['markers'].get(line)
                if mk is None:
                    mk, = ax.plot([x0], [y0], marker='o', markersize=5,
                                  color=col, alpha=0.85, zorder=1000)
                    mk._is_hover_overlay = True
                    ov['markers'][line] = mk
                else:
                    mk.set_data([x0], [y0])
                    mk.set_color(col)
                    mk.set_visible(True)

                txt = ov['texts'].get(line)
                content = f"x={human_readable(x0)}, y={human_readable(y0)}"
                if txt is None:
                    txt = ax.text(x0, y0, content, color=col,
                                  fontsize=fs, family=ff,
                                  bbox=dict(boxstyle='round,pad=0.2',
                                            fc='w', ec=col, alpha=0.6),
                                  ha='left', va='bottom', zorder=1001)
                    ov['texts'][line] = txt
                else:
                    txt.set_position((x0, y0))
                    txt.set_text(content)
                    txt.set_color(col)
                    bp = txt.get_bbox_patch()
                    if bp is not None:
                        bp.set_edgecolor(col)
                    txt.set_visible(True)

                d = abs(x - x0)
                if best is None or d < best[0]:
                    best = (d, x0, y0)
                count += 1
            except Exception:
                continue

        for line in list(ov['markers'].keys()):
            if line not in active_lines:
                try: ov['markers'][line].set_visible(False)
                except Exception: pass
        for line in list(ov['texts'].keys()):
            if line not in active_lines:
                try: ov['texts'][line].set_visible(False)
                except Exception: pass

        if best is not None:
            _, sx, sy = best
            if len(ov['xhairs']) < 2:
                for a in ov['xhairs']:
                    try: a.remove()
                    except Exception: pass
                ov['xhairs'].clear()
                v = ax.axvline(x=sx, color='0.3', linestyle=':',
                               linewidth=0.9, alpha=0.7, zorder=999)
                h = ax.axhline(y=sy, color='0.3', linestyle=':',
                               linewidth=0.9, alpha=0.7, zorder=999)
                v._is_hover_overlay = True
                h._is_hover_overlay = True
                ov['xhairs'] = [v, h]
            else:
                v, h = ov['xhairs'][0], ov['xhairs'][1]
                v.set_xdata([sx, sx]); v.set_visible(True)
                h.set_ydata([sy, sy]); h.set_visible(True)
        else:
            for a in ov['xhairs']:
                try: a.set_visible(False)
                except Exception: pass

        for other_ax, other_ov in getattr(tab, 'hover_overlays', {}).items():
            if other_ax is ax:
                continue
            self._set_overlay_visible(other_ov, False)

        tab.canvas.draw_idle()
        self.statusBar().showMessage(f"[SNAP] overlays on {count} curve(s)")
        return

    # ── Math ──
    def _eval_expr(self, expr, tab):
        sym_map = {}; x_ref = None
        for lh in tab.lines:
            if lh.symbol and lh.line.get_visible():
                sym_map[lh.symbol] = np.asarray(lh.line.get_ydata(),dtype=float)
                if x_ref is None: x_ref = np.asarray(lh.line.get_xdata(),dtype=float)
        if not sym_map: QMessageBox.warning(self,"Math","No visible curves."); return None,None
        ml = min(len(v) for v in sym_map.values())
        if x_ref is not None: x_ref = x_ref[:ml]
        ns = {k:v[:ml] for k,v in sym_map.items()}
        ns.update({'np':np,'sqrt':np.sqrt,'abs':np.abs,'log':np.log,'sin':np.sin,'cos':np.cos,'exp':np.exp,'pi':np.pi})
        try:
            with np.errstate(divide='ignore',invalid='ignore'):
                r = eval(expr,{"__builtins__":{}},ns)
            r = np.asarray(r,dtype=float)
            if r.shape == (): r = np.full(ml,float(r))
        except Exception as e: QMessageBox.critical(self,"Math",str(e)); return None,None
        if r.size==1: r = np.full(ml,float(r))
        return r, x_ref

    def _apply_math(self):
        tab = self._tab(); expr = self.math_edit.text().strip()
        if not expr: QMessageBox.warning(self,"Math","Enter an expression."); return
        r, x = self._eval_expr(expr, tab)
        if r is None: return
        label, ok = QInputDialog.getText(self,"Label","Legend:",text=expr)
        if not ok: return  # User cancelled — do nothing
        if not label.strip(): label = expr
        target_ax = self._get_target_ax(self.math_target.currentText())
        ax_idx = tab.axes_list.index(target_ax) if target_ax in tab.axes_list else 0
        ln, = target_ax.plot(x,r,lw=1.5,label=label)
        sym = _next_symbol([lh.symbol for lh in tab.lines if lh.symbol])
        tab.lines.append(LineHandle(line=ln,label=label,source_key='__derived__',axes_index=ax_idx,symbol=sym))
        target_ax.relim(); target_ax.autoscale(True)
        self._update_legend(); tab.canvas.draw_idle(); self._refresh_lines()

    def _math_newtab(self):
        tab = self._tab(); expr = self.math_edit.text().strip()
        if not expr: QMessageBox.warning(self,"Math","Enter an expression."); return
        r, x = self._eval_expr(expr, tab)
        if r is None: return
        label, ok = QInputDialog.getText(self,"Label","Legend:",text=expr)
        if not ok: return  # User cancelled — do nothing
        if not label.strip(): label = expr
        nt = self._new_tab(); ax = nt.axes_list[0]
        ln, = ax.plot(x,r,lw=1.5,label=label)
        sym = _next_symbol([lh.symbol for lh in nt.lines if lh.symbol])
        nt.lines.append(LineHandle(line=ln,label=label,source_key='__derived__',axes_index=0,symbol=sym))
        ax.relim(); ax.autoscale(True)
        self._update_legend(); nt.canvas.draw_idle(); self._refresh_lines()

    # ── Band, Range, Titles, Fonts, Measurements, Export ──
    def _apply_band(self):
        tab = self._tab(); ax = self._ax()
        if ax is None: return
        self._remove_band()
        try: pct = float(self.band_pct_edit.text())/100
        except: QMessageBox.warning(self,"Band","Invalid percentage."); return
        if self.band_curve_rb.isChecked():
            for lh in tab.lines:
                if lh.line.axes is ax and lh.line.get_visible():
                    yd = np.asarray(lh.line.get_ydata(),dtype=float)
                    yc = yd[np.isfinite(yd)]
                    if yc.size==0: continue
                    c = float(yc[-1]); b = abs(c)*pct if abs(c)>1e-15 else pct
                    col = lh.line.get_color()
                    tab.band_patches.append(ax.axhspan(c-b,c+b,alpha=0.08,color=col,zorder=0))
                    hl = ax.axhline(y=c,color=col,ls=':',lw=0.7,alpha=0.5); hl._is_crosshair=True
                    tab.band_patches.append(hl)
        else:
            try: c = float(self.band_center_edit.text())
            except: QMessageBox.warning(self,"Band","Invalid center."); return
            u,l = c*(1+pct), c*(1-pct)
            tab.band_patches.append(ax.axhspan(l,u,alpha=0.12,color='green',zorder=0))
            hl = ax.axhline(y=c,color='green',ls='--',lw=0.8,alpha=0.5); hl._is_crosshair=True
            tab.band_patches.append(hl)
        tab.canvas.draw_idle()

    def _remove_band(self):
        tab = self._tab()
        for p in getattr(tab,'band_patches',[]):
            try: p.remove()
            except: pass
        tab.band_patches = []; tab.canvas.draw_idle()

    def _apply_range(self):
        ax = self._ax()
        if ax is None: return
        tab = self._tab()
        try:
            xn = float(self.xmin_e.text()) if self.xmin_e.text().strip() else None
            xx = float(self.xmax_e.text()) if self.xmax_e.text().strip() else None
            yn = float(self.ymin_e.text()) if self.ymin_e.text().strip() else None
            yx = float(self.ymax_e.text()) if self.ymax_e.text().strip() else None
        except: QMessageBox.warning(self,"Range","Invalid numbers."); return
        # When Link X is on, apply the x range to every subplot on the tab.
        # (Y range is always per-axis since each subplot may show different
        # quantities.)
        link_x = getattr(tab, 'link_x', False)
        if xn is not None and xx is not None:
            if link_x and tab is not None:
                for a in tab.axes_list:
                    a.set_xlim(xn, xx)
            else:
                ax.set_xlim(xn, xx)
        if yn is not None and yx is not None:
            ax.set_ylim(yn, yx)
        tab.canvas.draw_idle()

    def _reset_range(self):
        ax = self._ax()
        if ax is None: return
        tab = self._tab()
        if getattr(tab, 'link_x', False):
            for a in tab.axes_list:
                a.relim(); a.autoscale(True)
        else:
            ax.relim(); ax.autoscale(True)
        for e in [self.xmin_e, self.xmax_e, self.ymin_e, self.ymax_e]:
            e.clear()
        tab.canvas.draw_idle()

    def _apply_titles(self):
        ax = self._ax()
        if ax is None: return
        pal = THEMES[self._effective_theme]
        t, xl, yl = self.title_edit.text().strip(), self.xlabel_edit.text().strip(), self.ylabel_edit.text().strip()
        if t: ax.set_title(t, color=pal['text'])
        if xl: ax.set_xlabel(xl, color=pal['text'])
        if yl: ax.set_ylabel(yl, color=pal['text'])
        self._tab().canvas.draw_idle()

    def _apply_fonts(self):
        ax = self._ax()
        if ax is None: return
        fs,ff = self.font_size_spin.value(), self.font_combo.currentText()
        for item in [ax.title,ax.xaxis.label,ax.yaxis.label]:
            item.set_fontsize(fs); item.set_fontfamily(ff)
        for lbl in ax.get_xticklabels()+ax.get_yticklabels():
            lbl.set_fontsize(max(6,fs-1)); lbl.set_fontfamily(ff)
        self._tab().canvas.draw_idle()

    def _get_times(self):
        try: return float(self.t0_edit.text()), float(self.t1_edit.text())
        except: QMessageBox.warning(self,"Measurement","Enter valid t₀ and t₁."); return None,None

    def _measure(self, kind):
        t0,t1 = self._get_times()
        if t0 is None: return
        tab = self._tab(); ax = self._ax()
        if ax is None: return
        results = []
        for lh in tab.lines:
            if lh.line.axes is not ax or not lh.line.get_visible(): continue
            t = np.asarray(lh.line.get_xdata(),dtype=float)
            y = np.asarray(lh.line.get_ydata(),dtype=float)
            n = lh.line.get_label()
            if kind=='rise':
                v = calc_rise_time(t,y,t0,t1)
                results.append(f"{n}: {v:.6g} s" if v is not None else f"{n}: N/A")
            elif kind=='settle':
                v = calc_settling_time(t,y,t0,t1)
                results.append(f"{n}: {v:.6g} s" if v is not None else f"{n}: N/A")
            elif kind=='freq':
                v = calc_oscillation_freq(t,y,t0,t1)
                results.append(f"{n}: {v:.4g} Hz" if v is not None else f"{n}: N/A")
        QMessageBox.information(self, kind.title(), '\n'.join(results) if results else "No visible curves.")

    def _show_stats(self):
        tab = self._tab(); ax = self._ax()
        if ax is None: return
        vis = [lh for lh in tab.lines if lh.line.axes is ax and lh.line.get_visible()]
        if not vis: QMessageBox.information(self,"Stats","No visible curves."); return
        lines = []
        for lh in vis:
            yd = np.asarray(lh.line.get_ydata(),dtype=float); yc = yd[np.isfinite(yd)]
            if yc.size==0: continue
            mn,mx,mean = float(yc.min()),float(yc.max()),float(yc.mean())
            rms = float(np.sqrt(np.mean(yc**2))); final = float(yc[-1])
            ov = ((mx-final)/abs(final))*100 if abs(final)>1e-15 else 0
            lines.append(f"{lh.line.get_label()}\n  Min={human_readable(mn)} Max={human_readable(mx)} "
                        f"Mean={human_readable(mean)} RMS={human_readable(rms)} Final={human_readable(final)} "
                        f"Overshoot={ov:.1f}%")
        QMessageBox.information(self, "Statistics", '\n\n'.join(lines))

    def _save_image(self, autofit):
        fname, _ = QFileDialog.getSaveFileName(self,"Save Image","","PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not fname: return
        fig = self._tab().fig
        if autofit:
            for ax in self._tab().axes_list: ax.relim(); ax.autoscale(True)
        fig.savefig(fname, dpi=self.dpi_spin.value(), bbox_inches='tight', facecolor=fig.get_facecolor())
        self.statusBar().showMessage(f"Saved {os.path.basename(fname)}")

    def _export_csv(self):
        tab = self._tab()
        if not tab.lines: QMessageBox.information(self,"Export","No curves."); return
        fname, _ = QFileDialog.getSaveFileName(self,"Export CSV","","CSV (*.csv)")
        if not fname: return
        data = {}
        for lh in tab.lines:
            p = lh.line.get_label().replace(',','_')
            data[f"{p}_x"] = pd.Series(np.asarray(lh.line.get_xdata(),dtype=float))
            data[f"{p}_y"] = pd.Series(np.asarray(lh.line.get_ydata(),dtype=float))
        pd.DataFrame(data).to_csv(fname,index=False)
        self.statusBar().showMessage(f"Exported to {os.path.basename(fname)}")

    def _show_help_menu(self):
        """Popup offering Shortcuts / Requirements / About — used by the in-plot Help button."""
        m = QMenu(self)
        m.addAction("Keyboard Shortcuts", self._show_shortcuts)
        m.addAction("Requirements && Install", self._show_requirements)
        m.addAction("About", lambda: QMessageBox.about(self, "About",
            f"Power System Plot Visualizer (PSPV) v{__version__}\n\n"
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
            f"OS: {platform.system()} {platform.release()}"))
        # Show near the current mouse cursor (use QCursor for a robust location)
        from PyQt6.QtGui import QCursor
        m.exec(QCursor.pos())

    def _show_shortcuts(self):
        QMessageBox.information(self, "Keyboard Shortcuts",
            "── Navigation ──\n"
            "Ctrl+O — Open data file\n"
            "Ctrl+T — New plot tab\n"
            "Ctrl+Z — Undo last remove\n"
            "Del — Remove selected curves\n"
            "\n"
            "── Viewport ──\n"
            "X — Fit X axis to visible curves\n"
            "Y — Fit Y axis to visible curves\n"
            "M — Toggle marquee (rectangular) zoom\n"
            "Scroll — Pan horizontally; Shift+Scroll — Pan vertically\n"
            "Ctrl+Scroll — Zoom around cursor\n"
            "Ctrl+Shift+Scroll — Zoom Y only\n"
            "\n"
            "── Mouse ──\n"
            "Drop data files onto the window — Open them "
            "(CSV, TXT, OUT, PLB, XLS, XLSX, MAT, COMTRADE)\n"
            "Drag Y-axis item → subplot — Plot that column\n"
            "Double-click Y list — Plot to focused (or 1st) subplot\n"
            "Double-click curve row — Edit properties\n"
            "Click legend entry — Select (press Del to remove curve)\n"
            "Double-click legend — Rename label\n"
            "Right-click legend entry — Remove curve\n"
            "Drag a curve between subplots — Click + drop\n"
            "Drag an annotation label — Adjust callout position\n"
            "Right-click curve list — Context menu\n"
            "\n"
            "── Other ──\n"
            "Esc — Cancel annotation click-to-place\n"
            "Top toolbar — Select / Pan / Zoom / Hover Values")

    def _show_requirements(self):
        sys_info = (f"{platform.system()} {platform.release()}  "
                    f"(Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})")
        macos_linux = _pip_hint(['numpy', 'pandas', 'matplotlib', 'PyQt6'])
        macos_linux_full = _pip_hint(['numpy', 'pandas', 'matplotlib', 'PyQt6',
                                       'openpyxl', 'xlrd', 'scipy', 'comtrade'])
        msg = (
            "<h3>Power System Plot Visualizer (PSPV) — Requirements</h3>"
            f"<p><b>Current environment:</b> {sys_info}</p>"
            "<h4>Python versions</h4>"
            "<p>Python <b>3.9 or newer</b> is required. Tested on 3.10, 3.11, 3.12, 3.13.</p>"
            "<h4>Supported file formats</h4>"
            "<table cellspacing='4'>"
            "<tr><td><b>Format</b></td><td><b>Extension</b></td><td><b>Needed package</b></td></tr>"
            "<tr><td>CSV / Text</td><td>.csv .txt</td><td>(built-in)</td></tr>"
            "<tr><td>PSS(E) dynamics</td><td>.out .outx .plb</td><td>pssepath (Win) + dyntools</td></tr>"
            "<tr><td>Excel</td><td>.xls .xlsx</td><td>openpyxl (xlsx), xlrd (xls)</td></tr>"
            "<tr><td>MATLAB</td><td>.mat</td><td>scipy  (v7.3 files need h5py)</td></tr>"
            "<tr><td>COMTRADE</td><td>.cfg .dat .cff</td><td>comtrade</td></tr>"
            "</table>"
            "<h4>Required packages (both OSes)</h4>"
            "<ul>"
            "<li><code>numpy</code></li>"
            "<li><code>pandas</code></li>"
            "<li><code>matplotlib</code></li>"
            "<li><code>PyQt6</code></li>"
            "</ul>"
            "<h4>Optional (install on demand, only when you need that format)</h4>"
            "<ul>"
            "<li><code>openpyxl</code>, <code>xlrd</code> — Excel</li>"
            "<li><code>scipy</code> — MATLAB .mat</li>"
            "<li><code>comtrade</code> — COMTRADE</li>"
            "<li><code>pssepath</code> — Windows PSS(E) version discovery</li>"
            "</ul>"
            "<h4>Install commands</h4>"
            "<p><b>Minimum (macOS / Linux):</b><br>"
            f"<code>{macos_linux}</code></p>"
            "<p><b>Full (everything, macOS / Linux):</b><br>"
            f"<code>{macos_linux_full}</code></p>"
            "<p><b>Full (Windows, includes PSS(E)):</b><br>"
            "<code>py -m pip install --upgrade numpy pandas matplotlib PyQt6 "
            "openpyxl xlrd scipy comtrade pssepath</code></p>"
            "<p>Use <b>File → Configure PSS(E)...</b> on Windows to pick an installed PSS(E) "
            "version once pssepath is available, or point it at the PSS(E) root folder manually.</p>"
        )
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Requirements & Install")
        dlg.setTextFormat(Qt.TextFormat.RichText)
        dlg.setText(msg)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()


def main():
    app = QApplication(sys.argv)
    # Force the Fusion style app-wide. The native Windows style interferes
    # with our dark stylesheet (radio-button dots and checkboxes become
    # invisible because Windows tries to use native theming with light
    # colors on our dark background). Fusion is a cross-platform Qt style
    # that draws all controls with the palette we set, so indicators are
    # always visible.
    try:
        app.setStyle('Fusion')
    except Exception:
        pass
    # Build a palette matching the dark theme so Fusion-drawn indicators
    # (radio-button dots, checkbox ticks, text selection) use colors that
    # contrast with the dark background.
    try:
        from PyQt6.QtGui import QPalette, QColor
        pal = THEMES['dark']
        qp = QPalette()
        qp.setColor(QPalette.ColorRole.Window, QColor(pal['bg']))
        qp.setColor(QPalette.ColorRole.WindowText, QColor(pal['text']))
        qp.setColor(QPalette.ColorRole.Base, QColor(pal['panel']))
        qp.setColor(QPalette.ColorRole.AlternateBase, QColor(pal['bg_alt']))
        qp.setColor(QPalette.ColorRole.Text, QColor(pal['text']))
        qp.setColor(QPalette.ColorRole.Button, QColor(pal['panel']))
        qp.setColor(QPalette.ColorRole.ButtonText, QColor(pal['text']))
        qp.setColor(QPalette.ColorRole.Highlight, QColor(pal['accent']))
        qp.setColor(QPalette.ColorRole.HighlightedText, QColor(pal['bg']))
        qp.setColor(QPalette.ColorRole.ToolTipBase, QColor(pal['panel']))
        qp.setColor(QPalette.ColorRole.ToolTipText, QColor(pal['text']))
        app.setPalette(qp)
    except Exception:
        pass
    app.setStyleSheet(DARK_QSS)
    # Use the OS's default UI font. QFontDatabase.systemFont(GeneralFont)
    # returns whatever the platform already has loaded — no font-alias scan
    # needed, so startup stays fast on every OS.
    try:
        from PyQt6.QtGui import QFontDatabase
        _ui_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
        _ui_font.setPointSize(9)
        app.setFont(_ui_font)
    except Exception:
        app.setFont(QFont("", 9))   # Empty family → Qt picks default
    w = Visualizer()
    w.show()
    # Auto-open any data files passed on the command line
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            w._open_path(os.path.abspath(arg))
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
