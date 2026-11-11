"""Perfis de configuração (um por jogo) e configuração global, salvos em JSON."""
import copy
import json
import os
import re

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "G500Config")
PROFILES_DIR = os.path.join(CONFIG_DIR, "perfis")
GLOBAL_FILE = os.path.join(CONFIG_DIR, "config.json")

# Botões do controle de Xbox que podem receber um botão do volante.
XBOX_BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "BACK", "START", "LS", "RS", "GUIDE"]

PEDAL_DEFAULT = {"deadzone": 0.03, "saturation": 1.0, "gamma": 1.0}

DEFAULT_PROFILE = {
    "name": "Padrão",
    "exes": [],
    # Índice do eixo físico (0-6) usado para cada função. -1 = não usado.
    "axes": {"wheel": 0, "throttle": 2, "brake": 5, "clutch": 6},
    "invert": {"wheel": False, "throttle": False, "brake": False, "clutch": False},
    "wheel": {"hw_angle": 900, "angle": 900, "deadzone": 0.0, "gamma": 1.0},
    # Configurações gravadas no próprio volante pelo Bluetooth.
    "hw": {"apply": False, "angle": 900, "ffb": 80, "spring": 80, "damper": 80, "friction": 80,
           "inertia": 80, "reverse": False, "pedals_on_wheel": False,
           "curve_throttle": 1.0, "curve_brake": 1.0, "curve_clutch": 1.0},
    "throttle": dict(PEDAL_DEFAULT),
    "brake": dict(PEDAL_DEFAULT),
    "clutch": dict(PEDAL_DEFAULT),
    "ffb": {
        "app_control": False,  # o programa segura o force feedback (o jogo não consegue usar)
        "gain": 100,
        "spring": 40,
        "damper": 10,
        "rumble": 70,
        "invert": False,
    },
    "compat": {
        "enabled": False,
        "clutch_to": "none",  # none | left_stick_y
        "buttons": {"A": 0, "B": 1, "X": 2, "Y": 3, "LB": 4, "RB": 5,
                    "BACK": 8, "START": 9, "LS": 10, "RS": 11, "GUIDE": 12},
    },
}

PRESETS = [
    {"name": "Dirt 5", "exes": ["dirt5.exe"],
     "compat": {"enabled": True}, "ffb": {"app_control": True}},
    {"name": "Forza Motorsport", "exes": ["forza_steamworks_release_final.exe",
                                          "forza_gaming.desktop.x64_release_final.exe"],
     "compat": {"enabled": True}, "ffb": {"app_control": True}},
]


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def new_profile(name, **overrides):
    p = _merge(DEFAULT_PROFILE, overrides)
    p["name"] = name
    return p


def _filename(name):
    safe = re.sub(r"[^\w\- ]", "_", name).strip() or "perfil"
    return os.path.join(PROFILES_DIR, safe + ".json")


def load_profiles():
    os.makedirs(PROFILES_DIR, exist_ok=True)
    profiles = {}
    for fn in os.listdir(PROFILES_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(PROFILES_DIR, fn), encoding="utf-8") as f:
                p = _merge(DEFAULT_PROFILE, json.load(f))
            profiles[p["name"]] = p
        except (OSError, ValueError):
            pass
    if not profiles:
        for p in [new_profile("Padrão")] + [_merge(DEFAULT_PROFILE, x) for x in PRESETS]:
            save_profile(p)
            profiles[p["name"]] = p
    if "Padrão" not in profiles:
        profiles["Padrão"] = new_profile("Padrão")
        save_profile(profiles["Padrão"])
    return profiles


def save_profile(p):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(_filename(p["name"]), "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


def delete_profile(name):
    try:
        os.remove(_filename(name))
    except OSError:
        pass


def load_global():
    data = {"active_profile": "Padrão", "auto_switch": True, "calibration": {}}
    try:
        with open(GLOBAL_FILE, encoding="utf-8") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    return data


def save_global(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(GLOBAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
