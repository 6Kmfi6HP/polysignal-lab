from py_clob_client_v2 import ClobClient


def make_client():
    return ClobClient(host="https://clob.polymarket.com", chain_id=137)
