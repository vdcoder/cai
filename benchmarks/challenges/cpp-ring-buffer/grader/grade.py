"""Hidden grader: compiles the workspace sources with a hidden test program."""
import json
import os
import subprocess
import sys
import tempfile

WS = os.environ["CAI_BENCH_WORKSPACE"]
with tempfile.TemporaryDirectory() as tmp:
    exe = os.path.join(tmp, "test")
    build = subprocess.run(["g++", "-std=c++17", "-I", os.path.join(WS, "src"),
                            os.path.join(WS, "src", "ring_buffer.cpp"), "test_main.cpp", "-o", exe],
                           capture_output=True, text=True)
    if build.returncode:
        print(build.stderr)
        print("CAI_BENCH_RESULT " + json.dumps({"tests_passed": 0, "tests_total": 5}))
        sys.exit(1)
    run = subprocess.run([exe], capture_output=True, text=True, timeout=20)
print(run.stdout)
failed = run.stdout.count("FAIL")
print("CAI_BENCH_RESULT " + json.dumps({"tests_passed": 5 - failed, "tests_total": 5}))
sys.exit(0 if run.returncode == 0 and failed == 0 else 1)
