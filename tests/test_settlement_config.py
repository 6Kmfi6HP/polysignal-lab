"""
Input: polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.load_settings
Output: test_default_settlement_config, test_settlement_env_override
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from polysignal_lab.config import Settings, load_settings


def test_default_settlement_config() -> None:
    config = Settings().data.polymarket.settlement

    assert config.chain_enabled is True
    assert config.polygon_rpc_url == ""
    assert config.chain_timeout_sec == 3.0
    assert config.gamma_enabled is True
    assert config.ws_enabled is True
    assert config.prefer_chain is True


def test_settlement_env_override(monkeypatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_LAB__DATA__POLYMARKET__SETTLEMENT__POLYGON_RPC_URL", "https://rpc.example")

    settings = load_settings()

    assert settings.data.polymarket.settlement.polygon_rpc_url == "https://rpc.example"
