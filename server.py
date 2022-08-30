#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import json
import os
import random
import re
import ssl
import string

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
INT_BASE_URL = os.environ["INT_BASE_URL"]
SEARCH_STRING = f"{INT_BASE_URL}/{{custom_id}}"
UUID_PATTERN = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}$')
# remove trailing slashes
DISCOURSE_API_URL = DISCOURSE_API_URL if not DISCOURSE_API_URL.endswith("/") else DISCOURSE_API_URL[:-1]
INT_BASE_URL = INT_BASE_URL if not INT_BASE_URL.endswith("/") else INT_BASE_URL[:-1]
TOPIC_TEMPLATE="""
<h2>{title}</h2>
<a target="_blank" href="{cit_entry_url}">
	<img src="{image_url}" alt="{title}">
</a><br />
<a target="_blank" href="{cit_entry_url}">Click here or on the image to view this entry in our collection.</a>
{description}
<h6>Created by <a target="_blank" href="https://github.com/linuxdojo/catalogbot">CatalogBot</a></h6>
"""

# ThreadingMixin to make the HTTPServer multithreaded
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass


# HTTPRequestHandler class
class HTTPServer_RequestHandler(BaseHTTPRequestHandler):

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

    def do_GET(self):
        tracking_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        logger.info(f"[{tracking_id}] New GET request from '{self.client_address}' with request headers '{self.headers}'")
        # extract custom_id
        custom_id = self.path[1:] if len(self.path) > 1 else None
        try:
            if not UUID_PATTERN.match(custom_id):
                logger.info(f"[{tracking_id}] Got malformed custom_id: {custom_id}'")
                return self.send_error_response(message="malformed id")
        except Exception as e:
            logger.info(f"[{tracking_id}] Got exception while handling request: {e}'")
            return self.send_error_response(message="bad request")
        # get topic if exists
        topic = self.d_api.get_topic(custom_id)
        if topic:
            topic_id = topic["id"]
        else:
            # generate new topic attributes 
            logger.info(f"[{tracking_id}] Topic not found for custom_id '{custom_id}', creating new topic...")
            cit_entry = self.cit_api.get_entry_by_custom_id(custom_id)
            if not cit_entry:
                logger.error(f"[{tracking_id}] Failed during lookup of catalogit entry for custom_id: {custom_id}")
                return self.send_error_response(message="unexpected cit-entry error, please try again later", status=500)
            cit_name = cit_entry['properties'].get("hasName", {}).get("value_text")
            if not cit_name:
                logger.error(f"[{tracking_id}] Refusing to create topic for unnamed item with entry_id: {cit_entry['id']}")
                return self.send_error_response(message="Sorry, this item is not yet named and thus can't be linked to the forum", status=400)
            title = f"Discussion about collection item: {cit_name}"
            category_id = self.d_api.get_category_by_name(DISCOURSE_CATEGORY)["id"]
            image_url = cit_entry.get("media", [{}])[0].get("derivatives", {}).get("public", {}).get("path", "")
            backlink_url = f"https://hub.catalogit.app/{CIT_ACCOUNT_ID}/folder/entry/{cit_entry['id']}"
            cit_description = cit_entry['properties'].get("hasDescription", {}).get("value_text")
            if cit_description:
                description = "<pre>Description:<br /><br />{d}<br /></pre>".format(d=cit_description.replace("\n", "<br />"))
            else:
                description = ""
            external_id = custom_id
            raw = TOPIC_TEMPLATE.format(
                title=title,
                cit_entry_url=backlink_url,
                image_url=image_url,
                description=description
            )
            # create new topic
            logger.info(f"[{tracking_id}] New topic fields are: title: '{title}', category_id: '{category_id}', image_url: '{image_url}', backlink_url: {backlink_url}, external_id: {external_id}")
            result = self.d_api.create_topic(title, raw, category_id, external_id)
            try:
                topic_id = result["topic_id"]
            except KeyError:
                logger.error(f"[{tracking_id}] Failed to fetch topic_id after creating topic. Topic create response was: {result}")
                if 'External has already been taken' in result.get("errors", []):
                    msg = f"duplicate UUID detected, please update your CatalogIt weblink with a unique UUID"
                    status = 400
                else:
                    msg = "unexpected topic-fetch error, please try again later"
                    status = 500
                return self.send_error_response(message=msg, status=status)
        # redirect to topic
        topic_url = f"{DISCOURSE_API_URL}/t/{topic_id}"
        self.send_response(301)
        self.send_header('Location', topic_url)
        self.end_headers()


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

