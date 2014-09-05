import os.path
from urlparse import urlparse

from konfig import Config
from shavar.exceptions import MissingListDataError
from shavar.sources import DirectorySource, FileSource


def configure_lists(config_file, registry):
    config = Config(config_file)

    lists_to_serve = config.mget('shavar', 'lists_served')
    if not lists_to_serve:
        raise ValueError("lists_served appears to be empty or missing "
                         "in the config \"%s\"!" % config.filename)

    registry['shavar.serving'] = {}

    for lname in lists_to_serve:
        if config.has_section(lname):
            settings = config.get_map(lname)
        else:
            defaults = config.get_map('shavar')
            settings = {'type': 'shavar',
                        'source': os.path.join(defaults.get('lists_root',
                                                            ''), lname)}

        type_ = settings.get('type', '')
        if type_ == 'digest256':
            list_ = Digest256(lname, settings['source'], settings)
        elif type_ == 'shavar':
            list_ = Shavar(lname, settings['source'], settings)
        else:
            raise ValueError('Unknown list type for "%s": "%s"' % (lname,
                                                                   type_))

        registry['shavar.serving'][lname] = list_


def get_list(request, list_name):
    if list_name not in request.registry['shavar.serving']:
        raise MissingListDataError('Not serving requested list "%s"', list_name)
    return request.registry['shavar.serving'][list_name]


def lookup_prefixes(request, prefixes):
    """
    prefixes is an iterable of hash prefixes to look up

    Returns a dict of the format:

    { list-name0: { chunk_num0: [ full-hash, ... ],
                    chunk_num1: [ full-hash, ... ],
                    ... },
      list-name1: { chunk_num0: [ full-hash, ... ],
                    ... },
      ... }
    }

    Prefixes that aren't found are ignored
    """

    found = {}

    for list_name, sblist in request.registry['shavar.serving'].iteritems():
        for prefix in prefixes:
            list_o_chunks = sblist.find_prefix(prefix)
            if not list_o_chunks:
                continue
            if list_name not in found:
                found[list_name] = {}
            for chunk in list_o_chunks:
                if chunk.number not in found[list_name]:
                    found[list_name][chunk.number] = []
                found[list_name][chunk.number].extend(chunk.get_hashes(prefix))
    return found


class SafeBrowsingList(object):
    """
    Manages comparisons and data freshness
    """

    # Size of prefixes in bytes
    hash_size = 32
    prefix_size = 4
    type = 'invalid'

    def __init__(self, list_name, source_url, settings):
        self.name = list_name
        self.source_url = source_url
        self.url = urlparse(source_url)
        self.settings = settings
        if (self.url.scheme == 'file' or
                not (self.url.scheme and self.url.netloc)):
            self._source = FileSource(self.source_url, self)
        else:
            raise Exception('Only filesystem access supported at this time')
        self._source.load()

    def refresh(self):
        self._source.refresh()

    def delta(self, adds, subs):
        """
        Calculates the delta necessary for a given client to catch up to the
        server's idea of "current"

        This current iteration is very simplistic algorithm
        """
        current_adds, current_subs = self._source.list_chunks()

        # FIXME Should we call issuperset() first to be sure we're not getting
        # weird stuff from the request?
        a_delta = current_adds.difference(adds)
        s_delta = current_subs.difference(subs)
        return sorted(a_delta), sorted(s_delta)

    def fetch(self, add_chunks=[], sub_chunks=[]):
        details = self._source.fetch(add_chunks, sub_chunks)
        details['type'] = self.type
        return details

    def fetch_adds(self, add_chunks):
        return self.fetch(add_chunks, [])['adds']

    def fetch_subs(self, sub_chunks):
        return self.fetch([], sub_chunks)['subs']

    def find_prefix(self, prefix):
        # Don't bother looking for prefixes that aren't the right size
        if len(prefix) != self.prefix_size:
            return ()
        return self._source.find_prefix(prefix)


class Digest256(SafeBrowsingList):

    prefix_size = 32
    type = 'digest256'


class Shavar(SafeBrowsingList):

    prefix_size = 4
    type = 'shavar'
