import threading
import time
import urllib.parse

import requests

from log import get_logger


# setup logging
logger = get_logger()


# CatalogIt's public search stopped matching on the `weblink_link` (href)
# sub-field, so an entry can no longer be found by searching for the weblink
# URL itself. Instead we pull the account's entries with a match-all query and
# build the weblink URL -> entry mapping locally.
#
# Matching all entries rather than searching for the weblink label keeps this
# independent of the label text, which is curator-editable and would otherwise
# silently drop entries out of the index if reworded.
SEARCH_QUERY = "*"
# how long an index is served before it is rebuilt
DEFAULT_CACHE_TTL = 300
# floor between fetches, so an unrecognised custom_id can't stampede the
# (multi-megabyte) search endpoint, and a failing API isn't hammered
DEFAULT_MIN_FETCH_INTERVAL = 60
REQUEST_TIMEOUT = 120


def normalise_url(url):
    """strip scheme and trailing slash so http/https variants compare equal"""
    url = url.strip().lower()
    for scheme in ("https://", "http://"):
        if url.startswith(scheme):
            url = url[len(scheme):]
            break
    return url.rstrip("/")


class CatalogItAPI():

    # shared across instances: server.py builds a new API object per request,
    # so per-instance state would rebuild the index on every click
    _lock = threading.Lock()
    _session = requests.Session()
    _index = None           # custom_id -> entry
    _index_built = None     # monotonic time of the last successful build
    _last_fetch = None      # monotonic time of the last fetch attempt

    def __init__(self, account_id, int_base_url, cache_ttl=DEFAULT_CACHE_TTL,
                 min_fetch_interval=DEFAULT_MIN_FETCH_INTERVAL):
        self.account_id = account_id
        self.int_base_url = int_base_url
        self.cache_ttl = cache_ttl
        self.min_fetch_interval = min_fetch_interval
        self.link_prefix = normalise_url(int_base_url) + "/"
        self.search_url = (
            f"https://api.catalogit.app/api/public/accounts/{account_id}"
            f"/search?query={urllib.parse.quote(SEARCH_QUERY, safe='')}"
        )

    def _iter_weblinks(self, entry):
        """yield weblink URLs for an entry; value_weblink is a dict, or a list
        when the entry carries more than one weblink"""
        value = entry.get("properties", {}).get("hasWebLink", {}).get("value_weblink")
        if isinstance(value, dict):
            value = [value]
        elif not isinstance(value, list):
            return
        for weblink in value:
            if isinstance(weblink, dict) and weblink.get("weblink_link"):
                yield weblink["weblink_link"]

    def _custom_id_from_weblink(self, url):
        """return the custom_id if this is one of our weblinks, else None"""
        normalised = normalise_url(url)
        if not normalised.startswith(self.link_prefix):
            return None
        custom_id = normalised[len(self.link_prefix):]
        # our weblinks are a bare id, anything deeper isn't one of ours
        if not custom_id or "/" in custom_id:
            return None
        return custom_id

    def _fetch_index(self):
        """map custom_id -> entry for every entry carrying one of our weblinks"""
        response = self._session.get(self.search_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        entries = response.json().get("entries", [])
        index = {}
        for entry in entries:
            for weblink in self._iter_weblinks(entry):
                custom_id = self._custom_id_from_weblink(weblink)
                if not custom_id:
                    continue
                existing = index.get(custom_id)
                if existing and existing["id"] != entry["id"]:
                    logger.warning(
                        f"custom_id {custom_id} is on more than one entry "
                        f"({existing['id']} and {entry['id']}), keeping the first"
                    )
                    continue
                index[custom_id] = entry
        logger.info(f"indexed {len(index)} weblinks from {len(entries)} CatalogIt entries")
        return index

    def _get_index(self, force=False):
        cls = type(self)
        with cls._lock:
            now = time.monotonic()
            if cls._index is not None and not force:
                if (now - cls._index_built) < self.cache_ttl:
                    return cls._index
            if cls._last_fetch is not None:
                if (now - cls._last_fetch) < self.min_fetch_interval:
                    # too soon to fetch again; serve what we have
                    return cls._index if cls._index is not None else {}
            cls._last_fetch = now
            try:
                cls._index = self._fetch_index()
                cls._index_built = now
            except Exception as e:
                # keep serving a stale index rather than failing every request
                logger.error(f"failed to refresh CatalogIt entry index: {e}")
                if cls._index is None:
                    return {}
            return cls._index

    def get_entry_by_custom_id(self, custom_id):
        entry = self._get_index().get(custom_id)
        if entry is None:
            # may be a weblink added since the index was last built
            entry = self._get_index(force=True).get(custom_id)
        if entry is None:
            logger.warning(f"no CatalogIt entry has a weblink for custom_id: {custom_id}")
        return entry
