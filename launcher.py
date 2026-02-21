#!/usr/bin/env python3
import subprocess
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

cmds = [
    ("client", ["python3", "client/main.py"]),
    ("detector", ["python3", "detection_engine/detector.py"]),
    ("simulator", ["python3", "utils/ransomware_simulator.py"]),
    ("recovery", ["python3", "recovery_manager/recovery_manager.py"]),
]

for name, cmd in cmds:
    full = " ".join(cmd)
    print(f"🚀 {name}: {full}")

    if sys.platform == "darwin":
        subprocess.Popen(["osascript", "-e", 
                f'tell app "Terminal" to activate\n'
            f'tell app "Terminal" to do script "cd {BASE} && {full}"'])

    elif sys.platform == "linux":
        for term in ["gnome-terminal", "konsole", "xterm"]:
            try:
                subprocess.Popen([term, "--", "bash", "-c", f"cd {BASE} && {full}; exec bash"])
                break
            except FileNotFoundError:
                continue

    else:  # Windows
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", f"cd /d {BASE} && {full}"])
