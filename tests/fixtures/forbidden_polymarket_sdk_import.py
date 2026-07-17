"""
Input: py_clob_client_v2, py_clob_client_v2.ClobClient
Output: make_client
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from py_clob_client_v2 import ClobClient


def make_client():
    return ClobClient(host="https://clob.polymarket.com", chain_id=137)
