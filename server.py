#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import collections
import hashlib
import hmac
import html
import json
import os
import random
import re
import ssl
import string
import threading
import time
import urllib.parse

from dotenv import load_dotenv
import requests

import catalogit_api
import discourse_api
from log import get_logger


# setup logging
logger = get_logger()

try:
    load_dotenv(stream=open(".environ"))
except FileNotFoundError:
    logger.warning("Environment file '.environ' not found, using default environment variables.")


# read env vars
BIND_HOST = os.environ["INT_BIND_HOST"]
BIND_PORT = int(os.environ["INT_BIND_PORT"])
CIT_ACCOUNT_ID = os.environ["CIT_ACCOUNT_ID"]
CIT_SEARCH_URL = f"https://api.catalogit.app/api/public/accounts/{CIT_ACCOUNT_ID}/search?query={{SEARCH_STRING}}"
DISCOURSE_API_KEY = os.environ["DISCOURSE_API_KEY"]
DISCOURSE_API_URL = os.environ["DISCOURSE_API_URL"]
DISCOURSE_API_USERNAME = os.environ["DISCOURSE_API_USERNAME"]
DISCOURSE_CATEGORY = os.environ["DISCOURSE_CATEGORY"]
DISCOURSE_TOPIC_FOOTER = os.environ.get("DISCOURSE_TOPIC_FOOTER")
INT_BASE_URL = os.environ["INT_BASE_URL"]
SEARCH_STRING = f"{INT_BASE_URL}/{{custom_id}}"
UUID_PATTERN = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}$')
# remove trailing slashes
DISCOURSE_API_URL = DISCOURSE_API_URL if not DISCOURSE_API_URL.endswith("/") else DISCOURSE_API_URL[:-1]
INT_BASE_URL = INT_BASE_URL if not INT_BASE_URL.endswith("/") else INT_BASE_URL[:-1]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_template(name):
    """templates use $placeholders so that CSS braces need no escaping"""
    with open(os.path.join(BASE_DIR, "templates", name), encoding="utf8") as fh:
        return string.Template(fh.read())


def load_static(name):
    with open(os.path.join(BASE_DIR, "static", name), "rb") as fh:
        return fh.read()


TOPIC_TEMPLATE = load_template("topic.html")
INTERSTITIAL_TEMPLATE = load_template("interstitial.html")
# served from this host so the integration doesn't depend on acms.org.au
STATIC_FILES = {
    "/static/acms-logo.jpg": ("image/jpeg", load_static("acms-logo.jpg")),
}
LOGO_URL = "/static/acms-logo.jpg"
# a topic is only created by POSTing the form on the interstitial page, and the
# form carries a signed token, so a crawler that merely follows the weblink (or
# blindly POSTs to it) creates nothing
GATE_SECRET = os.urandom(32)
GATE_TOKEN_TTL = 1800
# backstop: whatever gets past the gate, it cannot create more topics than this
# in a rolling hour. 43 unwanted topics accumulated over three days in Aug 2026
# before anyone noticed; a cap makes the next surprise bounded and loud.
MAX_NEW_TOPICS_PER_HOUR = int(os.environ.get("INT_MAX_NEW_TOPICS_PER_HOUR", 20))
# "googleother" is listed separately because, unlike googlebot, its user-agent
# contains no "bot" substring and so matched nothing here
CRAWLER_USER_AGENTS = ["googlebot", "googleother", "bingbot", "yahoo", "AhrefsBot", "Baiduspider", "Ezooms", "MJ12bot", "YandexBot", "bot", "agent", "spider", "crawler", "extractor"]
# nothing here is meant to be crawled: every path is a redirect into CatalogIt
# or the forum. GoogleOther honours this, and it created 24 of the 43 unwanted
# topics on 10-12 Aug 2026 because its user-agent matches nothing above.
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"

# ThreadingMixin to make the HTTPServer multithreaded
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass


