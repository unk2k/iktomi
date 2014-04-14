# -*- coding: utf-8 -*-

__all__ = ['Reverse', 'UrlBuildingError']

from .url import URL
from .url_templates import UrlBuildingError
from ..utils import cached_property



class Location(object):
    '''
    Class representing an endpoint in the reverse url map.
    '''
    def __init__(self, *builders, **kwargs):
        self.builders = list(builders)
        self.subdomains = kwargs.get('subdomains', [])

    @property
    def need_arguments(self):
        for b in self.builders:
            if b._url_params:
                return True
        return False

    def build_path(self, reverse, **kwargs):
        result = []
        for b in self.builders:
            result.append(b(**kwargs))
        return ''.join(result)

    def build_subdomians(self, reverse):
        subdomains = [getattr(x, 'primary', x) 
                      for x in self.subdomains
                      if getattr(x, 'primary', x)]
        return u'.'.join(subdomains)

    @property
    def url_arguments(self):
        return reduce(lambda x,y: x|set(y._url_params), self.builders, set())

    def __eq__(self, other):
        return isinstance(other, self.__class__) and \
               self.builders == other.builders and self.subdomains == other.subdomains

    def __repr__(self):
        return '%s(*%r, subdomains=%r)' % (self.__class__.__name__, self.builders, self.subdomains)



