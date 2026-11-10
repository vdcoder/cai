"""CAI runner for Python workspaces: executes the directive body.

Protocol: body on stdin, cwd = snapshot directory, metadata in CAI_* variables.
"""
import os
import sys

body = sys.stdin.read()
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
exec(compile(body, f"<cai {os.environ.get('CAI_KIND')} {os.environ.get('CAI_NAME')}>", "exec"), {"__name__": "__cai__"})
