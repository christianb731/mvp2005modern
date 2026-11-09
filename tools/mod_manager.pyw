"""Windows mod manager for ZIP packages of MVP 2005 BIG replacements."""

import argparse
import subprocess
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from zipfile import BadZipFile
from zlib import error as DeflateError

from mod_install import install, plain_path, restore
from mod_preview import game_root, preview


MOD_ERRORS = (BadZipFile, DeflateError, EOFError, OSError, RuntimeError, ValueError,
              subprocess.CalledProcessError)


class ModManager:
    def __init__(self, window: tk.Tk, game: Path):
        self.window = window
        self.game = game
        self.journal = game / "MVP2005Modern.Mods" / "active.json"
        self.package = None
        self.replacements = []
        self.task = None
        self.worker = ThreadPoolExecutor(max_workers=1)

        window.title("MVP2005 Modern Mod Manager")
        window.minsize(620, 320)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.close)

        panel = ttk.Frame(window, padding=16)
        panel.grid(sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        ttk.Label(panel, text="Game folder").grid(row=0, column=0, sticky="w")
        game_folder = ttk.Entry(panel)
        game_folder.insert(0, str(game))
        game_folder.configure(state="readonly")
        game_folder.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))

        self.details = tk.Text(panel, height=10, width=72, wrap="word", state="disabled")
        self.details.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.details.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.details.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(panel)
        buttons.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.browse = ttk.Button(buttons, text="Preview ZIP…", command=self.choose_package)
        self.install_button = ttk.Button(buttons, text="Install", command=self.install_package)
        self.restore_button = ttk.Button(buttons, text="Restore originals", command=self.restore_originals)
        for column, button in enumerate((self.browse, self.install_button, self.restore_button)):
            button.grid(row=0, column=column, padx=(0, 8))

        if self.journal.exists():
            self.show("A package is installed or an operation was interrupted. Restore the originals to install another package.")
        else:
            self.show("Close the game before installing or restoring. Choose a ZIP to preview its BIG archives.")
        self.update_buttons()

    def show(self, message: str):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", message)
        self.details.configure(state="disabled")

    def update_buttons(self):
        active = self.journal.exists() or self.journal.is_symlink()
        self.browse.configure(state="disabled" if self.task else "normal")
        can_install = not (self.task or active) and any(
            entry.installed_sha256 != entry.packaged_sha256 for entry in self.replacements
        )
        self.install_button.configure(state="normal" if can_install else "disabled")
        self.restore_button.configure(state="normal" if active and not self.task else "disabled")

    def start(self, message, operation, finished):
        self.show(message)
        self.task = self.worker.submit(operation)
        self.update_buttons()

        def poll():
            if not self.task.done():
                self.window.after(80, poll)
                return
            task, self.task = self.task, None
            try:
                finished(task.result())
            except MOD_ERRORS as exc:
                self.package = None
                self.replacements = []
                messagebox.showerror("Mod operation failed", str(exc), parent=self.window)
                self.show("Choose a ZIP to preview it again. If an operation was interrupted, restore the originals.")
            self.update_buttons()

        self.window.after(80, poll)

    def choose_package(self):
        selected = filedialog.askopenfilename(
            parent=self.window, title="Choose a mod package", filetypes=[("ZIP packages", "*.zip")]
        )
        if not selected:
            return
        package = Path(selected)

        def display(entries):
            self.package, self.replacements = package, entries
            lines = [package.name, ""]
            for entry in entries:
                changed = entry.installed_sha256 != entry.packaged_sha256
                lines.append(f"{'Replace' if changed else 'Identical'}   {entry.path}")
            if self.journal.exists():
                lines.extend(("", "Restore the active package before installing another one."))
            self.show("\n".join(lines))

        self.start("Reading package…", lambda: preview(package, self.game), display)

    def install_package(self):
        package, entries = self.package, self.replacements

        def finished(count):
            self.package, self.replacements = None, []
            self.show(f"Installed {count} archive(s) from {package.name}. You can now close the manager and start the game.")

        self.start("Backing up and installing the previewed archives…",
                   lambda: install(self.game, package, expected=entries), finished)

    def restore_originals(self):
        if not messagebox.askokcancel("Restore original archives",
                                      "Restore the original archives from the active package's backup?",
                                      parent=self.window):
            return

        def finished(count):
            self.package, self.replacements = None, []
            self.show(f"Restore complete. Changed {count} archive(s).")

        self.start("Restoring the original archives…", lambda: restore(self.game), finished)

    def close(self):
        if self.task:
            return
        self.worker.shutdown()
        self.window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    args = parser.parse_args()
    window = tk.Tk()
    window.withdraw()
    try:
        if sys.version_info < (3, 11):
            raise ValueError("The mod manager requires Python 3.11 or later with Tkinter.")
        game = game_root(args.game)
        plain_path(game / "MVP2005Modern.Mods")
        ModManager(window, game)
    except (OSError, ValueError) as exc:
        messagebox.showerror("Mod manager", str(exc), parent=window)
        window.destroy()
        return
    window.deiconify()
    window.mainloop()


if __name__ == "__main__":
    main()
