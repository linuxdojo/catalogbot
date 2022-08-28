import requests


def api_request(base_url, path, api_username, api_key, method_func=requests.get, body={}):
    headers = {
        "Accept": "application/json",
        "Api-Username": api_username,
        "Api-Key": api_key
    }
    if method_func == requests.post:
        headers["Content-Type"] = "multipart/form-data"
    # do request
    url = f"{base_url}/{path}"
    response = method_func(url, headers=headers)
    return response.json()
