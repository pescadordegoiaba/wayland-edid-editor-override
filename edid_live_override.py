#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edid_live_override.py

Lê o EDID atual do Linux em /sys/class/drm, modifica em memória e aplica
runtime via /sys/kernel/debug/dri/*/<connector>/edid_override.

Não grava arquivo EDID permanente.
Não grava nada no monitor físico.
O override some no reboot.

Uso recomendado:
  cd ~/MONITOR
  sudo python3 edid_live_override.py --add '1280x1024;869x723:75' --clean-cta

Forçar conector:
  sudo python3 edid_live_override.py --connector HDMI-A-2 --add '869x723:75' --clean-cta

Listar modos do EDID atual:
  python3 edid_live_override.py --list

Resetar override runtime:
  sudo python3 edid_live_override.py --connector HDMI-A-2 --reset

Testar com modo xrandr depois de aplicar:
  xrandr --output HDMI-A-2 --mode 869x723

Observação:
  No shell, ; separa comandos. Use aspas:
    --add '1280x1024;869x723:75'
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Mode:
    h: int
    v: int
    hz: float

    def key(self) -> Tuple[int, int, int]:
        return (self.h, self.v, int(round(self.hz)))

    def label(self) -> str:
        return f"{self.h}x{self.v}@{int(round(self.hz))}"


@dataclass
class Modeline:
    h: int
    v: int
    hz: float
    pixel_mhz: float
    hfront: int
    hsync: int
    hback: int
    vfront: int
    vsync: int
    vback: int
    flags: int = 0x1e

    @property
    def hblank(self) -> int:
        return self.hfront + self.hsync + self.hback

    @property
    def vblank(self) -> int:
        return self.vfront + self.vsync + self.vback

    @property
    def htotal(self) -> int:
        return self.h + self.hblank

    @property
    def vtotal(self) -> int:
        return self.v + self.vblank

    @property
    def hfreq_khz(self) -> float:
        return self.pixel_mhz * 1000.0 / self.htotal

    @property
    def actual_hz(self) -> float:
        return self.pixel_mhz * 1_000_000.0 / (self.htotal * self.vtotal)


DMT = {
    (640, 480, 60):    (25.175, 16, 96, 48, 10, 2, 33, 0x1a),
    (640, 480, 75):    (31.500, 16, 64, 120, 1, 3, 16, 0x1a),
    (800, 600, 60):    (40.000, 40, 128, 88, 1, 4, 23, 0x1e),
    (800, 600, 75):    (49.500, 16, 80, 160, 1, 3, 21, 0x1e),
    (1024, 768, 60):   (65.000, 24, 136, 160, 3, 6, 29, 0x1a),
    (1024, 768, 75):   (78.750, 16, 96, 176, 1, 3, 28, 0x1e),
    (1152, 864, 75):   (108.000, 64, 128, 256, 1, 3, 32, 0x1e),
    (1280, 720, 60):   (74.250, 110, 40, 220, 5, 5, 20, 0x1e),
    (1280, 1024, 60):  (108.000, 48, 112, 248, 1, 3, 38, 0x1e),
    (1280, 1024, 75):  (135.000, 16, 144, 248, 1, 3, 38, 0x1e),
    (720, 480, 60):    (27.000, 16, 62, 60, 9, 6, 30, 0x18),
    (1920, 1080, 60):  (148.500, 88, 44, 148, 4, 5, 36, 0x1e),
}

VIC_MODES = {
    3: Mode(720, 480, 60),
    4: Mode(1280, 720, 60),
    16: Mode(1920, 1080, 60),
}


def die(msg: str, code: int = 1) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)


def warn(msg: str) -> None:
    print(f"AVISO: {msg}", file=sys.stderr)


def need_root() -> None:
    if os.geteuid() != 0:
        die("para aplicar/resetar override, rode com sudo. Para --list não precisa.")


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def checksum_block(block: bytes | bytearray) -> int:
    return sum(block[:128]) & 0xff


def fix_checksum(edid: bytearray, block_index: int) -> None:
    start = block_index * 128
    edid[start + 127] = 0
    edid[start + 127] = (-sum(edid[start:start + 127])) & 0xff


def fix_all_checksums(edid: bytearray) -> None:
    for i in range(len(edid) // 128):
        fix_checksum(edid, i)


def parse_refreshes(raw: str) -> List[float]:
    out: List[float] = []
    for part in re.split(r"[;,]+", raw):
        part = part.strip()
        if part:
            out.append(float(part))
    if not out:
        die("lista de refreshes vazia.")
    return out


def parse_mode_list(raw_items: Iterable[str], default_refreshes: List[float]) -> List[Mode]:
    modes: List[Mode] = []
    seen = set()
    for raw in raw_items:
        if not raw:
            continue
        for token in re.split(r"[;,]+", raw.strip()):
            token = token.strip()
            if not token:
                continue
            m = re.fullmatch(r"(\d{2,5})x(\d{2,5})(?::(\d+(?:\.\d+)?))?", token, re.I)
            if not m:
                die(f"modo inválido: {token!r}. Use: 1280x1024 ou 1280x1024:75")
            h = int(m.group(1))
            v = int(m.group(2))
            hz_text = m.group(3)
            refreshes = [float(hz_text)] if hz_text else default_refreshes
            for hz in refreshes:
                mode = Mode(h, v, hz)
                if mode.key() not in seen:
                    modes.append(mode)
                    seen.add(mode.key())
    return modes


def drm_connector_name(sys_name: str) -> str:
    return re.sub(r"^card\d+-", "", sys_name)


def detect_connected() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for status in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        try:
            if status.read_text().strip() != "connected":
                continue
        except OSError:
            continue
        sys_dir = status.parent
        found.append((drm_connector_name(sys_dir.name), sys_dir))
    return found


def find_connector_sysfs(connector: Optional[str]) -> tuple[str, Path]:
    connected = detect_connected()
    if connector:
        matches = [(name, path) for name, path in connected if name == connector]
        if matches:
            return matches[0]
        for d in sorted(Path("/sys/class/drm").glob(f"card*-{connector}")):
            return connector, d
        die(f"conector não encontrado: {connector}")
    if len(connected) == 1:
        return connected[0]
    if not connected:
        die("nenhum conector conectado detectado. Use --connector manualmente.")
    print("Conectores conectados detectados:")
    for name, path in connected:
        print(f"  - {name} ({path})")
    die("mais de um conector conectado. Informe --connector, exemplo: --connector HDMI-A-2")


def read_current_edid(sys_dir: Path) -> bytearray:
    edid_path = sys_dir / "edid"
    if not edid_path.exists():
        die(f"EDID não existe em {edid_path}")
    data = edid_path.read_bytes()
    if not data:
        die(f"EDID vazio em {edid_path}")
    if len(data) < 128 or len(data) % 128 != 0:
        die(f"tamanho EDID inválido: {len(data)} bytes")
    if data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        warn("cabeçalho EDID não parece padrão; continuando mesmo assim.")
    return bytearray(data)


def ensure_length_matches_extension_count(edid: bytearray) -> None:
    expected = (edid[0x7e] + 1) * 128
    if len(edid) < expected:
        edid.extend(b"\x00" * (expected - len(edid)))
    elif len(edid) > expected:
        edid[0x7e] = len(edid) // 128 - 1
        fix_checksum(edid, 0)


def base_descriptors() -> List[int]:
    return [0x36 + 18 * i for i in range(4)]


def parse_range_limits(edid: bytes) -> Tuple[float, float, float, float, float]:
    min_v, max_v = 1.0, 240.0
    min_h, max_h = 1.0, 300.0
    max_clock_mhz = 655.0
    for off in base_descriptors():
        d = edid[off:off + 18]
        if len(d) == 18 and d[0] == 0 and d[1] == 0 and d[2] == 0 and d[3] == 0xfd:
            min_v = float(d[5])
            max_v = float(d[6])
            min_h = float(d[7])
            max_h = float(d[8])
            if d[9]:
                max_clock_mhz = float(d[9] * 10)
            break
    return min_v, max_v, min_h, max_h, max_clock_mhz


def physical_size_mm(edid: bytes) -> Tuple[int, int]:
    if len(edid) >= 23:
        w_cm, h_cm = edid[21], edid[22]
        if w_cm and h_cm:
            return w_cm * 10, h_cm * 10
    return 0, 0


def parse_dtd(d: bytes) -> Optional[Tuple[int, int, float]]:
    if len(d) < 18:
        return None
    pixel_10khz = d[0] | (d[1] << 8)
    if pixel_10khz == 0:
        return None
    hact = d[2] | (((d[4] >> 4) & 0x0f) << 8)
    hblank = d[3] | ((d[4] & 0x0f) << 8)
    vact = d[5] | (((d[7] >> 4) & 0x0f) << 8)
    vblank = d[6] | ((d[7] & 0x0f) << 8)
    if hact <= 0 or vact <= 0 or hblank <= 0 or vblank <= 0:
        return None
    refresh = pixel_10khz * 10_000.0 / ((hact + hblank) * (vact + vblank))
    return hact, vact, refresh


def standard_timing_to_mode(b1: int, b2: int) -> Optional[Mode]:
    if (b1, b2) in [(0x01, 0x01), (0x00, 0x00)]:
        return None
    h = (b1 + 31) * 8
    aspect = (b2 >> 6) & 0x03
    hz = (b2 & 0x3f) + 60
    if aspect == 0:
        v = round(h * 10 / 16)
    elif aspect == 1:
        v = round(h * 3 / 4)
    elif aspect == 2:
        v = round(h * 4 / 5)
    else:
        v = round(h * 9 / 16)
    return Mode(h, int(v), float(hz))


def established_modes(edid: bytes) -> List[Mode]:
    if len(edid) < 0x26:
        return []
    b35, b36, b37 = edid[0x23], edid[0x24], edid[0x25]
    mapping = [
        (b35, 7, Mode(720, 400, 70)),
        (b35, 6, Mode(720, 400, 88)),
        (b35, 5, Mode(640, 480, 60)),
        (b35, 4, Mode(640, 480, 67)),
        (b35, 3, Mode(640, 480, 72)),
        (b35, 2, Mode(640, 480, 75)),
        (b35, 1, Mode(800, 600, 56)),
        (b35, 0, Mode(800, 600, 60)),
        (b36, 7, Mode(800, 600, 72)),
        (b36, 6, Mode(800, 600, 75)),
        (b36, 5, Mode(832, 624, 75)),
        (b36, 4, Mode(1024, 768, 87)),
        (b36, 3, Mode(1024, 768, 60)),
        (b36, 2, Mode(1024, 768, 70)),
        (b36, 1, Mode(1024, 768, 75)),
        (b36, 0, Mode(1280, 1024, 75)),
        (b37, 7, Mode(1152, 870, 75)),
    ]
    return [mode for byte, bit, mode in mapping if byte & (1 << bit)]


def iter_existing_modes(edid: bytes) -> List[Mode]:
    modes: List[Mode] = []
    modes.extend(established_modes(edid))
    for off in range(0x26, 0x36, 2):
        m = standard_timing_to_mode(edid[off], edid[off + 1])
        if m:
            modes.append(m)
    for off in base_descriptors():
        parsed = parse_dtd(edid[off:off + 18])
        if parsed:
            h, v, hz = parsed
            modes.append(Mode(h, v, hz))
    for block_index in range(1, len(edid) // 128):
        start = block_index * 128
        if edid[start] != 0x02:
            continue
        dtd_offset = edid[start + 2]
        if 4 <= dtd_offset <= 126:
            p = start + 4
            data_end = start + dtd_offset
            while p < data_end:
                header = edid[p]
                tag_code = (header >> 5) & 0x07
                length = header & 0x1f
                payload = edid[p + 1:p + 1 + length]
                if tag_code == 2:
                    for svd in payload:
                        vic = svd & 0x7f
                        if vic in VIC_MODES:
                            modes.append(VIC_MODES[vic])
                p += 1 + length
            for off in range(start + dtd_offset, start + 110, 18):
                parsed = parse_dtd(edid[off:off + 18])
                if parsed:
                    h, v, hz = parsed
                    modes.append(Mode(h, v, hz))
    unique = {}
    for m in modes:
        unique.setdefault(m.key(), m)
    return list(unique.values())


def mode_exists(edid: bytes, target: Mode) -> bool:
    return any(m.key() == target.key() for m in iter_existing_modes(edid))


def choose_vsync_width(h: int, v: int) -> int:
    ratio = h / v
    if abs(ratio - 4 / 3) < 0.04:
        return 4
    if abs(ratio - 16 / 9) < 0.04:
        return 5
    if abs(ratio - 16 / 10) < 0.04:
        return 6
    if abs(ratio - 5 / 4) < 0.04:
        return 7
    return 10


def generate_cvt_modeline(h: int, v: int, hz: float) -> Modeline:
    cell = 8
    min_vsync_bp_us = 550.0
    min_v_porch = 3
    hsync_percent = 8.0
    m = 600.0
    c = 40.0
    k = 128.0
    j = 20.0
    c_prime = ((c - j) * k / 256.0) + j
    m_prime = (k / 256.0) * m
    vsync = choose_vsync_width(h, v)
    h_period_est = ((1.0 / hz) - (min_vsync_bp_us / 1_000_000.0)) / (v + min_v_porch) * 1_000_000.0
    vsync_bp = int(math.floor(min_vsync_bp_us / h_period_est)) + 1
    if vsync_bp < vsync + 6:
        vsync_bp = vsync + 6
    vfront = min_v_porch
    vback = vsync_bp - vsync
    vtotal = v + vfront + vsync + vback
    ideal_duty = c_prime - (m_prime * h_period_est / 1000.0)
    ideal_duty = max(20.0, min(50.0, ideal_duty))
    hblank = int(math.floor((h * ideal_duty / (100.0 - ideal_duty)) / (2 * cell))) * (2 * cell)
    hblank = max(160, hblank)
    htotal = h + hblank
    hsync = int(math.floor((hsync_percent / 100.0 * htotal) / cell)) * cell
    hsync = max(8, hsync)
    hfront = hblank // 2 - hsync
    hfront = max(8, hfront)
    hback = hblank - hfront - hsync
    if hback < 8:
        hback = 8
        hblank = hfront + hsync + hback
        htotal = h + hblank
    pixel_mhz = htotal * vtotal * hz / 1_000_000.0
    pixel_mhz = round(pixel_mhz / 0.25) * 0.25
    return Modeline(h, v, hz, pixel_mhz, int(hfront), int(hsync), int(hback), int(vfront), int(vsync), int(vback), 0x1e)


def modeline_for_mode(mode: Mode) -> Modeline:
    key = (mode.h, mode.v, int(round(mode.hz)))
    if key in DMT:
        pclk, hf, hs, hb, vf, vs, vb, flags = DMT[key]
        return Modeline(mode.h, mode.v, mode.hz, pclk, hf, hs, hb, vf, vs, vb, flags)
    return generate_cvt_modeline(mode.h, mode.v, mode.hz)


def validate_modeline(ml: Modeline, edid: bytes, force: bool = False) -> bool:
    min_v, max_v, min_h, max_h, max_clock = parse_range_limits(edid)
    reasons = []
    if ml.actual_hz < min_v - 0.75 or ml.actual_hz > max_v + 0.75:
        reasons.append(f"vertical {ml.actual_hz:.2f} Hz fora de {min_v:.0f}-{max_v:.0f} Hz")
    if ml.hfreq_khz < min_h - 0.50 or ml.hfreq_khz > max_h + 0.50:
        reasons.append(f"horizontal {ml.hfreq_khz:.2f} kHz fora de {min_h:.0f}-{max_h:.0f} kHz")
    if ml.pixel_mhz > max_clock + 0.50:
        reasons.append(f"pixel clock {ml.pixel_mhz:.2f} MHz acima de {max_clock:.0f} MHz")
    if reasons and not force:
        warn(f"pulando {ml.h}x{ml.v}@{int(round(ml.hz))}: " + "; ".join(reasons))
        return False
    if reasons and force:
        warn(f"forçando {ml.h}x{ml.v}@{int(round(ml.hz))}, apesar de: " + "; ".join(reasons))
    return True


def encode_dtd(ml: Modeline, size_mm: Tuple[int, int]) -> bytes:
    pixel_10khz = int(round(ml.pixel_mhz * 100.0))
    if not (1 <= pixel_10khz <= 0xffff):
        die(f"pixel clock inválido: {ml.pixel_mhz} MHz")
    hblank = ml.hblank
    vblank = ml.vblank
    w_mm, h_mm = size_mm
    if w_mm > 4095:
        w_mm = 0
    if h_mm > 4095:
        h_mm = 0
    d = bytearray(18)
    d[0] = pixel_10khz & 0xff
    d[1] = (pixel_10khz >> 8) & 0xff
    d[2] = ml.h & 0xff
    d[3] = hblank & 0xff
    d[4] = ((ml.h >> 8) & 0x0f) << 4 | ((hblank >> 8) & 0x0f)
    d[5] = ml.v & 0xff
    d[6] = vblank & 0xff
    d[7] = ((ml.v >> 8) & 0x0f) << 4 | ((vblank >> 8) & 0x0f)
    d[8] = ml.hfront & 0xff
    d[9] = ml.hsync & 0xff
    d[10] = ((ml.vfront & 0x0f) << 4) | (ml.vsync & 0x0f)
    d[11] = (((ml.hfront >> 8) & 0x03) << 6) | (((ml.hsync >> 8) & 0x03) << 4) | (((ml.vfront >> 4) & 0x03) << 2) | ((ml.vsync >> 4) & 0x03)
    d[12] = w_mm & 0xff
    d[13] = h_mm & 0xff
    d[14] = ((w_mm >> 8) & 0x0f) << 4 | ((h_mm >> 8) & 0x0f)
    d[15] = 0
    d[16] = 0
    d[17] = ml.flags & 0xff
    return bytes(d)


def clean_cta(edid: bytearray) -> bytearray:
    out = bytearray(edid[:128])
    out[0x7e] = 0
    fix_checksum(out, 0)
    return out


def create_cta_extension() -> bytes:
    # CTA mínimo com VCDB para evitar algumas reclamações de conformidade.
    b = bytearray(128)
    b[0] = 0x02
    b[1] = 0x03
    b[2] = 0x07
    b[3] = 0x00
    b[4] = 0xe2  # extended tag, length 2
    b[5] = 0x00  # Video Capability Data Block
    b[6] = 0x0f
    b[127] = (-sum(b[:127])) & 0xff
    return bytes(b)


def find_empty_cta_dtd_slot(edid: bytearray) -> Optional[Tuple[int, int]]:
    for block_index in range(1, len(edid) // 128):
        start = block_index * 128
        if edid[start] != 0x02:
            continue
        dtd_offset = edid[start + 2]
        if not (4 <= dtd_offset <= 109):
            continue
        for off in range(start + dtd_offset, start + 110, 18):
            chunk = edid[off:off + 18]
            if len(chunk) == 18 and all(x == 0 for x in chunk):
                return block_index, off
    return None


def add_cta_extension(edid: bytearray) -> None:
    edid.extend(create_cta_extension())
    edid[0x7e] = len(edid) // 128 - 1
    fix_checksum(edid, 0)


def add_dtd_to_edid(edid: bytearray, dtd: bytes) -> None:
    slot = find_empty_cta_dtd_slot(edid)
    if slot is None:
        add_cta_extension(edid)
        slot = find_empty_cta_dtd_slot(edid)
    if slot is None:
        die("não encontrei espaço para DTD em bloco CTA.")
    block_index, off = slot
    edid[off:off + 18] = dtd
    fix_checksum(edid, block_index)


def modify_edid(edid: bytearray, add_items: List[str], default_refreshes: List[float], clean: bool, force: bool) -> Tuple[bytearray, int, int]:
    ensure_length_matches_extension_count(edid)
    if clean:
        print("Limpando extensões CTA/HDMI existentes...")
        edid = clean_cta(edid)
    requested = parse_mode_list(add_items, default_refreshes)
    min_v, max_v, min_h, max_h, max_clock = parse_range_limits(edid)
    print(f"Limites declarados: {min_v:.0f}-{max_v:.0f} Hz V, {min_h:.0f}-{max_h:.0f} kHz H, pixel clock máx {max_clock:.0f} MHz")
    added = 0
    skipped = 0
    for mode in requested:
        if mode_exists(edid, mode):
            print(f"Já existe, pulando: {mode.label()}")
            skipped += 1
            continue
        ml = modeline_for_mode(mode)
        if not validate_modeline(ml, edid, force=force):
            skipped += 1
            continue
        dtd = encode_dtd(ml, physical_size_mm(edid))
        add_dtd_to_edid(edid, dtd)
        added += 1
        print(f"Adicionado: {mode.label()} (clock {ml.pixel_mhz:.2f} MHz, H {ml.hfreq_khz:.2f} kHz, real {ml.actual_hz:.2f} Hz)")
    fix_all_checksums(edid)
    for i in range(len(edid) // 128):
        c = checksum_block(edid[i * 128:(i + 1) * 128])
        if c != 0:
            die(f"checksum inválido no bloco {i}: {c:#x}")
    return edid, added, skipped


def list_modes(edid: bytes) -> None:
    modes = sorted(iter_existing_modes(edid), key=lambda m: (m.h, m.v, round(m.hz)))
    print("Modos anunciados no EDID atual:")
    for m in modes:
        print(f"  - {m.label()}")


def ensure_debugfs_mounted() -> None:
    dbg = Path("/sys/kernel/debug")
    if not dbg.exists():
        die("/sys/kernel/debug não existe.")
    dri = dbg / "dri"
    if dri.exists():
        return
    print("debugfs não parece montado; tentando montar...")
    proc = run(["mount", "-t", "debugfs", "debugfs", "/sys/kernel/debug"])
    if proc.returncode != 0:
        die("não consegui montar debugfs:\n" + proc.stderr.strip())
    if not dri.exists():
        die("debugfs montou, mas /sys/kernel/debug/dri não apareceu.")


def find_debugfs_connector(connector: str, sys_dir: Path) -> Path:
    ensure_debugfs_mounted()
    card_match = re.match(r"card(\d+)-", sys_dir.name)
    candidates: List[Path] = []
    if card_match:
        candidates.append(Path("/sys/kernel/debug/dri") / card_match.group(1) / connector)
    candidates.extend(sorted(Path("/sys/kernel/debug/dri").glob(f"*/{connector}")))
    seen = set()
    unique = []
    for c in candidates:
        s = str(c)
        if s not in seen:
            seen.add(s)
            unique.append(c)
    for c in unique:
        if (c / "edid_override").exists():
            return c
    print("Candidatos tentados:")
    for c in unique:
        print(f"  - {c}")
    die(f"não encontrei edid_override para {connector} em /sys/kernel/debug/dri/*/{connector}")


