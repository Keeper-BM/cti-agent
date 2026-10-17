"""Exception location diagnostics that omit messages, source lines, and local values."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def safe_exception_details(exc: Exception) -> str:
    frames = []
    trace = exc.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        path = Path(code.co_filename)
        try:
            location = str(path.resolve().relative_to(ROOT))
        except ValueError:
            location = path.name
        frames.append(f"{location}:{trace.tb_lineno}:{code.co_name}")
        trace = trace.tb_next
    error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    return f"exception_type={error_type}; frames={' -> '.join(frames[-20:])}"
