import requests
import json

class RateQuoteAPI:
    def __init__(self, config):
        self.config = config
        self.access_token = None

    def get_access_token(self):
        url = f"{self.config['url']}{self.config['oauth_endpoint']}?grant_type=client_credentials"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": self.config['client_id'],
            "client_secret": self.config['client_secret'],
            "grant_type": "client_credentials"
        }
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        self.access_token = response.json()["access_token"]

    def get_rate_quote(self, payload):
        if not self.access_token:
            self.get_access_token()

        url = f"{self.config['url']}{self.config['rate_quote_endpoint']}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        return response.json()

class AuptixRateQuoteAPI:
    def __init__(self, config):
        self.config = config

    def get_rate_quote(self, payload):
        url = f"{self.config['url']}{self.config['rate_quote_endpoint']}"
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        return response.json()
    
class CNUSAExpressAPI:
    def __init__(self, config):
        self.config = config

    def get_rate_quote(self, payload):
        url = self.config['url']
        headers = {
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

