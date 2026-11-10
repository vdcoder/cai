"""Human-readable rendering of an invocation report."""
from __future__ import annotations

from .diagnostics import Diagnostic


def format_report(report: dict) -> str:
    lines: list[str] = []
    for d in report.get("diagnostics", []):
        lines.append(Diagnostic(**d).format())
    counts = report.get("directives")
    if counts is not None:
        used = ", ".join(f"{n} #{c}" for c, n in counts.items() if n) or "no directives"
        lines.append(f"cai {report['mode']}: {used}")
    for w in report.get("waits", []):
        lines.append(f"#wait {w['file']}:{w['line']}")
        lines.extend("    " + t for t in w["text"].splitlines())
    for kind in ("runs", "tests"):
        for r in report.get(kind, []):
            code = "-" if r["exit_code"] is None else r["exit_code"]
            cp = "" if r["checkpoint"] is None else f"  checkpoint={r['checkpoint']}"
            lines.append(f"[{r['kind']}] {r['name']}: {r['status']}  exit={code}  "
                         f"{r['duration_ms']:.1f}ms{cp}  ({r['file']}:{r['line']})")
            for stream in ("stdout", "stderr"):
                text = r[stream].rstrip("\n")
                if text:
                    mark = " (truncated)" if r[f"{stream}_truncated"] else ""
                    lines.append(f"  {stream}{mark}:")
                    lines.extend("    " + t for t in text.split("\n"))
        results = report.get(kind)
        if results:
            passed = sum(r["status"] == "passed" for r in results)
            lines.append(f"{kind}: {passed}/{len(results)} passed")
    if report.get("mode") == "check":
        for rel in report.get("would_modify", []):
            lines.append(f"would modify: {rel}")
    for rel in report.get("files_modified", []):
        lines.append(f"modified: {rel}")
    pending = report.get("pending", {})
    for kind in ("defers", "tests", "runs"):
        names = [b["name"] for b in pending.get(kind, [])]
        if names:
            lines.append(f"active {kind}: {', '.join(names)}")
    status = "ok" if report.get("ok") else f"FAILED (exit {report.get('exit_code')})"
    lines.append(f"result: {status}")
    return "\n".join(lines) + "\n"
