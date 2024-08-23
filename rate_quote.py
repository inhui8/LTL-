import requests
import json
from datetime import datetime, timedelta

class RateQuoteAPI:
    def __init__(self, config):
        self.config = config
        self.access_token = None
        self.token_expiry = None

    def get_access_token(self):
        if self.access_token is None or datetime.now() >= self.token_expiry:
            url = f"{self.config['url']}{self.config['oauth_endpoint']}?grant_type=client_credentials"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "client_id": self.config['client_id'],
                "client_secret": self.config['client_secret'],
                "grant_type": "client_credentials"
            }
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.token_expiry = datetime.now() + timedelta(seconds=int(token_data["expires_in"]))
            print(f"Received and cached access token: {self.access_token}")

    def get_rate_quote(self, payload):
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