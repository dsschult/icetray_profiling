"""
Utilities to help monitor processes
"""

import time
import threading
from functools import partial

import psutil

def get_stats(pid):
    ret = {}
    proc = psutil.Process(pid)
    ret['memory'] = proc.memory_info().rss
    ret['cpu_percent'] = proc.cpu_percent()
    for p in proc.children(recursive=True):
        try:
            ret['memory'] += p.memory_info().rss
            ret['cpu_percent'] += p.cpu_percent()
        except:
            pass
    return ret

class Stats(object):
    def __init__(self, poll_interval=0.1):
        self.running = False
        self.poll_interval = poll_interval
        self.stats = {}
    def monitor(self, pid):
        self.running = True
        threading.Thread(target=partial(self._run, pid)).start()
    def stop(self):
        self.running = False
    def _run(self, pid):
        while self.running:
            self.stats = get_stats(pid)
            time.sleep(self.poll_interval)
