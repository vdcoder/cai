"""Example CAI runner for #run experiments.

CAI starts this script with the snapshot directory as working directory and
the experiment body on standard input. Here the body is Python code that may
import the project's modules from src/.
"""
import os
import sys

body = sys.stdin.read()
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
label = f"<#{os.environ['CAI_KIND']} {os.environ['CAI_NAME']} @ checkpoint {os.environ['CAI_CHECKPOINT'] or 'final'}>"
exec(compile(body, label, "exec"), {"__name__": "__cai__"})
