"""Hooks into the desktop window, set by desktop.py. None when the UI runs in
a plain browser (dev), where the app falls back to typed paths."""

pick_folder = None  # (start_dir: str) -> str | None
