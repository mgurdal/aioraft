import requests


if __name__ == "__main__":
    resp = requests.post("http://localhost:8000", json={"some": "data"})
    print(resp)
