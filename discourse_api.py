import requests

from log import get_logger


# setup logging
logger = get_logger()


class DiscourseAPI():

    def __init__(self, base_url, username, key):
        self.base_url = base_url
        self.username = username
        self.key = key

    def api_request(self, path, method_func=requests.get, body={}):
        headers = {
            "Accept": "application/json",
            "Api-Username": self.username,
            "Api-Key": self.key
        }
        kwargs = {
            "headers": headers,
        }
        if method_func == requests.post:
            #headers.pop("Accept")
            headers["Content-Type"] = "multipart/form-data"
            kwargs["data"] = body
        # do request
        url = f"{self.base_url}{path}"
        response = method_func(url, **kwargs)
        return response.json()

    def get_categories(self):
        response = self.api_request("/categories", requests.get)
        return response

    def get_category_by_name(self, category_name):
        all_categories = self.get_categories()
        for c in all_categories["category_list"]["categories"]:
            if c["name"] == category_name:
                return c
        return None

    def create_category(self, category_name, color="66FF66"):
        body = {
            "name": category_name,
            "color": color
        }
        response = self.api_request("/categories", requests.post, body=body)
        return response

    def create_user(self, name, email, username, password):
        body = {
            "name": name,
            "email": email,
            "password": password,
            "username": username
        }
        response = self.api_request("/users", requests.post, body=body)
        return response

    def get_topic(self, custom_id):
        url = f"/t/external_id/{custom_id}"
        response = self.api_request(url, requests.get)
        if response.get("error_type") == "not_found":
            return None
        return response

    def create_topic(self, title, raw, category_id, embed_url, external_id):
        body = {
            "title": title,
            "raw": raw,
            "category": category_id,
            "embed_url": embed_url,
            "external_id": external_id
        }
        response = self.api_request("/posts", requests.post, body=body)
        return response

