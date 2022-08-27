#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import json
import os
import ssl
import urllib.parse

from dotenv import load_dotenv
import requests


load_dotenv(stream=open(".environ"))

CIT_ACCOUNT_ID = os.environ["CIT_ACCOUNT_ID"]
INT_FQDN = os.environ["INT_FQDN"]
BIND_HOST = os.environ["INT_BIND_HOST"]
BIND_PORT = int(os.environ["INT_BIND_PORT"])
CIT_SEARCH_URL = f"https://api.catalogit.app/api/public/accounts/{CIT_ACCOUNT_ID}/search?query={{SEARCH_STRING}}"
SEARCH_STRING = f"{INT_FQDN}/{{custom_id}}"


# Add ThreadingMixin to make the HTTPServer multithreaded
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass


# HTTPRequestHandler class
class HTTPServer_RequestHandler(BaseHTTPRequestHandler):
 
    # GET
    def do_GET(self):

        custom_id = self.path[1:] if len(self.path) > 1 else None
        entry = get_cit_entry(custom_id)
        
        if entry:
            # send redirect
            self.send_response(301)
            self.send_header('Location', url)
            self.end_headers()
        else:
            # Send response status code
            self.send_response(400)
            self.send_header('Content-type','text/html')
            self.end_headers()
            data = {"message": "bad_request"}
            message = json.dumps(data)
            # Write content as utf-8 data
            self.wfile.write(bytes(message, "utf8"))


def get_cit_entry(custom_id):
    search_string = urllib.parse.quote(SEARCH_STRING.format(custom_id=custom_id), safe="")
    url = CIT_SEARCH_URL.format(SEARCH_STRING=search_string)
    response = requests.get(url).json()
    if response["total"] != 1:
        return None
    else:
        return response


def run():
    print('Starting CatalogIt-Discourse Integration Server...')
    server_address = (BIND_HOST, BIND_PORT)
    httpd = ThreadingHTTPServer(server_address, HTTPServer_RequestHandler)
    httpd.socket = ssl.wrap_socket(
        httpd.socket,
        server_side=True,
        certfile='localhost.pem',
        ssl_version=ssl.PROTOCOL_TLSv1_2
    )
    httpd.serve_forever()
 

if __name__ == "__main__": 
    run()