def apply_edid_override(debug_dir: Path, edid: bytes) -> None:
    target = debug_dir / "edid_override"
    print(f"Aplicando override runtime em: {target}")
    with target.open("wb") as f:
        f.write(edid)
    print(f"Override escrito em memória: {len(edid)} bytes")


def reset_edid_override(debug_dir: Path) -> None:
    target = debug_dir / "edid_override"
    print(f"Resetando override runtime em: {target}")
    with target.open("wb") as f:
        f.write(b"reset\n")
    print("Override resetado.")


def trigger_detect(debug_dir: Path, connector: str) -> None:
    force_file = debug_dir / "force"
    if force_file.exists():
        for value in ["detect\n", "on\n"]:
            try:
                with force_file.open("w") as f:
                    f.write(value)
                print(f"Trigger DRM aplicado via force={value.strip()}")
                break
            except OSError as e:
                warn(f"não consegui escrever {value.strip()} em {force_file}: {e}")
    run(["udevadm", "trigger", "--subsystem-match=drm", "--action=change"], check=False)
    run(["xrandr", "--query"], check=False)
    time.sleep(0.5)
    print("Detect/change enviado. Se o modo não aparecer, replugue o cabo ou reinicie a sessão gráfica.")


def maybe_xrandr_mode(connector: str, mode: Optional[str]) -> None:
    if not mode:
        return
    print(f"Tentando aplicar modo com xrandr: {connector} -> {mode}")
    proc = subprocess.run(["xrandr", "--output", connector, "--mode", mode], text=True)
    if proc.returncode != 0:
        warn("xrandr não conseguiu aplicar o modo. Veja o nome exato com: xrandr")


