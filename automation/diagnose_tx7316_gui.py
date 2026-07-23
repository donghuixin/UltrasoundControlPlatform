# -*- coding: utf-8 -*-
from __future__ import print_function

"""
TX7316 GUI read-only diagnostic.

This file NEVER calls write_register.  It tries likely VI Server ports,
application names, and register-tree labels, then records the first combination
that can read a harmless GUI register.  Run with 32-bit Python 2.7 as
Administrator while TX7316 GUI is already open as Administrator.
"""

import ctypes
import imp
import math
import os
import struct
import sys
import time


MODULE_CANDIDATES = [
    os.environ.get("TX7316_EVM_PYTHON_MODULE"),
    r"E:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py",
    r"C:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py",
]
MODULE = next((path for path in MODULE_CANDIDATES if path and os.path.isfile(path)), MODULE_CANDIDATES[1])
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tx_gui_diagnostic.log")

PORTS = [6640.0, float("nan"), 3370.0]
APPLICATIONS = [
    "TX7316 EVM GUI",
    "TX7316 EVM",
    "TX7316 5LVL EVM",
    "TX7316 EVM.exe",
    "TX7316 EVM GUI.vi",
    "TX7316 5LVL EVM.vi",
    "TX7316 EVM.vi",
    "",
]
REGISTER_PAIRS = [
    ("GLOBAL", "Register 22"),
    ("GLOBAL", "Register 0"),
    ("GLOBAL", "Register22"),
    ("GLOBAL", "0x16"),
    ("GLOBAL", "22"),
    ("Global", "Register 22"),
    ("GLOBAL ", "Register 22"),
    ("GLOBAL/Register 22", "Register 22"),
]


def emit(handle, text):
    line = str(text)
    print(line)
    handle.write((line + "\n").encode("utf-8"))
    handle.flush()


def port_text(port):
    return "NaN" if math.isnan(port) else str(port)


def main():
    if struct.calcsize("P") * 8 != 32:
        print("ERROR: use C:\\Python27\\python.exe (32-bit).")
        return 2
    if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
        print("ERROR: diagnostic must run as Administrator.")
        return 2
    if not os.path.isfile(MODULE):
        print("ERROR: module not found: " + MODULE)
        return 2

    module = imp.load_source("ti_tx7316_diag", MODULE)
    attempts = 0
    last_error_by_port = {}
    with open(LOG, "wb") as handle:
        emit(handle, "TX7316 READ-ONLY DIAGNOSTIC")
        emit(handle, "No register writes will be performed.")
        emit(handle, "Python: " + sys.executable)
        emit(handle, "Time: " + time.strftime("%Y-%m-%d %H:%M:%S"))
        emit(handle, "=" * 72)

        for port in PORTS:
            emit(handle, "Testing VI Server port " + port_text(port))
            last_error_by_port[port_text(port)] = None
            for application in APPLICATIONS:
                gui = module.Device_GUI(application, port)
                for block, register in REGISTER_PAIRS:
                    attempts += 1
                    try:
                        value = int(gui.read_register(block, register)) & 0xffffffff
                    except Exception as exc:
                        last_error_by_port[port_text(port)] = repr(exc)
                        continue
                    emit(handle, "MATCH FOUND")
                    emit(handle, "  port        = " + port_text(port))
                    emit(handle, "  application = %r" % application)
                    emit(handle, "  block       = %r" % block)
                    emit(handle, "  register    = %r" % register)
                    emit(handle, "  value       = 0x%08X" % value)
                    emit(handle, "Attempts: %d" % attempts)
                    emit(handle, "READ-ONLY DIAGNOSTIC SUCCESS")
                    return 0

        emit(handle, "=" * 72)
        emit(handle, "NO MATCH after %d read-only attempts." % attempts)
        for port in PORTS:
            emit(handle, "Last error at port %s: %s" % (
                port_text(port), last_error_by_port[port_text(port)]))
        emit(handle, "Next step: launch IDLE from the TX7316 GUI Script menu so the GUI")
        emit(handle, "reveals the exact -l module,path,application,port parameters.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        try:
            with open(LOG, "ab") as handle:
                emit(handle, "FATAL: %r" % exc)
        except Exception:
            pass
        print("FATAL: %r" % exc)
        sys.exit(1)
