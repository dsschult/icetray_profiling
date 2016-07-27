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

from util import Stats, TimeStats, chmod

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

    s = TimeStats()
    # fake CC and CXX
    cc = os.path.join(build_path,'cc.sh')
    cxx = os.path.join(build_path,'cxx.sh')
    with open(cc,'w') as f:
        f.write('#!/bin/sh\n')
        f.write(s.time_cmd+(os.environ['CC'] if 'CC' in os.environ else 'gcc')+' $@\n')
    with open(cxx,'w') as f:
        f.write('#!/bin/sh\n')
        f.write(s.time_cmd+(os.environ['CXX'] if 'CXX' in os.environ else 'g++')+' $@\n')
    chmod(cc)
    chmod(cxx)
    environ = os.environ.copy()
    environ['CC'] = cc
    environ['CXX'] = cxx

    projects = set(get_projects(src_path))
    ret = {}
    for p in projects:
        for c in ('walltime', 'cpu_user', 'cpu_system', 'cpu_percent_avg', 'memory_avg'):
            k = 'make.{}.{}'.format(p,c)
            if c.endswith('avg'):
                ret[k] = []
            else:
                ret[k] = 0.

    cmd = ['cmake', '-DCMAKE_BUILD_TYPE=Release']
    if cmake_opts:
        cmd.extend(cmake_opts.split())
    cmd += [src_path]
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=build_path, env=environ)
    ret['cmake.memory_max'] = os.wait4(proc.pid, 0)[2].ru_maxrss
    ret['cmake.time'] = time.time()-start

    proc = subprocess.Popen(['make'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=build_path, env=environ)
    last_project = None
    last_line = None
    time_line = None
    while proc.poll() is None:
        try:
            line = proc.stdout.readline().strip()
            print(line)
            if s.is_time_output(line):
                time_line = line
            else:
                last_line = line
                continue

            if last_line.startswith('Linking'):
                output = last_line.split('/')[-1].strip()
            else:
                output = last_line[7:].strip().split()[-1]
            for p in projects:
                if p in output.split('/')[0]:
                    break
            else:
                if last_project:
                    p = last_project
                else:
                    continue

            time_stats = s.stats(time_line)
            ret['make.'+p+'.walltime'] += time_stats['cpu_walltime']
            ret['make.'+p+'.cpu_user'] += time_stats['cpu_user']
            ret['make.'+p+'.cpu_system'] += time_stats['cpu_system']
            ret['make.'+p+'.cpu_percent_avg'].append(time_stats['cpu_percent'])
            ret['make.'+p+'.memory_avg'].append(time_stats['memory_max'])
            last_project = p
        except Exception:
            logging.info('error reading make stdout',exc_info=True)
        except:
            proc.terminate()
            break

    for k in list(ret):
        if k.startswith('make') and k.endswith('avg'):
            ret[k.replace('avg','max')] = int(max(ret[k])) if ret[k] else 0
            ret[k] = sum(ret[k])//len(ret[k]) if ret[k] else 0

    return ret

def run(path, program):
    subprocess.check_call('./env-shell.sh /usr/bin/time '+program, shell=True, cwd=path)

def convert_to_unix_time(date):
    epoch = datetime.utcfromtimestamp(0)
    return int((date-epoch).total_seconds())


class Results(object):
    def __init__(self, address, prefix=None):
        if prefix:
            self.prefix = prefix
        else:
            # compute prefix
            hostname = socket.gethostname().replace('.','_')
            gcc = subprocess.check_output(['gcc','--version']).split(')')[1].split()[0].replace('.','_')
            self.prefix = 'icetray.{}.{}'.format(hostname,gcc)

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
    parser.add_argument('--prefix',help='prefix to apply to stats')
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

        kwargs = {}
        if args.prefix:
            kwargs['prefix'] = args.prefix
        r = Results(args.result_address, **kwargs)
        for project in ret:
            r.send(project, ret[project], d)

    finally:
        shutil.rmtree(tmpdir)

if __name__ == '__main__':
    main()
