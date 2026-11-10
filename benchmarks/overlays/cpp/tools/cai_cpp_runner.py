"""CAI runner for C++ workspaces: the directive body is a complete program
(with main) that is compiled together with src/**/*.cpp and executed."""
import glob
import os
import subprocess
import sys
import tempfile

body = sys.stdin.read()
with tempfile.TemporaryDirectory() as tmp:
    main = os.path.join(tmp, "cai_main.cpp")
    with open(main, "w", encoding="utf-8") as fh:
        fh.write(body)
    exe = os.path.join(tmp, "cai_exe")
    sources = sorted(glob.glob("src/**/*.cpp", recursive=True))
    build = subprocess.run(["g++", "-std=c++17", "-Isrc", main, *sources, "-o", exe])
    if build.returncode:
        sys.exit(build.returncode)
    sys.exit(subprocess.run([exe]).returncode)
