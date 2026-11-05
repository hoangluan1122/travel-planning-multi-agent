"""Talk to TravelMate as another agent would, over A2A 1.0 (JSON-RPC).

    uv run python scripts/a2a_client.py "Lên lịch đi Huế" "từ 20/11 đến 21/11, 2 người, 5 triệu"

Reads the Agent Card, then sends each argument as one message in the same context, continuing
the task while it is TASK_STATE_INPUT_REQUIRED. The bearer token comes from TRAVELMATE_API_TOKEN
in .env (never printed). Use --url for a server other than http://127.0.0.1:8000.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("messages", nargs="+")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    from app.main import Settings

    token = Settings().travelmate_api_token
    headers = {"A2A-Version": "1.0", **({"Authorization": f"Bearer {token}"} if token else {})}
    with httpx.Client(timeout=300) as client:
        card = client.get(f"{args.url}/.well-known/agent-card.json").raise_for_status().json()
        endpoint = card["supportedInterfaces"][0]["url"]
        print(f"Agent: {card['name']} v{card['version']} — skills: {', '.join(s['id'] for s in card['skills'])}")
        context_id = task_id = None
        for number, text in enumerate(args.messages, 1):
            message = {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": str(uuid.uuid4())}
            if context_id:
                message["contextId"] = context_id
            if task_id:
                message["taskId"] = task_id
            body = {"jsonrpc": "2.0", "id": number, "method": "SendMessage", "params": {"message": message}}
            reply = client.post(endpoint, json=body, headers=headers).raise_for_status().json()
            if "error" in reply:
                print(f"\n> {text}\nERROR {reply['error']}")
                continue
            task = reply["result"]["task"]
            status = task["status"]
            meta = status["message"].get("metadata", {})
            print(f"\n> {text}\n[{status['state']}] {meta.get('specialist')}: {status['message']['parts'][0]['text']}")
            for artifact in task.get("artifacts", [])[-1:] if status["state"] == "TASK_STATE_COMPLETED" else []:
                print(f"  artifact {artifact['name']}: {json.dumps(artifact['parts'][0]['data'], ensure_ascii=False)[:300]}")
            context_id = task["contextId"]
            task_id = task["id"] if status["state"] == "TASK_STATE_INPUT_REQUIRED" else None


if __name__ == "__main__":
    main()
