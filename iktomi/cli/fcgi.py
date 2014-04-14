# -*- coding: utf-8 -*-

import os
import sys
import time
import errno
import signal
import logging
logger = logging.getLogger(__name__)

from .base import Cli
from iktomi.utils.system import safe_makedirs, is_running, terminate, \
                                doublefork


def flup_fastcgi(wsgi_app, bind, cwd=None, pidfile=None, logfile=None,
                 daemonize=False, umask=None, **params):
    if params.pop('preforked', False):
        from flup.server import fcgi_fork as fcgi
    else:
        from flup.server import fcgi
    if daemonize:
        if os.path.isfile(pidfile):
            with open(pidfile, 'r') as f:
                try:
                    pid = int(f.read())
                except ValueError:
                    pid = None

            if pid is not None and  is_running(pid):
                sys.exit('Already running (PID: %r)' % pid)
            elif pid is not None:
                logger.info('PID file was pointing to nonexistent process %r',
                            pid)
            else:
                logger.info('PID file should contain a number')
        doublefork(pidfile, logfile, cwd, umask)
    logger.info('Starting FastCGI server (flup), current working dir %r' % cwd)
    fcgi.WSGIServer(wsgi_app, bindAddress=bind, umask=umask,
                    debug=False, **params).run()


class Flup(Cli):

    def __init__(self, app, bind='', logfile=None, pidfile=None,
                 cwd='.', umask=002, fastcgi_params=None):
        self.app = app
        self.cwd = os.path.abspath(cwd)
        if ':' in bind:
            host, port = bind.split(':')
            port = int(port)
        else:
            bind = os.path.abspath(bind or os.path.join(self.cwd, 'fcgi.sock'))
            safe_makedirs(bind)
        self.bind = bind
        self.umask = umask
        self.logfile = logfile or os.path.join(self.cwd, 'fcgi.log')
        self.pidfile = pidfile or os.path.join(self.cwd, 'fcgi.pid')
        self.fastcgi_params = fastcgi_params or {}

    def command_start(self, daemonize=False):
        if daemonize:
            safe_makedirs(self.logfile, self.pidfile)
        flup_fastcgi(self.app, bind=self.bind, pidfile=self.pidfile,
                     logfile=self.logfile, daemonize=daemonize,
                     cwd=self.cwd, umask=self.umask, **self.fastcgi_params)

    def command_stop(self):
        if self.pidfile:
            if not os.path.exists(self.pidfile):
                sys.exit("Pidfile %r doesn't exist" % self.pidfile)
            with open(self.pidfile) as pidfile:
                pid = int(pidfile.read())
            for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]:
                try:
                    if terminate(pid, sig, 3):
                        os.remove(self.pidfile)
                        sys.exit()
                except OSError, exc:
                    if exc.errno != errno.ESRCH:
                        raise
                    elif sig == signal.SIGINT:
                        sys.exit('Not running')
        sys.exit('No pidfile provided')

    def command_restart(self):
        self.command_stop()
        self.command_start()
