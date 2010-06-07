# -*- coding: utf-8 -*-

__all__ = ['RequestHandler', 'STOP', 'Map', 'Wrapper']

import logging
import types
import httplib
from inspect import getargspec
from .http import HttpException, RequestContext
from ..utils.url import URL


logger = logging.getLogger(__name__)


def prepare_handler(handler):
    '''Wrappes functions, that they can be usual RequestHandler's'''
    if type(handler) in (types.FunctionType, types.LambdaType,
                         types.MethodType):
        handler = FunctionWrapper(handler)
    elif isinstance(handler, Wrapper):
        handler = ChainWrapper(handler)
    return handler



class STOP(object): pass


class RequestHandler(object):
    '''Base class for all request handlers.'''

    def __init__(self):
        self._next_handler = None

    def __or__(self, next):
        next = prepare_handler(next)
        this = prepare_handler(self)
        if isinstance(next, Chain):
            handlers = [this] + next.handlers
        else:
            handlers = [this, next]
        return Chain(handlers)

    def __call__(self, rctx):
        return self.handle(rctx)

    def handle(self, rctx):
        '''This method should be overridden in subclasses.
        It always takes rctx object as only argument and returns it'''
        return rctx

    def next(self):
        return self._next_handler

    def trace(self, tracer):
        pass

    def __repr__(self):
        return '%s()' % self.__class__.__name__


class Chain(RequestHandler):

    def __init__(self, handlers):
        self.handlers = handlers

    def __or__(self, next):
        next = prepare_handler(next)

        last = self.handlers[-1]
        if isinstance(last, ChainWrapper):
            handlers = self.handlers[:-1] + [last | next]
        elif isinstance(next, Chain):
            handlers = self.handlers + next.handlers
        else:
            handlers = self.handlers + [next]
        return Chain(handlers)

    def __call__(self, rctx):
        for handler in self.handlers:
            if rctx is STOP: return STOP
            rctx = handler(rctx)
        return rctx

    def __repr__(self):
        return '%s(*%r)' % (self.__class__.__name__, self.handlers)


class ChainWrapper(RequestHandler):
    def __init__(self, wrapper, handler=None):
        self.wrapper = wrapper
        self.handler = handler or RequestHandler()

    def __or__(self, handler):
        handler = prepare_handler(handler)
        if self.handler is not None:
            handler = self.handler | handler
        return ChainWrapper(self.wrapper, handler)

    def __call__(self, rctx):
        return self.wrapper(rctx, self.handler)

    def __repr__(self):
        return '%s(%r, %r)' % (self.__class__.__name__, self.wrapper, self.handler)


class Wrapper(RequestHandler):
    '''
    A subclass of RequestHandler with other order of calling chained handlers.

    Base class for handlers wrapping execution of next chains. Subclasses should
    execute chained handlers in :meth:`handle` method by calling :object:`wrapped`.
    For example::

        class MyWrapper(Wrapper):
            def handle(self, rctx, wrapped):
                do_smth(rctx)
                try:
                    rctx = wrapped(rctx)
                finally:
                    do_smth2(rctx)
                return rctx

    *Note*: Be careful with exceptions. Chained method can throw exceptions including
    HttpExceptions. If you use wrappers to finalize some actions (close db connection,
    store http-sessions), it is recommended to use context managers
    ("with" statements) or try...finally constructions.
    '''

    def __call__(self, rctx, wrapped):
        return self.handle(rctx, wrapped)

    def handle(self, rctx, wrapped):
        '''Should be overriden in subclasses.'''
        logger.debug("Wrapper begin %r" % self)
        rctx = wrapped(rctx)
        logger.debug("Wrapper end %r" % self)
        return rctx

    def __repr__(self):
        return '%s() | %r' % (self.__class__.__name__, self._next_handler)


class Reverse(object):

    def __init__(self, urls, namespace, host=''):
        self.urls = urls
        self.namespace = namespace
        self.host = host

    def __call__(self, name, **kwargs):
        if self.namespace:
            local_name = self.namespace + '.' + name
            # if there are no url in local namespace, we search it in global
            url = self.urls.get(local_name) or self.urls[name]
        else:
            url = self.urls[name]

        subdomains, builders = url

        host = u'.'.join(subdomains)
        absolute = (host != self.host)
        path = u''.join([b(**kwargs) for b in builders])
        return URL(path, host=host)


class Map(RequestHandler):

    def __init__(self, *handlers, **kwargs):
        super(Map, self).__init__()
        # make sure all views are wrapped
        self.handlers = [prepare_handler(h) for h in handlers]
        self.__urls = self.compile_urls_map()
        self.rctx_class = kwargs.get('rctx_class', RequestContext)

    @property
    def urls(self):
        return self.__urls

    def handle(self, rctx):
        logger.debug('Map begin %r' % self)

        # construct url_for
        last_url_for = getattr(rctx.vals, 'url_for', None)
        if last_url_for is None:
            urls = self.urls
        else:
            urls = last_url_for.urls
        # urls - url map of the most parent Map instance.
        # namespace is controlled by Conf wrapper instance,
        # so we just use rctx.conf.namespace
        url_for = Reverse(urls, rctx.conf.namespace,
                          host=rctx.request.host.split(':')[0])
        rctx.vals['url_for'] = rctx.data['url_for'] = url_for

        for i in xrange(len(self.handlers)):
            handler = self.handlers[i]
            result = handler(rctx)
            if result is STOP:
                continue
            return result

        rctx.vals['url_for'] = rctx.data['url_for'] = last_url_for
        return STOP

    def _get_chain_members(self, handler):
        handlers = []
        if isinstance(handler, Chain):
            for h in handler.handlers:
                handlers.extend(self._get_chain_members(h))
        elif isinstance(handler, ChainWrapper):
            handlers.append(handler.wrapper)
            handlers.extend(self._get_chain_members(handler.handler))
        elif handler is not None:
            handlers.append(handler)
        return handlers

    def compile_urls_map(self):
        tracer = Tracer()
        for handler in self.handlers:
            item = handler
            for item in self._get_chain_members(handler):
                if isinstance(item, Map):
                    tracer.nested_map(item)
                    break
                item.trace(tracer)
            tracer.finish_step()
        return tracer.urls

    def __repr__(self):
        return '%s(*%r)' % (self.__class__.__name__, self.handlers)


class FunctionWrapper(RequestHandler):
    '''Wrapper for handler represented by function'''

    def __init__(self, func):
        super(FunctionWrapper, self).__init__()
        self.func = func

    def handle(self, rctx):
        # Now we will find which arguments are required by
        # wrapped function. And then get arguments values from rctx
        # data,
        # if there is no value argument we trying to get default value
        # from function specification otherwise Exception is raised
        argsspec = getargspec(self.func)
        arg_offset = 1 if type(self.func) is types.MethodType else 0
        if argsspec.defaults and len(argsspec.defaults) > 0:
            args = argsspec.args[arg_offset:-len(argsspec.defaults)]
            kwargs = {}
            for i, kwarg_name in enumerate(argsspec.args[-len(argsspec.defaults):]):
                if kwarg_name in rctx.data:
                    kwargs[kwarg_name] = rctx.data[kwarg_name]
                else:
                    kwargs[kwarg_name] = argsspec.defaults[i]
        else:
            args = argsspec.args[arg_offset:]
            kwargs = {}
        # form list of arguments values
        args = [rctx] + [rctx.data[arg_name] for arg_name in args[1:]]
        result = self.func(*args, **kwargs)
        if result is STOP:
            return STOP
        if isinstance(result, dict):
            rctx.data.update(result)
        return rctx

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.func.__name__)


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
