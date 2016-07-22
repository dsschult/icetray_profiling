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

def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('--start',help='start date in iso format')
    parser.add_argument('--end',help='end date in iso format')
    parser.add_argument('--skip',help='skip X days')
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

    start = datetime.strptime(args.start, '%Y-%m-%d')
    end = datetime.strptime(args.end, '%Y-%m-%d')
    while start < end:
        cmd = ['./build.py','--date', start.strftime('%Y-%m-%d')]
        if args.url:
            cmd += ['--url', args.url]
        if args.benchmark:
            cmd += ['--benchmark', args.benchmark]
        if args.result_address:
            cmd += ['-a', args.result_address]
        if args.cmake_opts:
            cmd += ['--cmake-opts', args.cmake_opts]
        if args.debug:
            cmd += ['--debug']
        subprocess.call(cmd)
        start += timedelta(days=int(args.skip)+1 if args.skip else 1)

if __name__ == '__main__':
    main()
