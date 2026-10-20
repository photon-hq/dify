"""Optional acceptance-only validation against the supplied OpenAPI 3.1 file."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class OpenAPIContract:
    def __init__(self):
        from jsonschema import Draft202012Validator

        self.validator = Draft202012Validator
        self.spec = json.loads(Path(os.environ["PHOTON_OPENAPI"]).read_text())

    def validate(self, value, schema):
        self.validator({"components": self.spec["components"], **schema}).validate(value)

    def validate_request(self, request):
        parsed = urlparse(request.url)
        path = "/v1/projects/{id}/" + parsed.path.split("/", 4)[4]
        if path.startswith("/v1/projects/{id}/messages/"):
            path = "/v1/projects/{id}/messages/{messageId}"
        if path.startswith("/v1/projects/{id}/attachments/"):
            path = "/v1/projects/{id}/attachments/{attachmentId}" + ("/content" if path.endswith("/content") else "")
        operation = self.spec["paths"][path][request.method.lower()]
        query = parse_qs(parsed.query)
        known = {p["name"]: p for p in operation.get("parameters", []) if p["in"] == "query"}
        unknown = set(query) - set(known)
        if unknown:
            raise AssertionError("Query parameters absent from official OpenAPI")
        for name, values in query.items():
            value = int(values[0]) if name == "pageSize" else values[0]
            self.validate(value, known[name]["schema"])
        if request.method == "POST":
            media_type = request.headers["Content-Type"].split(";", 1)[0]
            if media_type == "application/json":
                self.validate(json.loads(request.body), operation["requestBody"]["content"]["application/json"]["schema"])
            elif media_type not in operation["requestBody"]["content"]:
                raise AssertionError("Request media type absent from official OpenAPI")
            parameter = next(p for p in operation["parameters"] if p["in"] == "header" and p["name"] == "idempotency-key")
            self.validate(request.headers["Idempotency-Key"], parameter["schema"])
