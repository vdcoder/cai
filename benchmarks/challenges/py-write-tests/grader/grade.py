"""Hidden grader: mutation check of the agent's tests."""
import json
import os
import shutil
import subprocess
import sys

WS = os.environ["CAI_BENCH_WORKSPACE"]
TARGET = os.path.join(WS, "src", "intervals.py")


def suite_passes():
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=WS,
                          capture_output=True, text=True, timeout=30)
    ran = "Ran 0 tests" not in proc.stderr and "NO TESTS RAN" not in proc.stderr
    return proc.returncode == 0 and ran


shutil.copyfile("reference.py", TARGET)
score = reference_ok = int(suite_passes())
print("passes on reference:", bool(score))
for name in sorted(os.listdir("mutants")):
    shutil.copyfile(os.path.join("mutants", name), TARGET)
    # a suite that does not even pass on the reference kills nothing
    killed = bool(reference_ok) and not suite_passes()
    print(name, "killed" if killed else "SURVIVED")
    score += killed
print("CAI_BENCH_RESULT " + json.dumps({"tests_passed": score, "tests_total": 4}))
sys.exit(0 if score == 4 else 1)
