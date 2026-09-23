import time

from anihub.services.pausing import wait_while_paused


def test_wait_while_paused_blocks_until_unpaused():
    state = {"paused": True}
    calls = []

    def unpause_soon():
        time.sleep(0.1)
        state["paused"] = False

    import threading
    threading.Thread(target=unpause_soon, daemon=True).start()
    start = time.time()
    wait_while_paused(lambda: state["paused"], interval=0.02)
    calls.append(time.time() - start)
    assert calls[0] >= 0.08                            # actually waited, not a no-op


def test_wait_while_paused_returns_immediately_when_not_paused():
    start = time.time()
    wait_while_paused(lambda: False)
    assert time.time() - start < 0.05


def test_wait_while_paused_is_a_no_op_without_a_paused_callback():
    start = time.time()
    wait_while_paused(None)
    assert time.time() - start < 0.05


def test_wait_while_paused_stops_early_once_cancelled():
    start = time.time()
    wait_while_paused(lambda: True, cancelled=lambda: True, interval=0.02)
    assert time.time() - start < 0.1                   # cancelled overrides "still paused" and breaks out
