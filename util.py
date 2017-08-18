"""
Utilities to help monitor processes
"""
from __future__ import absolute_import, division, print_function


import os
import stat
import time
import threading
from functools import partial
import subprocess
import tempfile
import shutil
import logging

import psutil

def chmod(script):
    os.chmod(script, stat.S_IXUSR | stat.S_IWUSR | stat.S_IRUSR)

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


class TimeStats(object):
    def __init__(self):
        self.memory_factor = 1
        self.get_mem_factor()

    def get_mem_factor(self):
        tmpdir = tempfile.mkdtemp()
        try:
            src = os.path.join(tmpdir,'src.c')
            with open(src,'w') as f:
                f.write("""#include "stdlib.h"
#define N 10000000
int main(char** args){
    unsigned i=0;
    char* a = malloc(N);
    while(i<N) {
         a[i] = i%256;
         i++;
    }
    free(a);
    return 0;
}
""")
            bin = os.path.join(tmpdir,'bin')
            subprocess.check_call(['gcc','-o',bin,src], cwd=tmpdir)
            chmod(bin)
            out = subprocess.check_output(self.time_cmd+bin, shell=True, cwd=tmpdir, stderr=subprocess.STDOUT)
            stats = self.stats(out)
        except Exception:
            logging.info('memory factor error', exc_info=True)
            raise Exception('failed to compute memory factor')
        else:
            if stats['memory_max'] > 20000000:
                self.memory_factor = 4
            else:
                self.memory_factor = 1
        finally:
            shutil.rmtree(tmpdir)

    @property
    def time_cmd(self):
        """The preferred time command"""
        return "/usr/bin/time -f 'time: %U %S %e %P %M %t' "

    def is_time_output(self, output):
        return 'time:' in output

    def mem_convert(self, val):
        """Convert from time kB to bytes"""
        return int(val * 1024. / self.memory_factor)

    def stats(self, output):
        """Strip the cpu and memory from /usr/bin/time output"""
        if not output:
            raise Exception('stats not given the output')
        ret = {}
        pieces = output.replace('time:','').strip().split()
        logging.info('stat pieces %r',pieces)
        ret['cpu_user'] = float(pieces[0])
        ret['cpu_system'] = float(pieces[1])
        ret['cpu_walltime'] = float(pieces[2])
        ret['cpu_percent'] = float(pieces[3].replace('%',''))
        ret['memory_max'] = self.mem_convert(float(pieces[4]))
        ret['memory_avg'] = self.mem_convert(float(pieces[5]))
        return ret

