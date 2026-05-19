#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edid_live_gui.py

GUI Tkinter para o edid_live_override.py.

Ela usa o script CLI que já funcionou no seu sistema como backend:
  edid_live_override.py

Não grava EDID físico no monitor.
Aplica override runtime via debugfs, igual ao script CLI.
O override some após reboot.

Uso:
  cd ~/MONITOR
  python3 edid_live_gui.py

Requisitos Manjaro/Arch:
  sudo pacman -S python tk xorg-xrandr polkit
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog


APP_TITLE = "EDID Live Override GUI"


class EdidGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x700")
        self.minsize(860, 620)

        self.script_path = tk.StringVar(value=self.find_default_backend())
        self.connector_var = tk.StringVar()
        self.add_var = tk.StringVar(value="869x723:75;1024x1024:60")
        self.default_hz_var = tk.StringVar(value="60,75")
        self.clean_cta_var = tk.BooleanVar(value=True)
        self.force_var = tk.BooleanVar(value=False)
        self.no_trigger_var = tk.BooleanVar(value=False)
        self.xrandr_mode_var = tk.StringVar(value="")
        self.rotate_var = tk.StringVar(value="normal")
        self.scale_from_var = tk.StringVar(value="")

        self._build_ui()
        self.refresh_connectors()
        self.log("GUI carregada.")
        self.log("Backend esperado: edid_live_override.py")

    def find_default_backend(self) -> str:
        candidates = [
            Path.cwd() / "edid_live_override.py",
            Path.home() / "MONITOR" / "edid_live_override.py",
            Path.home() / "Downloads" / "edid_live_override.py",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return str(Path.cwd() / "edid_live_override.py")

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        backend = ttk.LabelFrame(root, text="Backend")
        backend.pack(fill="x")
        ttk.Label(backend, text="Script CLI:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(backend, textvariable=self.script_path).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(backend, text="Escolher...", command=self.choose_backend).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(backend, text="Checar", command=self.check_backend).grid(row=0, column=3, padx=6, pady=6)
        backend.columnconfigure(1, weight=1)

        conn = ttk.LabelFrame(root, text="Conector DRM")
        conn.pack(fill="x", pady=(10, 0))
        ttk.Label(conn, text="Saída:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.connector_combo = ttk.Combobox(conn, textvariable=self.connector_var, state="readonly", width=44)
        self.connector_combo.grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(conn, text="Atualizar", command=self.refresh_connectors).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(conn, text="Listar modos", command=self.list_modes).grid(row=0, column=3, padx=6, pady=6)
        conn.columnconfigure(1, weight=1)

        modes = ttk.LabelFrame(root, text="Adicionar resoluções ao EDID runtime")
        modes.pack(fill="x", pady=(10, 0))
        ttk.Label(modes, text="Resoluções:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(modes, textvariable=self.add_var).grid(row=0, column=1, columnspan=5, padx=6, pady=6, sticky="we")

        ttk.Label(modes, text="Hz padrão:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(modes, textvariable=self.default_hz_var, width=14).grid(row=1, column=1, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(modes, text="Limpar CTA/HDMI falso", variable=self.clean_cta_var).grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(modes, text="Forçar fora dos limites", variable=self.force_var).grid(row=1, column=3, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(modes, text="Não acionar detect/change", variable=self.no_trigger_var).grid(row=1, column=4, padx=6, pady=6, sticky="w")
        ttk.Button(modes, text="Aplicar EDID runtime", command=self.apply_edid).grid(row=1, column=5, padx=6, pady=6, sticky="e")
        modes.columnconfigure(1, weight=1)

        xr = ttk.LabelFrame(root, text="Teste rápido com xrandr")
        xr.pack(fill="x", pady=(10, 0))
        ttk.Label(xr, text="Modo:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(xr, textvariable=self.xrandr_mode_var, width=18).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(xr, text="Aplicar modo", command=self.apply_xrandr_mode).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(xr, text="Rotação:").grid(row=0, column=3, padx=6, pady=6, sticky="w")
        rot = ttk.Combobox(xr, textvariable=self.rotate_var, values=["normal", "left", "right", "inverted"], state="readonly", width=10)
        rot.grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(xr, text="Aplicar rotação", command=self.apply_rotation).grid(row=0, column=5, padx=6, pady=6)

        ttk.Label(xr, text="Scale-from:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(xr, textvariable=self.scale_from_var, width=18).grid(row=1, column=1, padx=6, pady=6)
        ttk.Button(xr, text="Aplicar scale-from", command=self.apply_scale_from).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(xr, text="Reset xrandr", command=self.reset_xrandr).grid(row=1, column=3, padx=6, pady=6)
        ttk.Button(xr, text="Resetar EDID runtime", command=self.reset_edid).grid(row=1, column=4, columnspan=2, padx=6, pady=6, sticky="e")

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_box = scrolledtext.ScrolledText(log_frame, wrap="word", height=18)
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Limpar log", command=self.clear_log).pack(side="left")
        ttk.Button(bottom, text="Comando equivalente", command=self.show_command).pack(side="left", padx=8)
        ttk.Button(bottom, text="Sair", command=self.destroy).pack(side="right")

    def log(self, text: str):
        self.log_box.insert("end", str(text) + "\n")
        self.log_box.see("end")
        self.update_idletasks()

    def clear_log(self):
        self.log_box.delete("1.0", "end")

    def choose_backend(self):
        path = filedialog.askopenfilename(
            title="Escolha edid_live_override.py",
            initialdir=str(Path.home()),
            filetypes=[("Python", "*.py"), ("Todos", "*")],
        )
        if path:
            self.script_path.set(path)

    def check_backend(self):
        p = Path(self.script_path.get()).expanduser()
        if not p.exists():
            messagebox.showerror("Backend não encontrado", f"Arquivo não existe:\n{p}")
            return
        self.log(f"Backend encontrado: {p}")
        proc = subprocess.run(["python3", str(p), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0:
            self.log("Backend respondeu --help corretamente.")
        else:
            self.log("Backend respondeu com erro:")
            self.log(proc.stderr.strip())

    def refresh_connectors(self):
        values = []
        connected = []
        for status in sorted(Path("/sys/class/drm").glob("card*-*/status")):
            sys_name = status.parent.name
            connector = re.sub(r"^card\d+-", "", sys_name)
            try:
                st = status.read_text().strip()
            except OSError:
                st = "unknown"
            label = f"{connector} [{st}]"
            values.append(label)
            if st == "connected":
                connected.append(label)

        self.connector_combo["values"] = values
        if connected:
            self.connector_var.set(connected[0])
        elif values:
            self.connector_var.set(values[0])

        self.log("Conectores:")
        for v in values:
            self.log(f"  - {v}")

    def connector(self) -> str:
        raw = self.connector_var.get().strip()
        if not raw:
            raise RuntimeError("Selecione um conector.")
        return raw.split()[0]

    def backend(self) -> Path:
        p = Path(self.script_path.get()).expanduser()
        if not p.exists():
            raise RuntimeError(f"Backend não encontrado: {p}")
        return p

    def run_normal(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.log("")
        self.log("Executando:")
        self.log(" ".join(shlex.quote(x) for x in cmd))
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stdout:
            self.log(proc.stdout.rstrip())
        if proc.stderr:
            self.log(proc.stderr.rstrip())
        return proc

    def run_privileged_backend(self, args: list[str]) -> subprocess.CompletedProcess:
        p = self.backend()
        if os.geteuid() == 0:
            cmd = ["python3", str(p)] + args
        else:
            cmd = ["pkexec", "python3", str(p)] + args
        return self.run_normal(cmd)

    def list_modes(self):
        try:
            cmd = ["python3", str(self.backend()), "--connector", self.connector(), "--list"]
            proc = self.run_normal(cmd)
            if proc.returncode != 0:
                messagebox.showerror("Erro", "Falha ao listar modos. Veja o log.")
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def apply_edid(self):
        try:
            add = self.add_var.get().strip()
            if not add:
                raise RuntimeError("Campo de resoluções vazio.")
            args = ["--connector", self.connector(), "--add", add, "--default-refreshes", self.default_hz_var.get().strip() or "60,75"]
            if self.clean_cta_var.get():
                args.append("--clean-cta")
            if self.force_var.get():
                args.append("--force")
            if self.no_trigger_var.get():
                args.append("--no-trigger")
            proc = self.run_privileged_backend(args)
            if proc.returncode == 0:
                messagebox.showinfo("EDID aplicado", "Override runtime aplicado. Confira no xrandr.")
            else:
                messagebox.showerror("Erro", "Falha ao aplicar. Veja o log.")
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def reset_edid(self):
        try:
            args = ["--connector", self.connector(), "--reset"]
            if self.no_trigger_var.get():
                args.append("--no-trigger")
            proc = self.run_privileged_backend(args)
            if proc.returncode == 0:
                messagebox.showinfo("Reset", "Override runtime resetado.")
            else:
                messagebox.showerror("Erro", "Falha ao resetar. Veja o log.")
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def apply_xrandr_mode(self):
        try:
            mode = self.xrandr_mode_var.get().strip()
            if not mode:
                raise RuntimeError("Informe o modo, exemplo: 869x723")
            self.run_normal(["xrandr", "--output", self.connector(), "--mode", mode])
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def apply_rotation(self):
        try:
            self.run_normal(["xrandr", "--output", self.connector(), "--rotate", self.rotate_var.get()])
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def apply_scale_from(self):
        try:
            scale = self.scale_from_var.get().strip()
            if not scale:
                raise RuntimeError("Informe scale-from, exemplo: 900x1280")
            self.run_normal(["xrandr", "--output", self.connector(), "--scale-from", scale])
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def reset_xrandr(self):
        try:
            self.run_normal(["xrandr", "--output", self.connector(), "--rotate", "normal", "--scale", "1x1"])
        except Exception as e:
            self.log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))

    def show_command(self):
        try:
            args = ["sudo", "python3", str(self.backend()), "--connector", self.connector(), "--add", self.add_var.get(), "--default-refreshes", self.default_hz_var.get()]
            if self.clean_cta_var.get():
                args.append("--clean-cta")
            if self.force_var.get():
                args.append("--force")
            if self.no_trigger_var.get():
                args.append("--no-trigger")
            self.log("")
            self.log("Comando equivalente:")
            self.log(" ".join(shlex.quote(x) for x in args))
        except Exception as e:
            self.log(f"ERRO: {e}")


def main() -> int:
    app = EdidGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
