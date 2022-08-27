#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import json
import ssl
import urllib.parse

from dotenv import dotenv_values
import requests


config = dotenv_values("env")

INT_FQDN = config["INT_FQDN"]
CIT_ACCOUNT_ID = config["CIT_ACCOUNT_ID"]
SEARCH_STRING = "{INT_FQDN}/{{acms_id}}".format(INT_FQDN=INT_FQDN)
CIT_API_URL = f"https://api.catalogit.app/api/public/accounts/{CIT_ACCOUNT_ID}/search?query={{SEARCH_STRING}}"

# Add ThreadingMixin to make the HTTPServer multithreaded
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass


# HTTPRequestHandler class
class HTTPServer_RequestHandler(BaseHTTPRequestHandler):
 
    # GET
    def do_GET(self):

        acms_id = self.path[1:] if len(self.path) > 1 else None
        entry = get_cit_entry(acms_id)
        
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


def get_cit_entry(acms_id):
    search_string = urllib.parse.quote(SEARCH_STRING.format(acms_id=acms_id), safe="")
    url = CIT_API_URL.format(SEARCH_STRING=search_string)
    response = requests.get(url).json()
    if response["total"] != 1:
        return None
    else:
        return response


def run():
    print('Starting ACMS CatalogIt-Discourse Integration Server...')
    server_address = (config["INT_HOST"], int(config["INT_PORT"]))
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