def main() -> int:
    ap = argparse.ArgumentParser(description="Lê o EDID atual, modifica em memória e aplica via DRM debugfs edid_override.")
    ap.add_argument("--connector", help="Conector DRM. Ex: HDMI-A-2. Se omitido, autodetecta se houver só um conectado.")
    ap.add_argument("--add", action="append", default=[], help="Modo(s) para adicionar. Ex: '1280x1024;869x723:75'")
    ap.add_argument("--default-refreshes", default="60,75", help="Hz usados quando não tem :Hz. Padrão: 60,75")
    ap.add_argument("--clean-cta", action="store_true", help="Remove blocos CTA/HDMI existentes antes de adicionar os modos.")
    ap.add_argument("--force", action="store_true", help="Adiciona mesmo fora dos limites declarados do EDID.")
    ap.add_argument("--list", action="store_true", help="Lista os modos do EDID atual e sai.")
    ap.add_argument("--reset", action="store_true", help="Remove o override runtime do conector.")
    ap.add_argument("--no-trigger", action="store_true", help="Não tenta forçar detect/change depois de escrever o override.")
    ap.add_argument("--xrandr-mode", help="Depois de aplicar, tenta mudar para este modo. Ex: 869x723")
    args = ap.parse_args()

    connector, sys_dir = find_connector_sysfs(args.connector)
    print(f"Conector: {connector}")
    print(f"Sysfs:    {sys_dir}")

    if args.list:
        edid = read_current_edid(sys_dir)
        list_modes(edid)
        return 0

    need_root()
    debug_dir = find_debugfs_connector(connector, sys_dir)
    print(f"Debugfs:  {debug_dir}")

    if args.reset:
        reset_edid_override(debug_dir)
        if not args.no_trigger:
            trigger_detect(debug_dir, connector)
        return 0

    if not args.add:
        die("nenhum modo informado. Use --add '869x723:75', --list ou --reset.")

    edid = read_current_edid(sys_dir)
    print(f"EDID lido do sistema: {len(edid)} bytes")

    default_refreshes = parse_refreshes(args.default_refreshes)
    patched, added, skipped = modify_edid(
        edid=edid,
        add_items=args.add,
        default_refreshes=default_refreshes,
        clean=args.clean_cta,
        force=args.force,
    )

    if added == 0:
        print("Nenhum modo novo foi adicionado. Tudo foi pulado por já existir ou por limite de frequência.")
        return 0

    apply_edid_override(debug_dir, patched)

    if not args.no_trigger:
        trigger_detect(debug_dir, connector)

    maybe_xrandr_mode(connector, args.xrandr_mode)

    print()
    print(f"Concluído: {added} modo(s) adicionado(s), {skipped} pulado(s).")
    print("Esse override é runtime: some ao reiniciar.")
    print()
    print("Conferir:")
    print(f"  xrandr | grep -E '{connector}|869x723|1280x1024'")
    print()
    print("Resetar:")
    print(f"  sudo python3 {Path(sys.argv[0]).name} --connector {connector} --reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
