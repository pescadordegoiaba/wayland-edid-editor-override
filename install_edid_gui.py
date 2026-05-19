#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_edid_gui.py

Copia edid_live_gui.py para ~/.local/bin e cria atalho no menu do KDE.
Uso:
  cd ~/MONITOR
  python3 install_edid_gui.py
"""

from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
SRC = HERE / "edid_live_gui.py"
BACKEND = HERE / "edid_live_override.py"
BIN_DIR = Path.home() / ".local" / "bin"
APP_DIR = Path.home() / ".local" / "share" / "applications"
DST = BIN_DIR / "edid-live-gui"
DESKTOP = APP_DIR / "edid-live-gui.desktop"


def main() -> int:
    if not SRC.exists():
        print(f"ERRO: não achei {SRC}")
        return 1

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SRC, DST)
    DST.chmod(0o755)

    DESKTOP.write_text(f"""[Desktop Entry]
Type=Application
Name=EDID Live Override GUI
Comment=Adicionar resoluções EDID em runtime
Exec={DST}
Terminal=false
Categories=Settings;Hardware;
""")
    DESKTOP.chmod(0o644)

    print(f"Instalado: {DST}")
    print(f"Atalho criado: {DESKTOP}")
    print()
    print("Rodar pelo terminal:")
    print(f"  {DST}")
    print()
    print("Ou procure no menu do KDE por: EDID Live Override GUI")
    print()
    if not BACKEND.exists():
        print("AVISO: edid_live_override.py não está nesta pasta.")
        print("A GUI ainda funciona se você escolher o backend manualmente no botão 'Escolher...'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
