"""Example CAI runner for #test blocks: identical protocol, a failing
assertion makes the process exit non-zero, which CAI reports as "failed"."""
import runpy
import os

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_experiment.py"), run_name="__main__")
