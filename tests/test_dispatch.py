import threading

from soundboard.ui.dispatch import Dispatcher


class FakeRoot:
    """Collects after() callbacks so the test can drain them by hand."""

    def __init__(self):
        self.pending = []

    def after(self, _ms, fn):
        self.pending.append(fn)


def run_until(root, condition, timeout=2.0):
    done = threading.Event()
    deadline = threading.Timer(timeout, done.set)
    deadline.start()
    while not condition() and not done.is_set():
        for fn in root.pending[:]:
            root.pending.remove(fn)
            fn()
    deadline.cancel()


def test_background_error_reaches_on_error():
    root = FakeRoot()
    dispatch = Dispatcher(root)
    got = []

    def work():
        raise ValueError("boom")

    dispatch.run_in_background(work, on_done=got.append, on_error=lambda e: got.append(("error", str(e))))
    run_until(root, lambda: got)
    assert got == [("error", "boom")]


def test_background_result_reaches_on_done():
    root = FakeRoot()
    dispatch = Dispatcher(root)
    got = []
    dispatch.run_in_background(lambda: 42, on_done=got.append, on_error=got.append)
    run_until(root, lambda: got)
    assert got == [42]
