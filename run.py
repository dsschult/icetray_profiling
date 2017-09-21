#!/usr/bin/env python

from __future__ import absolute_import, division, print_function


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
    parser.add_argument('--skip',type=int,help='skip X days')
    args,other = parser.parse_known_args()

    start = datetime.strptime(args.start, '%Y-%m-%d')
    end = datetime.strptime(args.end, '%Y-%m-%d')
    while start < end:
        cmd = ['./build.py','--date', start.strftime('%Y-%m-%d')]
        cmd += other
        subprocess.call(cmd)
        start += timedelta(days=int(args.skip) if args.skip else 1)

if __name__ == '__main__':
    main()
