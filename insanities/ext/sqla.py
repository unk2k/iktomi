
from sqlalchemy import orm, types, create_engine
from sqlalchemy.ext import declarative
from sqlalchemy.orm.query import Query
from sqlalchemy import create_engine

from insanities.utils import cached_property
from insanities.web import HttpException, Wrapper


class DBSession(orm.session.Session):

    # XXX delayed actions are also implemented in one of projects

    def get(self, query, **kwargs):
        if not isinstance(query, Query):
            query = self.query(query)
        if kwargs:
            query = query.filter_by(**kwargs)
        return query.first()

    def get_or_404(self, query, **kwargs):
        obj = self.get(query, **kwargs)
        if obj is None:
            raise HttpException(404)
        return obj


class sqla_session(Wrapper):

    def __init__(self, uri, param_name='db', query_cls=Query,
                 class_=DBSession, engine_params=None):
        super(sqla_session, self).__init__()
        self.param_name = param_name
        engine_params = engine_params if engine_params else {}
        engine = create_engine(uri, **engine_params)
        #engine.logger.name += '(%s)' % ref
        self.maker = orm.sessionmaker(class_=class_, query_cls=query_cls,
                                      bind=engine, autoflush=False,
                                      autocommit=False)

    def handle(self, rctx, wrapped):
        db = self.maker()
        rctx.vals[self.param_name] = db
        try:
            rctx = wrapped(rctx)
        finally:
            db.close()
        return rctx


from . import CommandDigest


class SqlAlchemyCommands(CommandDigest):
    '''
    sqlalchemy operations on models:
    db_name - key from databases dict, provided during init
    '''

    def __init__(self, databases, base_class, initial=None):
        '''
        :*base_class* - base class of models (usualy result of declarative_meta())

        :*databases* - dict[db_name:db_uri]

        :*initial* - function that takes session object and populates 
                     session with models instances
        '''
        self.cfg = databases
        self.base_class = base_class
        self.initial = initial

    def command_sync(self, db_name=None):
        '''
        $ python manage.py sqlalchemy:sync [db_name]

        syncs models with database
        '''
        if db_name is None:
            db_name = ''
        engine = create_engine(self.cfg[db_name], echo=True)
        self.base_class.metadata.create_all(engine)

    def command_drop(self, db_name=None):
        '''
        $ python manage.py sqlalchemy:drop [db_name]

        drops model's tables from database
        '''
        if db_name is None:
            db_name = ''
        engine = create_engine(self.cfg[db_name], echo=True)
        self.base_class.metadata.drop_all(engine, checkfirst=True)

    def command_initial(self, db_name=None):
        '''
        $ python manage.py sqlalchemy:initial [db_name]

        populates models with initial data
        '''
        if db_name is None:
            db_name = ''
        if self.initial:
            engine = create_engine(self.cfg[db_name], echo=True)
            session = orm.sessionmaker(bind=engine)()
            self.initial(session)

    def command_schema(self, model_name=None):
        '''
        $ python manage.py sqlalchemy:schema [model_name]

        shows CREATE sql script for model(s)
        '''
        from sqlalchemy.schema import CreateTable
        if model_name:
            table = self.base_class._decl_class_registry[model_name].__table__
            print str(CreateTable(table))
        else:
            for model in self.base_class._decl_class_registry.values():
                print str(CreateTable(model.__table__))

    def command_reset(self, db_name=None):
        '''
        $ python manage.py sqlalchemy:reset [db_name]
        '''
        self.command_drop(db_name)
        self.command_sync(db_name)
        self.command_initial(db_name)

    def command_shell(self, db_name=None):
        '''
        $ python manage.py sqlalchemy:shell [db_name]

        provides python interactive shell with 'db' as session to database
        '''
        if db_name is None:
            db_name = ''
        engine = create_engine(self.cfg[db_name], echo=True)
        from code import interact
        interact('SqlAlchemy session with db: %s' % (db_name if db_name else 'default',),
                 local={'db': orm.sessionmaker(bind=engine)()})


# COLUMNS

#from sqlalchemy.databases.mysql import MSMediumText as MediumText
from sqlalchemy import String, Integer, Text, Boolean, Date, DateTime
from sqlalchemy import orm, types, create_engine

from ..forms.files import StoredFile, StoredImageFile

class StringList(types.TypeDecorator):

    impl = types.String

    def process_bind_param(self, value, dialect):
        if value is not None:
            return ','.join(value)

    def process_result_value(self, value, dialect):
        if value is not None:
            return filter(None, value.split(','))


class IntegerList(types.TypeDecorator):

    impl = types.String

    def process_bind_param(self, value, dialect):
        if value is not None:
            return ','.join(str(item) for item in value)

    def process_result_value(self, value, dialect):
        if value is not None:
            return [int(item) for item in value.split(',') if item]


def get_html_class(safe_marker, impl_=types.Text):

    class HtmlTextJinja(types.TypeDecorator):
        '''Represants safe to render in template html markup'''

        impl = impl_

        def process_result_value(self, value, dialect):
            if value is not None:
                return safe_marker(value)

        def process_bind_param(self, value, dialect):
            if value is not None:
                return unicode(value)

    return HtmlTextJinja

try:
    from jinja2 import Markup
except ImportError:
    pass
else:
    HtmlTextJinja = get_html_class(Markup)
    HtmlStringJinja = get_html_class(Markup, impl=types.String)
    HtmlMediumTextJinja = get_html_class(Markup, impl=types.MediumText)


class AlchemyFile(types.TypeDecorator):

    impl = types.Binary
    file_class = StoredFile # must be subclass of StoredFile

    def __init__(self, base_path=None, base_url=None):
        assert base_path and base_url
        super(AlchemyFile, self).__init__(255)
        self.base_path = base_path
        self.base_url = base_url

    def process_bind_param(self, value, dialect):
        if isinstance(value, StoredFile):
            return value.filename
        return value

    def process_result_value(self, value, dialect):
        if value:
            return self.file_class(value, base_path=self.base_path,
                                   base_url=self.base_url)
        return value

    def copy(self):
        return self.__class__(base_path=self.base_path, base_url=self.base_url)


class AlchemyImageFile(AlchemyFile):

    file_class = StoredImageFile
