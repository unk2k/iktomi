# -*- coding: utf-8 -*-

import sys, os
from insanities.web.wsgi import WSGIHandler
from . import CommandNotFound

__all__ = ['server']


class CommandDigest(object):

    def default(self, *args, **kwargs):
        '''This method will be called if command_name in __call__ is None'''
        sys.stdout.write(self.__class__.__doc__)

    def __call__(self, command_name, *args, **kwargs):
        if command_name is None:
            self.default(*args, **kwargs)
        elif command_name == 'help':
            sys.stdout.write(self.__doc__)
            for k in self.__dict__.keys():
                if k.startswith('command_'):
                    sys.stdout.write(k.__doc__)
        elif hasattr(self, 'command_'+command_name):
            getattr(self, 'command_'+command_name)(*args, **kwargs)
        else:
            sys.stdout.write(self.__class__.__doc__)
            raise CommandNotFound()


class server(CommandDigest):
    '''
    Development server:

        $ python manage.py server:serve
    
    FastCGI server:
        $ python manage.py server:runfastcgi 
            Available options:
                method=fork
                [
                    host=212.5.66.4
                    port=2345
                or
                    socket=/tmp/site.sock
                ]
                pid=/tmp/site.pid
                daemon=True
                maxrequest=300
                log=/home/site/mylogs.log
                loglevel=INFO
        # Note: The command require flup
    '''

    def __init__(self, app):
        self.app = app

    def dir_exist(self, file):
        dir = os.path.dirname(file)
        if not os.path.isdir(dir):
            raise ValueError('%s must be exist' % dir)

    def command_serve(self, host='', port='8000'):
        '''python manage.py server:serve [host] [port]'''
        import logging
        logging.basicConfig(level=logging.DEBUG)
        from wsgiref.simple_server import make_server
        from insanities.web.wsgi import WSGIHandler
        try:
            port = int(port)
        except ValueError:
            raise ValueError('Please provide valid port value insted of "%s"' % port)
        server = make_server(host, port, WSGIHandler(self.app))
        try:
            logging.debug('Insanities server is running on port %s\n' % port)
            server.serve_forever()
        except KeyboardInterrupt:
            pass

    def command_debug(self, url):
        '''python manage.py server:debug url'''
        import pdb
        from ..web.http import RequestContext
        rctx = RequestContext.blank(url)
        try:
            self.app(rctx)
        except Exception, e:
            pdb.post_mortem(e)


    def command_runfastcgi(self, method='fork', host=None, port=None, \
            socket=None, pid=None, daemon=True, maxrequest=300, log=None, loglevel='INFO'):
        if log:
            levels = {
                    'INFO': logging.INFO,
                    'DEBUG': logging.DEBUG,
                    }
            logging.basicConfig(
                    filename=log,
                    level=levels[loglevel],
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                    )
        # XXX do it here
        if method not in ['fork', 'threaded']:
            raise ValueError('method must be "fork" or "threaded"')
        if (host is None and port is None) == (socket is None):
            raise ValueError('You must use host and port or socket')
        if pid is None:
            raise ValueError('pid is required')
        self.dir_exist(pid)

        if method == 'fork':
            from flup.server import fcgi_fork as fcgi
        else:
            from flup.server import fcgi

        if host and port:
            try:
                int(port)
            except ValueError:
                raise ValueError('port must be integer only')
            bind = ':'.join([host, port])
        else:
            self.dir_exist(socket)
            bind = socket

        try:
            f = open(pid, 'r')
            proc_id = int(f.read())
            f.close()
        except (IOError, ValueError):
            pass
        else:
            try:
                os.kill(proc_id, 0)
                raise ValueError('Process allready runing')
            except OSError:
                pass

        if daemon:
            if os.fork() > 0:
                os._exit(0)
            with open(pid, 'w') as f:
                f.write(str(os.getpid()))
        fcgi.WSGIServer(WSGIHandler(self.app), bindAddress=bind, umask=777, debug=True).run()
