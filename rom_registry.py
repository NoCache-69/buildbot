#!/usr/bin/env python3
"""
Custom ROM Registry & Fuzzy Logo Resolver
Loads metadata for 100+ Android Custom ROMs and maps names/aliases to official logos.
"""

import os
import re
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ROMS_JSON = os.path.join(DATA_DIR, "roms.json")
LOGOS_DIR = os.path.join(BASE_DIR, "assets", "logos")

_ROMS_CACHE = None

def get_all_roms():
    global _ROMS_CACHE
    if _ROMS_CACHE is not None:
        return _ROMS_CACHE
    
    if os.path.isfile(ROMS_JSON):
        try:
            with open(ROMS_JSON, "r", encoding="utf-8") as f:
                _ROMS_CACHE = json.load(f)
                return _ROMS_CACHE
        except Exception:
            pass
    _ROMS_CACHE = []
    return _ROMS_CACHE

def find_rom(query):
    if not query:
        return None
        
    roms = get_all_roms()
    q_clean = re.sub(r"[^a-z0-9]", "", query.lower())
    
    # 1. Exact slug match
    for r in roms:
        if r.get("slug") == q_clean:
            return r

    # 2. Key aliases
    alias_map = {
        "aospa": "paranoidaospa",
        "pa": "paranoidaospa",
        "paranoid": "paranoidaospa",
        "crdroid": "crdroid",
        "cr": "crdroid",
        "infinity": "projectinfinityx",
        "infinityx": "projectinfinityx",
        "infx": "projectinfinityx",
        "evo": "evolutionx",
        "evox": "evolutionx",
        "evolution": "evolutionx",
        "lineage": "lineageos",
        "los": "lineageos",
        "derp": "derpfestaosp",
        "derpfest": "derpfestaosp",
        "axion": "axionaosp",
        "axionos": "axionaosp",
        "pixel": "pixelos",
        "pos": "pixelos",
        "rising": "risingrevivedoss",
        "risingos": "risingrevivedoss",
        "voltage": "voltageos",
        "bliss": "blissroms",
        "graphene": "grapheneos",
        "calyx": "calyxos",
        "statix": "statixos",
        "lunaris": "lunarisaosp",
        "luna": "lunarisaosp",
        "lunarisos": "lunarisaosp",
        "lunarisaosp": "lunarisaosp",
        "alpha": "alphadroid",
    }
    target_slug = alias_map.get(q_clean)
    if target_slug:
        for r in roms:
            if r.get("slug") == target_slug:
                return r

    # 3. Substring match
    for r in roms:
        slug = r.get("slug", "")
        name = r.get("name", "").lower()
        if q_clean in slug or q_clean in name:
            return r

    return None

def resolve_rom_logo(query):
    # Direct file check
    q_clean = re.sub(r"[^a-z0-9]", "", (query or "").lower())
    direct = os.path.join(LOGOS_DIR, f"{q_clean}.png")
    if os.path.isfile(direct):
        return direct
        
    rom = find_rom(query)
    if rom:
        logo_path = os.path.join(LOGOS_DIR, rom.get("logo_file", ""))
        if os.path.isfile(logo_path):
            return logo_path
            
    # Default fallbacks
    for fallback in ["aospa.png", "android.png"]:
        p = os.path.join(LOGOS_DIR, fallback)
        if os.path.isfile(p):
            return p
            
    return None

if __name__ == "__main__":
    test_queries = ["AOSPA", "crdroid", "infinity", "Evolution X", "LineageOS", "Axion", "RisingOS", "DerpFest", "VoltageOS"]
    for q in test_queries:
        r = find_rom(q)
        logo = resolve_rom_logo(q)
        name = r["name"] if r else "Not Found"
        print(f"Query: {q:15} -> {name:25} | Logo: {os.path.basename(logo) if logo else 'None'}")
