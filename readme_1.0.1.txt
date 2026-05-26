============================================================
  Power System Plot Visualizer (PSPV) — v1.0.1
  Setup & User Guide
============================================================

A desktop tool for plotting and inspecting time-series data
from power-system simulations and fault recorders. Built with
Python, PyQt6, and matplotlib.

Supported file formats:
  - CSV, TXT  (plain-text tabular data)
  - XLS, XLSX (Excel)
  - MAT       (MATLAB v7.2 or older)
  - OUT, OUTX (PSS(E) dynamics output)
  - PLB       (PSS(E) channel playback, text variant)
  - CFG, DAT, CFF (COMTRADE - relays, PMUs, DFRs)

Tested on macOS 13+ and Windows 10/11.


============================================================
  CONTENTS
============================================================
  1. Quick start
  2. Prerequisites (Python)
  3. Installation - Windows
  4. First launch
  5. Optional file formats
  6. Running the tests

============================================================
  1. QUICK START
============================================================

  macOS:
    python3 -m pip install --upgrade --user -r requirements.txt
    python3 PSPV.py

  Windows (Command Prompt):
    py -m pip install --upgrade -r requirements.txt
    py PSPV.py

That's it. The app opens a window with an empty plot. Use
File -> Open (or drag a data file onto the window) to start
visualizing.


============================================================
  2. PREREQUISITES - PYTHON
============================================================

You need Python 3.9 or newer. Tested on 3.10, 3.11, 3.12, 3.13.

Check what you have:
  macOS:   python3 --version
  Windows: py --version

If Python is missing or older than 3.9:

  macOS
  -----
  - Install Homebrew (once):    https://brew.sh
  - Install Python:             brew install python@3.12
  - Verify:                     python3 --version

  Windows
  -------
  - Download from:              https://www.python.org/downloads/
  - IMPORTANT during install:   tick "Add Python to PATH"
  - Verify (new Command Prompt): py --version

Avoid using system Python on Linux/macOS for packages; use
Homebrew's python or a virtualenv so you don't need sudo.


============================================================
  3. REQUIREMENTS INSTALLATION - WINDOWS
============================================================

Step 1. Open "Command Prompt" (Start -> type  cmd  -> Enter).

Step 2. Navigate to this folder. Example:

          cd C:\Users\you\Documents\PSPV

Step 3. Install the required packages:

          run the PSPV_Requirements.bat

Step 4. Launch the app:

          py PSPV.py



============================================================
  6. FIRST LAUNCH
============================================================

When the window opens:

  1. Drag a data file onto the window, or use File -> Open.
  2. The left panel populates with columns (X-axis and Y-axis).
  3. Drag a Y-axis column onto any subplot, or double-click
     it (first subplot gets it by default).
  4. Use the toolbar above each plot:
        Home / Back / Forward  - navigation history
        Pan (hand)             - drag to move the view
        Zoom (magnifier)       - drag a rectangle to zoom in;
                                 right-drag to zoom out
        Select                 - click curves/legends without
                                 changing the view
        Hover                  - toggle snap cursor with
                                 per-curve (x,y) values
        Save                   - export the plot as an image
        Help                   - shortcuts / requirements /
                                 about menu

Key features to try:
  - View -> Theme -> Dark / Light / System default
  - Right-panel collapsible sections:
        Titles & Labels (legend show/hide, include filename)
        Fonts, Axis Range, Math (derived curves),
        Annotations, Tolerance Band, Measurements, Export
  - Left-panel "Subplot Grid" with "Link X" checkbox
  - Legend: single-click to select, F2 or double-click to
    rename, Del (or Backspace) to delete the curve
  - Annotations: drag the text label to reposition; the
    arrow stays anchored on the data point

Full keyboard shortcuts are under Help -> Shortcuts.


============================================================
  5. OPTIONAL FILE FORMATS
============================================================

The readers for these formats load on demand. If a package is
missing, you'll get a clear install hint when you try to open
that format:

  Excel (.xls, .xlsx):
      python3 -m pip install openpyxl xlrd
      (xlrd is only for legacy .xls)

  MATLAB (.mat):
      python3 -m pip install scipy

  COMTRADE (.cfg / .dat / .cff):
      python3 -m pip install comtrade

  PSS(E) (.out / .outx / .plb):
      Requires a local PSS(E) installation. On Windows,
      install pssepath and use File -> Configure PSS(E)...
      to pick your installed version:
          py -m pip install pssepath
      On other OSes, set PSSE_ROOT to the install folder
      before launching PSPV.



