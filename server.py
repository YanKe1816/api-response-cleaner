#!/usr/bin/env python3
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "api-response-cleaner"
APP_VERSION = "0.1.0"


def _clean(value):
    if value is None:
        return None, True

    if isinstance(value, str):
        if value == "":
            return None, True
        return value, False

    if isinstance(value, list):
        cleaned_items = []
        for item in value:
            cleaned_item, removed = _clean(item)
            if not removed:
                cleaned_items.append(cleaned_item)
        if not cleaned_items:
            return None, True
        return cleaned_items, False

    if isinstance(value, dict):
        cleaned_obj = {}
        for key, item in value.items():
            cleaned_item, removed = _clean(item)
            if not removed:
                cleaned_obj[key] = cleaned_item
        if not cleaned_obj:
            return None, True
        return cleaned_obj, False

    return value, False


def clean_json(data):
    cleaned, removed = _clean(data)
    if removed:
        return {}
    return cleaned


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"

    def _send_json(self, status_code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status_code, text):
        payload = text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            raise ValueError("Empty request body")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc

    def _jsonrpc_error(self, request_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if self.path == "/.well-known/openai-apps-challenge":
            self._send_text(200, "challenge-ok")
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/mcp":
            self._send_json(404, {"error": "Not found"})
            return

        request_id = None
        try:
            request = self._read_json_body()
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            request_id = request.get("id")
            if request.get("jsonrpc") != "2.0":
                raise ValueError("jsonrpc must be '2.0'")

            method = request.get("method")
            params = request.get("params", {})
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                        "capabilities": {"tools": {}},
                    },
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "clean_api_response",
                                "description": "Remove null/empty values from JSON recursively.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"data": {}},
                                    "required": ["data"],
                                    "additionalProperties": False,
                                },
                            }
                        ]
                    },
                }
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {})

                if name != "clean_api_response":
                    response = self._jsonrpc_error(request_id, -32602, "Unknown tool")
                elif not isinstance(args, dict) or "data" not in args:
                    response = self._jsonrpc_error(
                        request_id,
                        -32602,
                        "Invalid tool arguments: expected object with 'data'",
                    )
                else:
                    cleaned = clean_json(args["data"])
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "json",
                                    "json": {"cleaned": cleaned},
                                }
                            ]
                        },
                    }
            else:
                response = self._jsonrpc_error(request_id, -32601, "Method not found")

            self._send_json(200, response)
        except ValueError as exc:
            self._send_json(400, self._jsonrpc_error(request_id, -32600, "Invalid Request", str(exc)))
        except Exception as exc:
            self._send_json(500, self._jsonrpc_error(request_id, -32603, "Internal error", str(exc)))


def main():
    host = "0.0.0.0"
    port = 8000
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"{APP_NAME} listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
