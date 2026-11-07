"""Inline callback_data helpers (prefix:payload)."""
from __future__ import annotations

CONFIRM = "cfm"
CUR = "cur"
CAT = "cat"
EXP_MODE = "exm"
WD_MODE = "wdm"
MEM = "mem"
TOGGLE = "tog"
DEBT = "debt"
ADV = "adv"
CONTRIB = "ctr"
OBL = "obl"
REPORT = "rpt"
SETTINGS = "set"
SKIP = "skip"
REG = "reg"
SETUP = "setup"
ROLE = "role"
PERM = "perm"
JOB = "job"
PROF = "prof"
GOP = "gop"
GUIDE = "guide"
RTREQ = "rtr"


def pack(prefix: str, *parts) -> str:
    return prefix + ":" + ":".join(str(p) for p in parts)


def unpack(data: str) -> list[str]:
    return (data or "").split(":")