class Reverse(object):
    '''
    Object incapsulating reverse url map and methods needed to build urls
    by their names, namespaces and parameters.

    Usually an instance of `Reverse` can be found in `env.root`.
    '''
    def __init__(self, scope, location=None, path='', host='', ready=False, 
                 need_arguments=False, bound_env=None, parent=None,
                 finalize_params=None):
        # location is stuff containing builders for current reverse step
        # (builds url part for particular namespace or endpoint)
        self._location = location
        # scope is a dict having nested namespace and endpoint names as key and
        # (location, nested scope) tuple as values for the current namespace
        self._scope = scope
        self._path = path
        self._host = host
        self._ready = ready
        self._need_arguments = need_arguments
        self._is_endpoint = (not self._scope) or ('' in self._scope)
        self._is_scope = bool(self._scope)
        self._bound_env = bound_env
        self._parent = parent
        self._finalize_params = finalize_params or {}

    def _attach_subdomain(self, host, location):
        subdomain = location.build_subdomians(self)
        if not host:
            return subdomain
        if subdomain:
            return subdomain + '.' + host
        return host

    def __call__(self, **kwargs):
        '''
        Get a copy of the `Reverse` but with same namespace and same url name,
        but with arguments attached.
        '''
        if self._ready:
            raise UrlBuildingError('Endpoint do not accept arguments')
        if self._is_endpoint or self._need_arguments:
            finalize_params = {}
            path, host = self._path, self._host
            if self._location:
                host = self._attach_subdomain(host, self._location)
                path += self._location.build_path(self, **kwargs)
            if '' in self._scope:
                finalize_params = kwargs
            return self.__class__(self._scope, self._location, path=path, host=host,
                                  bound_env=self._bound_env, 
                                  ready=self._is_endpoint,
                                  parent=self._parent,
                                  finalize_params=finalize_params)
        raise UrlBuildingError('Not an endpoint {}'.format(repr(self)))

    def __getattr__(self, name):
        '''
        Get subreverse, a reverse in current namespace with the name, equal
        to the attribute name::

            env.root.index # getattr(env.root, 'index')
        '''
        if self._is_scope and name in self._scope:
            if self._need_arguments:
                return getattr(self(), name)
            location, scope = self._scope[name]
            path = self._path
            host = self._host
            ready = not location.need_arguments
            if ready:
                path += location.build_path(self)
                host = self._attach_subdomain(host, location)
            return self.__class__(scope, location, path, host, ready,
                                  bound_env=self._bound_env,
                                  parent=self,
                                  need_arguments=location.need_arguments)
        raise UrlBuildingError('Namespace or endpoint "%s" does not exist'
                               ' in "%r"' % (name, self))

    def _finalize(self):
        # deferred build of the last part of url for endpoints that
        # also have nested scopes
        # i.e. finalization of __call__ for as_url
        if self._need_arguments:
            self = self()
        path, host = self._path, self._host
        location = self._scope[''][0]
        host = self._attach_subdomain(host, location)
        path += location.build_path(self, **self._finalize_params)
        return self.__class__({}, self._location, path=path, host=host,
                              bound_env=self._bound_env, 
                              parent=self._parent,
                              ready=self._is_endpoint)


    @cached_property
    def url_arguments(self):
        args = set()
        if self._is_endpoint or self._need_arguments:
            if self._location:
                args |= self._location.url_arguments
            if self._is_endpoint and self._scope:
                args |= self._scope[''][0].url_arguments
        return args

    def _build_url_silent(self, _name, **kwargs):
        subreverse = self
        used_args = set()
        for part in _name.split('.'):
            if not subreverse._ready and subreverse._need_arguments:
                used_args |= subreverse.url_arguments
                subreverse = subreverse(**kwargs)
            subreverse = getattr(subreverse, part)
        if not subreverse._ready and subreverse._is_endpoint:
            used_args |= subreverse.url_arguments
            subreverse = subreverse(**kwargs)
        return used_args, subreverse

    def build_subreverse(self, _name, **kwargs):
        '''
        String-based reverse API. Returns subreverse object::

            env.root.build_subreverse('user', user_id=1).profile
        '''
        _, subreverse = self._build_url_silent(_name, **kwargs)
        return subreverse

    def build_url(self, _name, **kwargs):
        '''
        String-based reverse API. Returns URL object::

            env.root.build_url('user.profile', user_id=1)

        Checks that all necessary arguments are provided and all 
        provided arguments are used.
        '''
        used_args, subreverse =  self._build_url_silent(_name, **kwargs)

        if set(kwargs).difference(used_args):
            raise UrlBuildingError('Not all arguments are used during URL building: %s' %
                                   ', '.join(set(kwargs).difference(used_args)))
        return subreverse.as_url

    @property
    def as_url(self):
        '''
        Reverse object converted to `web.URL`.

        If Reverse is bound to env:
            * try to build relative URL,
            * use current domain name, port and scheme as default
        '''
        if '' in self._scope:
            return self._finalize().as_url

        if not self._is_endpoint:
            raise UrlBuildingError('Not an endpoint {}'.format(repr(self)))

        if self._ready:
            path, host = self._path, self._host
        else:
            return self().as_url
            #raise UrlBuildingError('Not an endpoint {}'.format(repr(self)))

        # XXX there is a little mess with `domain` and `host` terms
        if ':' in host:
            domain, port = host.split(':')
        else:
            domain = host
            port = None

        if self._bound_env:
            request = self._bound_env.request
            scheme_port = {'http': '80',
                           'https': '443'}.get(request.scheme, '80')

            # Domain to compare with the result of build.
            # If both values are equal, domain part can be hidden from result.
            # Take it from route_state, not from env.request, because
            # route_state contains domain values with aliased replaced by their
            # primary value
            primary_domain = self._bound_env._route_state.primary_domain
            host_split = request.host.split(':')
            request_domain = host_split[0]
            request_port = host_split[1] if len(host_split) > 1 else scheme_port
            port = port or request_port

            return URL(path, host=domain or request_domain,
                       port=port if port != scheme_port else None,
                       schema=request.scheme,
                       show_host=host and (domain != primary_domain \
                                           or port != request_port))
        return URL(path, host=domain, port=port, show_host=True)

    def __str__(self):
        '''URLencoded representation of the URL'''
        return str(self.as_url)

    @classmethod
    def from_handler(cls, handler):
        '''
        Get unbound instance of the class related to given handler::

            app = web.cases(..)
            Reverse.from_handler(app)
        '''
        return cls(handler._locations())

    def bind_to_env(self, bound_env):
        '''
        Get a copy of the reverse, bound to `env` object. 
        Can be found in env.root attribute::

            # done in iktomi.web.app.Application
            env.root = Reverse.from_handler(app).bind_to_env(env)
        '''
        return self.__class__(self._scope, self._location,
                              path=self._path, host=self._host,
                              ready=self._ready,
                              need_arguments=self._need_arguments,
                              finalize_params=self._finalize_params,
                              parent=self._parent,
                              bound_env=bound_env)

    def __repr__(self):
        return '{}(path=\'{}\', host=\'{}\')'.format(
                self.__class__.__name__, self._path, self._host)
