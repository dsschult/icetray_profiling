from __future__ import absolute_import, division, print_function


import socket
import subprocess
import logging
from hashlib import sha256

import requests

logger = logging.getLogger('results')


def get_gcc_version():
    return subprocess.check_output(['gcc','--version']).split(')')[1].split()[0]


class ElasicSearch(object):
    def __init__(self, hostname, basename='icetray_profile'):
        self.session = requests.Session()
        # try a connection
        r = self.session.get(hostname)
        r.raise_for_status()
        self.hostname = hostname+'/'+basename+'/'
        self.host = socket.gethostname()
        self.gcc = get_gcc_version()
    def send(self, name, value, date):
        value[host] = self.host
        value[gcc] = self.gcc
        value['date'] = date
        index_name = sha256(self.host+self.gcc+name+date).hexdigest()
        self.put(name, index_name, value)
    def put(self, name, index_name, data):
        r = None
        try:
            kwargs = {}
            if isinstance(data,dict):
                kwargs['json'] = data
            else:
                kwargs['data'] = data
            r = self.session.put(self.hostname+name+'/'+index_name, **kwargs)
            r.raise_for_status()
        except Exception:
            logger.warn('cannot put %s/%s to elasticsearch at %r', name,
                         index_name, self.hostname, exc_info=True)
            if r:
                logger.info('%r',r.content)


class Graphite(object):
    def __init__(self, address, prefix=None):
        if prefix:
            self.prefix = prefix
        else:
            # compute prefix
            hostname = socket.gethostname().replace('.','_')
            gcc = get_gcc_version().replace('.','_')
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
        logger.info('sending msg: %s',msg)
        self.socket.sendall(msg)
