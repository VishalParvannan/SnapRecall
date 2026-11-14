"""Helper process that loads one model and answers calls from SnapRecall (see models.BackgroundModels).

Started as `python model_worker.py`, never imported by the app, so it can't run app.py again.
Messages are pickles over stdin/stdout:
    app -> worker: sys.path, then (loader, config), then (method, args) per call
    worker -> app: ("ok", (name, methods) | None) or ("error", message), then ("ok", result) |
                   ("error", message) per call
The worker exits when stdin closes, which happens when SnapRecall stops (or crashes).
"""
import os
import pickle
import sys


def main() -> None:
    # Keep the real stdout for messages; anything libraries print goes to stderr instead.
    out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    inp = sys.stdin.buffer

    def send(message) -> None:
        pickle.dump(message, out, protocol=pickle.HIGHEST_PROTOCOL)
        out.flush()

    try:
        sys.path[:0] = [p for p in pickle.load(inp) if p not in sys.path]
        loader, config = pickle.load(inp)
    except EOFError:
        return
    from models import _MODEL_METHODS, _load_problem

    try:
        model = loader(config)
    except Exception as exc:
        send(("error", _load_problem(exc)))
        return
    methods = sorted(m for m in _MODEL_METHODS if callable(getattr(model, m, None)))
    send(("ok", None if model is None else (model.name, methods)))
    while True:
        try:
            method, args = pickle.load(inp)
        except (EOFError, OSError):
            return
        try:
            send(("ok", getattr(model, method)(*args)))
        except Exception as exc:
            send(("error", f"{exc.__class__.__name__}: {exc}"))


if __name__ == "__main__":
    main()
