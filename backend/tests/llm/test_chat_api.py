"""POST /api/chat and GET /api/chat/history response shapes."""
from __future__ import annotations

import json


def test_post_chat_shape(client, fake_llm):
    fake_llm.reply = json.dumps({"message": "Bought",
                                 "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 2}],
                                 "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]})
    resp = client.post("/api/chat", json={"message": "buy 2 AAPL and watch PYPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "role", "message", "created_at", "trades", "watchlist_changes"}
    assert body["role"] == "assistant" and body["message"] == "Bought"
    assert set(body["trades"][0]) == {"ticker", "side", "quantity", "status", "price", "error"}
    assert set(body["watchlist_changes"][0]) == {"ticker", "action", "status", "error"}


def test_empty_message_is_400(client, fake_llm):
    for msg in ("", "   "):
        resp = client.post("/api/chat", json={"message": msg})
        assert resp.status_code == 400
        assert "detail" in resp.json()
    assert fake_llm.calls == []


def test_too_long_message_is_400(client, fake_llm):
    assert client.post("/api/chat", json={"message": "x" * 5000}).status_code == 400


def test_malformed_body_is_422(client):
    assert client.post("/api/chat", json={"msg": "hi"}).status_code == 422


def test_llm_failure_is_200_apology(client, fake_llm):
    fake_llm.reply = RuntimeError("down")
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json()["trades"] == []


def test_history(client, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    assert client.get("/api/chat/history").json() == {"messages": []}
    client.post("/api/chat", json={"message": "hello"})
    client.post("/api/chat", json={"message": "buy 1 AAPL"})
    msgs = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert set(msgs[0]) == {"id", "role", "content", "actions", "created_at"}
    assert msgs[0]["content"] == "hello" and msgs[0]["actions"] is None
    assert msgs[3]["content"] == "Mock: buying 1 AAPL."
    assert msgs[3]["actions"]["trades"][0]["status"] == "executed"
