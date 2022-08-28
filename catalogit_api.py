import requests
import urllib.parse

from log import get_logger


# setup logging
logger = get_logger()


class CatalogItAPI():

    def __init__(self, account_id, int_base_url):
        self.account_id = account_id
        self.int_base_url = int_base_url
        self.search_string_template = f"{int_base_url}/{{custom_id}}"
        self.search_url_template = f"https://api.catalogit.app/api/public/accounts/{account_id}/search?query={{search_string}}"

    def get_entry(self, custom_id):
        search_string = urllib.parse.quote(
            self.search_string_template.format(custom_id=custom_id),
            safe=""
        )
        url = self.search_url_template.format(search_string=search_string)
        response = requests.get(url).json()
        if response["total"] != 1:
            return None
        else:
            return response["entries"][0]
