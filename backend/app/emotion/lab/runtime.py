import os
import threading

from backend.app.emotion.lab.worker import loop


def start():
    if os.getenv('EMOJI_LAB_WORKER', '0') != '1':
        return None
    stop = threading.Event()
    thread = threading.Thread(
        target=loop,
        args=(stop,),
        daemon=True,
        name='happyclass-analysis-worker',
    )
    thread.start()
    return stop, thread


def shutdown(handle):
    if handle is None:
        return
    stop, thread = handle
    stop.set()
    thread.join(timeout=3)


def status():
    enabled = os.getenv('EMOJI_LAB_WORKER', '0') == '1'
    active = any(
        thread.name == 'happyclass-analysis-worker' and thread.is_alive()
        for thread in threading.enumerate()
    )
    return {
        'enabled_in_web_process': enabled,
        'active_in_web_process': active,
    }
