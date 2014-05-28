'''
Data classes representing references to files in model objects. Manager class
for common operations with files. Manager encapsulate knowledge on where and
how to store transient and persistent files.
'''

import os
import base64
import errno
from shutil import copyfileobj
from ...utils import cached_property


class BaseFile(object):

    def __init__(self, root, name, original_name=None, manager=None):
        '''@root depends on environment of application and @name uniquely
        identifies the file.'''
        self.root = root
        self.name = name
        self.manager = manager
        self.original_name = original_name

    @property
    def path(self):
        return os.path.join(self.root, self.name)

    @cached_property
    def size(self):
        try:
            return os.path.getsize(self.path)
        # Return None for non-existing file.
        # There can be OSError or IOError (depending on Python version?), both
        # are derived from EnvironmentError having errno property.
        except EnvironmentError, exc:
            if exc.errno!=errno.ENOENT:
                raise

    @property
    def file_name(self):
        return os.path.split(self.name)[1]

    @property
    def ext(self):
        return os.path.splitext(self.name)[1]

    def __repr__(self):
        return '{}({!r})'.format(type(self).__name__, self.name)


class TransientFile(BaseFile):

    mode = 'transient'

    @property
    def url(self):
        return self.manager.get_transient_url(self)


class PersistentFile(BaseFile):

    mode = 'existing' # XXX rename existing to persistent everywhere

    @property
    def url(self):
        return self.manager.get_persistent_url(self)


class _AttrDict(object):

    def __init__(self, inst):
        self.__inst = inst

    def __getitem__(self, key):
        return getattr(self.__inst, key)

def random_name():
    # altchars - do not use "-" and "_" in file names
    return base64.b64encode(os.urandom(8), altchars="AA").rstrip('=')


class BaseFileManager(object):

    def __init__(self, persistent_root, persistent_url):
        self.persistent_root = persistent_root
        self.persistent_url = persistent_url

    def get_persistent(self, name, cls=PersistentFile):
        assert name and not ('..' in name or name[0] in '~/'), name
        persistent = cls(self.persistent_root, name, original_name=None, manager=self)
        return persistent

    def get_persistent_url(self, file, env=None):
        return self.persistent_url + file.name


class ReadonlyFileManager(BaseFileManager):
    pass


class FileManager(BaseFileManager):

    def __init__(self, transient_root, persistent_root,
                 transient_url, persistent_url):
        self.transient_root = transient_root
        self.persistent_root = persistent_root
        self.transient_url = transient_url
        self.persistent_url = persistent_url

    def delete(self, file_obj):
        # XXX Is this right place again?
        #     BC "delete file if exist and ignore errors" would be used in many
        #     places, I think...
        if os.path.isfile(file_obj.path):
            try:
                os.unlink(file_obj.path)
            except OSError:
                pass

    def _copy_file(self, inp, path, length=None):
        # works for ajax file upload
        # XXX implement/debug for FieldStorage and file
        with open(path, 'wb') as fp:
            if length is None:
                copyfileobj(inp, fp)
            else:
                # copyfileobj does not work on request.input_stream
                # XXX check
                pos, bufsize = 0, 16*1024
                while pos < length:
                    bufsize = min(bufsize, length-pos)
                    data = inp.read(bufsize)
                    fp.write(data)
                    pos += bufsize

    def create_transient(self, input_stream, original_name, length=None):
        '''Create TransientFile and file on FS from given input stream and 
        original file name.'''
        ext = os.path.splitext(original_name)[1]
        transient = self.new_transient(ext)
        if not os.path.isdir(self.transient_root):
            os.makedirs(self.transient_root)

        self._copy_file(input_stream, transient.path, length=length)
        return transient

    def new_transient(self, ext=''):
        '''Creates empty TransientFile with random name and given extension.
        File on FS is not created'''
        name = os.urandom(8).encode('hex') + ext
        return TransientFile(self.transient_root, name, self)

    def get_transient(self, name, original_name=None):
        '''Restores TransientFile object with given name.
        Should be used when form is submitted with file name and no file'''
        # security checks: basically no folders are allowed
        assert not ('/' in name or '\\' in name or name[0] in '.~')
        transient = TransientFile(self.transient_root, name, original_name, self)
        if not os.path.isfile(transient.path):
            raise OSError(errno.ENOENT, 'Transient file has been lost',
                          transient.path)
        return transient

    def store(self, transient_file, persistent_file):
        '''Makes PersistentFile from TransientFile'''
        #for i in xrange(5):
        #    persistent_file = PersistentFile(self.persistent_root,
        #                                     persistent_name, self)
        #    if not os.path.exists(persistent_file.path):
        #        break
        #else:
        #    raise Exception('Unable to find free file name')
        dirname = os.path.dirname(persistent_file.path)
        if not os.path.isdir(dirname):
            os.makedirs(dirname)
        os.rename(transient_file.path, persistent_file.path)
        return persistent_file

    def get_transient_url(self, file, env=None):
        return self.transient_url + file.name

    def new_file_name(self, name_template, inst, ext, old_name):
        assert '{random}' in name_template, \
               'Non-random name templates are not supported yet'
        for i in xrange(5):
            name = name_template.format(item=inst, random=random_name())
            name = name + ext
            # XXX Must differ from old value[s].
            if name != old_name or not '{random}' in name_template:
                return name
        raise Exception('Unable to find new file name')