# HTTPRequestHandler class
class HTTPServer_RequestHandler(BaseHTTPRequestHandler):

    # shared across the per-request handler instances
    _cap_lock = threading.Lock()
    _created_at = collections.deque()

    def __init__(self, *args, **kwargs):
        self.cit_api = catalogit_api.CatalogItAPI(CIT_ACCOUNT_ID, INT_BASE_URL)
        self.d_api = discourse_api.DiscourseAPI(
            base_url=DISCOURSE_API_URL,
            username=DISCOURSE_API_USERNAME,
            key=DISCOURSE_API_KEY
        )
        super().__init__(*args, **kwargs)
 
    def send_error_response(self, message="bad request", status=400):
        self.send_response(status)
        self.send_header('Content-type','application/json')
        self.end_headers()
        data = {"message": message}
        message = json.dumps(data)
        self.wfile.write(bytes(message, "utf8"))

    def send_bytes(self, body, content_type, status=200, extra_headers=()):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for header, value in extra_headers:
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(body)

    def send_robots_txt(self):
        self.send_bytes(bytes(ROBOTS_TXT, "utf8"), 'text/plain; charset=utf-8')

    def redirect_to_topic(self, topic_id, status):
        self.send_response(status)
        self.send_header('Location', f"{DISCOURSE_API_URL}/t/{topic_id}")
        self.end_headers()

    def make_token(self, custom_id):
        expires = int(time.time()) + GATE_TOKEN_TTL
        digest = hmac.new(GATE_SECRET, f"{custom_id}:{expires}".encode("utf8"), hashlib.sha256).hexdigest()
        return f"{expires}.{digest}"

    def valid_token(self, custom_id, token):
        try:
            expires, digest = token.split(".", 1)
            expires = int(expires)
        except (AttributeError, ValueError):
            return False
        if expires < time.time():
            return False
        expected = hmac.new(GATE_SECRET, f"{custom_id}:{expires}".encode("utf8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, digest)

    def creation_allowed(self, tracking_id):
        """rolling one hour cap on new topics. Attempts are counted rather than
        successes, so a burst of failing creations trips it too."""
        cls = type(self)
        now = time.time()
        with cls._cap_lock:
            while cls._created_at and cls._created_at[0] < now - 3600:
                cls._created_at.popleft()
            if len(cls._created_at) >= MAX_NEW_TOPICS_PER_HOUR:
                logger.error(f"[{tracking_id}] TOPIC CREATION CAP REACHED: {len(cls._created_at)} in the last hour, limit is {MAX_NEW_TOPICS_PER_HOUR}. Refusing to create any more until it drains.")
                return False
            cls._created_at.append(now)
            return True

    def is_crawler(self, tracking_id):
        for k, v in self.headers.items():
            if k.lower() == "user-agent":
                for a in CRAWLER_USER_AGENTS:
                    if a.lower() in v.lower():
                        logger.info(f"[{tracking_id}] blocking crawler, detected via request header: {k}: {v}")
                        self.send_error_response(message="crawler blocked", status=403)
                        return True
        return False

    def get_custom_id(self, tracking_id):
        """returns the custom_id, or None once an error response has been sent"""
        path = self.path.split("?")[0]
        custom_id = path[1:] if len(path) > 1 else None
        try:
            if not UUID_PATTERN.match(custom_id):
                logger.info(f"[{tracking_id}] Got malformed custom_id: {custom_id}'")
                self.send_error_response(message="malformed id")
                return None
        except Exception as e:
            logger.info(f"[{tracking_id}] Got exception while handling request: {e}'")
            self.send_error_response(message="bad request")
            return None
        return custom_id

    def get_entry_fields(self, custom_id, tracking_id):
        """look up the CatalogIt entry and derive what a topic needs.
        returns None once an error response has been sent"""
        cit_entry = self.cit_api.get_entry_by_custom_id(custom_id)
        if not cit_entry:
            logger.error(f"[{tracking_id}] Failed during lookup of catalogit entry for custom_id: {custom_id}")
            return self.send_error_response(message="unexpected cit-entry error, please try again later", status=500)
        cit_name = cit_entry['properties'].get("hasName", {}).get("value_text")
        if not cit_name:
            logger.error(f"[{tracking_id}] Refusing to create topic for unnamed item with entry_id: {cit_entry['id']}")
            return self.send_error_response(message="Sorry, this item is not yet named and thus can't be linked to the forum", status=400)
        # an entry can carry a media key holding an empty list
        media = cit_entry.get("media") or [{}]
        image_url = media[0].get("derivatives", {}).get("public", {}).get("path", "")
        if not image_url:
            logger.error(f"[{tracking_id}] Refusing to create topic for item missing image with entry_id: {cit_entry['id']}")
            return self.send_error_response(message="Sorry, this item has no images yet and thus can't be linked to the forum", status=400)
        cit_description = cit_entry['properties'].get("hasDescription", {}).get("value_text")
        if cit_description:
            description = "<p>Description:<br /><br />{d}<br /></p>".format(d=cit_description.replace("\n", "<br />"))
        else:
            description = ""
        return {
            "name": cit_name,
            "image_url": image_url,
            "cit_entry_url": f"https://hub.catalogit.app/{CIT_ACCOUNT_ID}/folder/entry/{cit_entry['id']}",
            "description": description,
        }

    def do_GET(self):
        tracking_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        logger.info(f"[{tracking_id}] New GET request from '{self.client_address}' with request headers '{self.headers}'")
        # serve robots.txt ahead of the crawler block below, otherwise the
        # crawlers we want to turn away can never read the rules
        if self.path.split("?")[0] == "/robots.txt":
            logger.info(f"[{tracking_id}] serving robots.txt")
            return self.send_robots_txt()
        # serve the logo from here rather than hotlinking acms.org.au
        path = self.path.split("?")[0]
        if path in STATIC_FILES:
            content_type, body = STATIC_FILES[path]
            return self.send_bytes(body, content_type,
                                   extra_headers=[('Cache-Control', 'public, max-age=86400')])
        if self.is_crawler(tracking_id):
            return
        custom_id = self.get_custom_id(tracking_id)
        if not custom_id:
            return
        # existing topic: straight through to the forum
        topic = self.d_api.get_topic(custom_id)
        if topic:
            logger.info(f"[{tracking_id}] Topic found for custom_id '{custom_id}', redirecting user now...")
            if self.d_api.islisted_topic(custom_id) == False:
                logger.info(f"[{tracking_id}] Topic was unlisted, re-listing.")
                self.d_api.list_topic(custom_id)
            return self.redirect_to_topic(topic["id"], 301)
        # no topic yet: offer to start one instead of starting it here, so that
        # anything which merely follows the link creates nothing
        logger.info(f"[{tracking_id}] Topic not found for custom_id '{custom_id}', serving creation gate...")
        fields = self.get_entry_fields(custom_id, tracking_id)
        if not fields:
            return
        page = INTERSTITIAL_TEMPLATE.safe_substitute(
            title=html.escape(fields["name"]),
            image_url=html.escape(fields["image_url"], quote=True),
            cit_entry_url=html.escape(fields["cit_entry_url"], quote=True),
            custom_id=custom_id,
            token=self.make_token(custom_id),
            logo_url=LOGO_URL,
        )
        self.send_bytes(bytes(page, "utf8"), 'text/html; charset=utf-8',
                        extra_headers=[('X-Robots-Tag', 'noindex, nofollow')])

    def do_POST(self):
        tracking_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        logger.info(f"[{tracking_id}] New POST request from '{self.client_address}' with request headers '{self.headers}'")
        if self.is_crawler(tracking_id):
            return
        custom_id = self.get_custom_id(tracking_id)
        if not custom_id:
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            logger.info(f"[{tracking_id}] Rejecting POST with Content-Length: {length}")
            return self.send_error_response(message="bad request")
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf8", "replace"))
        if not self.valid_token(custom_id, (form.get("token") or [""])[0]):
            logger.info(f"[{tracking_id}] Rejecting POST with missing/expired token for custom_id '{custom_id}'")
            return self.send_error_response(message="this page has expired, please reload it and try again")
        # somebody may have started the topic between page load and submit
        topic = self.d_api.get_topic(custom_id)
        if topic:
            logger.info(f"[{tracking_id}] Topic already exists for custom_id '{custom_id}', redirecting user now...")
            return self.redirect_to_topic(topic["id"], 303)
        if not self.creation_allowed(tracking_id):
            return self.send_error_response(message="too many new discussions have been started recently, please try again shortly", status=503)
        fields = self.get_entry_fields(custom_id, tracking_id)
        if not fields:
            return
        category = self.d_api.get_category_by_name(DISCOURSE_CATEGORY)
        if not category:
            logger.error(f"[{tracking_id}] Discourse category '{DISCOURSE_CATEGORY}' not found")
            return self.send_error_response(message="forum category missing, please try again later", status=500)
        title = f"CatChat: {fields['name']}"
        raw = TOPIC_TEMPLATE.safe_substitute(
            title=title,
            cit_entry_url=fields["cit_entry_url"],
            image_url=fields["image_url"],
            description=fields["description"],
            footer=DISCOURSE_TOPIC_FOOTER or "",
        )
        logger.info(f"[{tracking_id}] New topic fields are: title: '{title}', category_id: '{category['id']}', image_url: '{fields['image_url']}', backlink_url: {fields['cit_entry_url']}, external_id: {custom_id}")
        result = self.d_api.create_topic(title, raw, category["id"], custom_id)
        try:
            topic_id = result["topic_id"]
        except KeyError:
            logger.error(f"[{tracking_id}] Failed to fetch topic_id after creating topic. Topic create response was: {result}")
            if any('External has already been taken' in e for e in result.get("errors", [])):
                msg = f"duplicate UUID detected, please update your CatalogIt weblink with a unique UUID"
                status = 400
            else:
                msg = "unexpected topic-fetch error, please try again later"
                status = 500
            return self.send_error_response(message=msg, status=status)
        self.redirect_to_topic(topic_id, 303)


def run():
    server_address = (BIND_HOST, BIND_PORT)
    httpd = ThreadingHTTPServer(server_address, HTTPServer_RequestHandler)
    if INT_BASE_URL.startswith("https://"):
        httpd.socket = ssl.wrap_socket(
            httpd.socket,
            server_side=True,
            certfile='localhost.pem',
            ssl_version=ssl.PROTOCOL_TLSv1_2
        )
    logger.info('Started CatalogBot Server, waiting for connections...')
    httpd.serve_forever()
 

def create_category(dapi, category_name):
    """idempotent create category function"""
    response = None
    if not dapi.get_category_by_name(category_name):
        response = dapi.create_category(category_name)
    return response


if __name__ == "__main__": 
    dapi = discourse_api.DiscourseAPI(base_url=DISCOURSE_API_URL, username=DISCOURSE_API_USERNAME, key=DISCOURSE_API_KEY)
    # create collection discussion category if it doesn't already exist
    if create_category(dapi, DISCOURSE_CATEGORY):
        logger.info(f"Created Discourse Category: {DISCOURSE_CATEGORY}")
    else:
        logger.info(f"Discourse Category '{DISCOURSE_CATEGORY}' exists.")
    # start the link mapping server
    run()

