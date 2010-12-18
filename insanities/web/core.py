# -*- coding: utf-8 -*-

__all__ = ['WebHandler', 'List', 'HttpException', 'handler', 'Reverse']

import logging
import types
from inspect import getargspec
from .http import HttpException, Request, Response
from ..utils.stacked_dict import StackedDict
from .url import URL


logger = logging.getLogger(__name__)


def prepare_handler(handler):
    '''Wrapps functions, that they can be usual WebHandler's'''
    if type(handler) in (types.FunctionType, types.MethodType):
        handler = FunctionWrapper(handler)
    return handler


class WebHandler(object):
    '''Base class for all request handlers.'''

    def __or__(self, next_):
        if hasattr(self, '_next_handler'):
            self._next_handler | next_
        else:
            self._next_handler = prepare_handler(next_)
        return self

    def handle(self, env, data, next_handler):
        '''This method should be overridden in subclasses.'''
        return next_handler(env, data)

    def trace(self, tracer):
        pass

    def __repr__(self):
        return '%s()' % self.__class__.__name__

    def __call__(self, env, data):
        next_handler = self.get_next()
        result = self.handle(env, data, next_handler)
        return result

    def get_next(self):
        if hasattr(self, '_next_handler'):
            return self._next_handler
        #XXX: may be FunctionWrapper?
        return lambda e, d: None


class Reverse(object):

    def __init__(self, urls, namespace, host=''):
        self.urls = urls
        self.namespace = namespace or ''
        self.host = host

    def __call__(self, name, **kwargs):
        if name.startswith('.'):
            local_name = name.lstrip('.')
            up = len(name) - len(local_name) - 1
            if up != 0:
                ns = ''.join(self.namespace.split('.')[:-up])
            else:
                ns = self.namespace
            name = ns + '.' + local_name

        subdomains, builders = self.urls[name]

        host = u'.'.join(subdomains)
        absolute = (host != self.host)
        # path - urlencoded str
        path = ''.join([b(**kwargs) for b in builders])
        return URL(path, host=host)


class List(WebHandler):

    def __init__(self, *handlers, **kwargs):
        self.handlers = []
        for handler in handlers:
            self.handlers.append(prepare_handler(handler))

    def handle(self, env, data, next_handler):
        for handler in self.handlers:
            result = handler(env, data)
            if result is None:
                continue
            return result
        return next_handler(env, data)

    def trace(self, tracer):
        for row in self.grid:
            for item in row:
                if isinstance(item, List):
                    tracer.nested_map(item)
                    break
                item.trace(tracer)
            tracer.finish_step()
        return tracer.urls

    def __repr__(self):
        return '%s(*%r)' % (self.__class__.__name__, self.handlers)


class FunctionWrapper(WebHandler):
    '''Wrapper for handler represented by function'''

    def __init__(self, func):
        self.func = func

    def handle(self, env, data, next_handler):
        return self.func(env, data, next_handler)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.func.__name__)


handler = FunctionWrapper


class Tracer(object):

    def __init__(self):
        self.__urls = {}
        self._current_step = {}

    @property
    def urls(self):
        return self.__urls

    def check_name(self, name):
        if name in self.__urls:
            raise ValueError('Dublicating key "%s" in url map' % name)

    def finish_step(self):
        # get subdomains, namespaces if there are any
        subdomains = self._current_step.get('subdomain', [])
        subdomains.reverse()
        namespaces = self._current_step.get('namespace', [])

        # get url name and url builders if there are any
        url_name = self._current_step.get('url_name', None)
        builders = self._current_step.get('builder', [])
        nested_map = self._current_step.get('nested_map', None)

        # url name show that it is an usual chain (no nested map)
        if url_name:
            url_name = url_name[0]
            if namespaces:
                url_name = '.'.join(namespaces) + '.' + url_name
            self.check_name(url_name)
            self.__urls[url_name] = (subdomains, builders)
        # nested map (which also may have nested maps)
        elif nested_map:
            nested_map = nested_map[0]
            for k,v in nested_map.urls.items():
                if namespaces:
                    k = '.'.join(namespaces) + '.' + k
                self.check_name(k)
                self.__urls[k] = (v[0] + subdomains, builders + v[1])

        self._current_step = {}

    def __getattr__(self, name):
        return lambda e: self._current_step.setdefault(name, []).append(e)




#    def redirect_to(self, *args, **kwargs):
#        raise HttpException(303, url=self.vals.url_for(*args, **kwargs))
#
#    def render_to_response(self, template, data, content_type='text/html'):
#        data.update(self.data.as_dict())
#        data['VALS'] = self.vals
#        data['CONF'] = self.conf
#        data['REQUEST'] = self.request
#        rendered = self.vals.renderer.render(template, **data)
#        self.response.content_type = content_type
#        self.response.write(rendered)
#
#    def render_string(self, template, data):
#        data.update(self.data.as_dict())
#        data['VALS'] = self.vals
#        data['CONF'] = self.conf
#        data['REQUEST'] = self.request
#        return self.vals.renderer.render(template, **data)
#

# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
# TESTSSSSSS INITIAL
