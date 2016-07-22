#!/usr/bin/env python

from __future__ import print_function, division

import os
import time
import tempfile
import shutil
import subprocess
import socket
import logging

from datetime import datetime, timedelta

def get_projects(src_dir, url=False):
    output = subprocess.check_output(['svn','propget','svn:externals'],
                                     universal_newlines=True, cwd=src_dir)
    for line in output.split('\n'):
        line = line.strip()
        if (not line) or line[0] == '#':
            continue
        if url:
            yield line.split()
        else:
            yield line.split()[0]

def checkout(url, path, date):
    r = '{'+date.isoformat()+'}'
    subprocess.check_call(['svn','co','-r',r,'--depth','immediates',url,path])
    for p,p_url in get_projects(path,url=True):
        subprocess.check_call(['svn','co','-r',r,p_url,os.path.join(path,p)])

def build(src_path, build_path, cmake_opts=None):
    if not os.path.exists(build_path):
        os.makedirs(build_path)

    projects = set(get_projects(src_path))
    counters = ('cpu',) #,'memory','disk')
    ret = {'make.{}.{}'.format(p,c): 0 for p in projects for c in counters}

    cmd = ['cmake', '-DCMAKE_BUILD_TYPE=Release']
    if cmake_opts:
        cmd.extend(cmake_opts.split())
    cmd += [src_path]
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=build_path)
    ret['cmake.memory'] = os.wait4(proc.pid, 0)[2].ru_maxrss
    ret['cmake.cpu'] = time.time()-start

    proc = subprocess.Popen(['make'], stdout=subprocess.PIPE, cwd=build_path)
    while proc.poll() is None:
        try:
            start = time.time()
            line = proc.stdout.readline().strip()
            print(line)
            output = line[7:].strip().split()[-1]
            end = time.time()
            for p in projects:
                if output.startswith(p):
                    ret['make.'+p+'.cpu'] += end-start
                    break
        except Exception:
            logging.info('error reading make stdout',exc_info=True)
    return ret

def run(path, program):
    subprocess.check_call('./env-shell.sh /usr/bin/time '+program, shell=True, cwd=path)

def convert_to_unix_time(date):
    epoch = datetime.utcfromtimestamp(0)
    return int((date-epoch).total_seconds())


class Results(object):
    def __init__(self, address, prefix='icetray'):
        self.prefix = prefix

        # set up socket
        port = 2003
        if ':' in address:
            address, port = address.split(':')
            port = int(port)
        addr = socket.getaddrinfo(address, port, 0, 0, socket.IPPROTO_TCP)
        for a in addr:
            try:
                s = socket.socket(*a[:3])
                s.connect(a[-1])
            except Exception:
                pass
            else:
                break
        else:
            raise Exception('cannot connect to %s:%d'%(address,port))
        self.socket = s

    def send(self, name, value, date):
        msg = '%s.%s %f %d\n'%(self.prefix, name, value,
                               convert_to_unix_time(date))
        logging.info('sending msg: %s',msg)
        self.socket.sendall(msg)


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-d','--date',help='date in iso format')
    parser.add_argument('--url',help='url to metaproject')
    parser.add_argument('--benchmark',help='benchmark to run')
    parser.add_argument('-a','--result-address',dest='result_address',
                        help='address to send results to')
    parser.add_argument('--cmake-opts',dest='cmake_opts',default=None,
                        help='additional cmake options')
    parser.add_argument('--debug',default=False,action='store_true',
                        help='debug logging')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARN)

    d = datetime.strptime(args.date, '%Y-%m-%d')

    tmpdir = tempfile.mkdtemp(dir=os.getcwd())
    try:
        srcdir = os.path.join(tmpdir,'src')
        builddir = os.path.join(tmpdir,'build')
        checkout(args.url, srcdir, d)
        ret = build(srcdir, builddir,cmake_opts=args.cmake_opts)
        #run(builddir, args.benchmark)

        r = Results(args.result_address)
        for project in ret:
            r.send(project, ret[project], d)

    finally:
        shutil.rmtree(tmpdir)

if __name__ == '__main__':
    main()
