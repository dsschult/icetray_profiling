#!/usr/bin/env python

from __future__ import absolute_import, division, print_function

import os
import time
import tempfile
import shutil
import subprocess
import logging
from collections import OrderedDict

from datetime import datetime, timedelta

from util import Stats, TimeStats, chmod

from results import Graphite, ElasicSearch

logger = logging.getLogger('build')

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
        for c in ('cpu_walltime', 'cpu_user', 'cpu_system', 'cpu_percent_avg', 'memory_avg'):
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
    ret['cmake.cpu_walltime'] = time.time()-start

    proc = subprocess.Popen(['make','all'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=build_path, env=environ)
    last_project = None
    last_line = None
    time_line = None
    while proc.poll() is None:
        try:
            line = proc.stdout.readline().strip()
            if not line:
                continue
            print(line)
            if s.is_time_output(line):
                time_line = line
            else:
                last_line = line
                continue

            try:
                if last_line.startswith('Linking'):
                    output = last_line.split('/')[-1].strip()
                else:
                    output = last_line[7:].strip().split()[-1]
                for p in projects:
                    if p in output.split('/')[0]:
                        break
                else:
                    raise Exception()
            except Exception:
                logger.info('error parsing last_line for project')
                if last_project:
                    p = last_project
                else:
                    continue

            time_stats = s.stats(time_line)
            ret['make.'+p+'.cpu_walltime'] += time_stats['cpu_walltime']
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

    subprocess.check_call(['make','test-bins'], cwd=build_path)

    for k in list(ret):
        if k.startswith('make') and k.endswith('avg'):
            ret[k.replace('avg','max')] = int(max(ret[k])) if ret[k] else 0
            ret[k] = sum(ret[k])//len(ret[k]) if ret[k] else 0

    return ret

def run(path, program):
    s = TimeStats()
    try:
        out = subprocess.check_output('./env-shell.sh '+s.time_cmd+' '+program, stderr=subprocess.STDOUT, shell=True, cwd=path)
    except subprocess.CalledProcessError as e:
        logger.warn('call failed: %r', e.output)
        raise
    for line in out.split('\n'):
        line = line.strip()
        if s.is_time_output(line):
            return s.stats(line)
    raise Exception('did not get time stats')

def convert_to_unix_time(date):
    epoch = datetime.utcfromtimestamp(0)
    return int((date-epoch).total_seconds())

def walk_path(path):
    if path in walk_path.cache:
        return walk_path.cache[path]
    ret = {}
    for root,dirs,files in os.walk(path):
        for f in files:
            ret[f] = os.path.join(root,f)
    walk_path.cache[path] = ret
    return ret
walk_path.cache = {}

def tests(path):
    out = subprocess.check_output(['ctest','-N'], cwd=path)
    test_paths = OrderedDict() # maintain test order for those that need it
    for l in out.split("\n"):
        if not l.startswith("  Test"):
            continue
        test_name = l.split(":",1)[-1].strip()
        proj,name = test_name.split("::")
        if name.endswith('.py'):
            # find python test
            paths = walk_path(os.path.join(path,proj,'resources'))
            for f in paths:
                if f == name:
                    test_paths[test_name] = 'python '+os.path.join(proj,'resources',paths[f])
                    break
            else:
                raise Exception('cannot find test %s::%s'%(proj,test_name))
        else:
            # binary test
            t = os.path.join('bin','%s-%s'%(proj,name))
            if not os.path.isfile(os.path.join(path,t)):
                raise Exception('cannot find test %s'%t)
            test_paths[test_name] = t+' -a'

    # now run tests
    ret = {}
    for name in test_paths:
        try:
            r = run(path,test_paths[name])
        except Exception:
            logger.warn("%s test failed", name, exc_info=True)
            continue
        name = name.replace('::','_').replace('.','_').replace('/','_')
        for k in r:
            ret['test.'+name+'.'+k] = r[k]
    return ret


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
    parser.add_argument('--elastic',default=False,action='store_true',
                        help='write result to elasic search')
    parser.add_argument('--graphite',default=False,action='store_true',
                        help='write result to graphite')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARN)

    d = datetime.strptime(args.date, '%Y-%m-%d')

    tmpdir = tempfile.mkdtemp(dir=os.getcwd())
    try:
        srcdir = os.path.join(tmpdir,'src')
        builddir = os.path.join(tmpdir,'build')
        checkout(args.url, srcdir, d)
        ret = build(srcdir, builddir,cmake_opts=args.cmake_opts)
        if args.benchmark:
            run(builddir, args.benchmark)
        else:
            ret.update(tests(builddir))

        if args.graphite:
            kwargs = {}
            if args.prefix:
                kwargs['prefix'] = args.prefix
            r = Graphite(args.result_address, **kwargs)
            for project in ret:
                r.send(project, ret[project], d)
        elif args.elastic:
            kwargs = {}
            if args.prefix:
                kwargs['basename'] = args.prefix
            r = ElasicSearch(args.result_address)
            for project in ret:
                r.send(project, ret[project], d)
        else:
            for project in ret:
                print(d, project, ret[project])
    finally:
        shutil.rmtree(tmpdir)

if __name__ == '__main__':
    main()
