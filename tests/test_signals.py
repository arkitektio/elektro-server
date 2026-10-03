"""elektro's model signals: what it declares to the hub's rekuest, and that a save reaches it signed.

The save goes to a real local HTTP server standing in for rekuest's signal intake, and is
checked the way rekuest checks it (the instance-key JWT, the body).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from joserfc.jwk import OKPKey

from rekuest_service import trust
from elektro_server.service import service

EXPECTED = {
    "@elektro/arraydataset": [
        "CREATED",
        "UPDATED",
        "DELETED"
    ],
    "@elektro/tabledataset": [
        "CREATED",
        "UPDATED",
        "DELETED"
    ],
    "@elektro/sparsedataset": [
        "CREATED",
        "DELETED"
    ],
    "@elektro/neuronmodel": [
        "CREATED"
    ],
    "@elektro/modelcollection": [
        "CREATED"
    ],
    "@elektro/experiment": [
        "CREATED",
        "UPDATED",
        "DELETED"
    ],
    "@elektro/file": [
        "CREATED",
        "DELETED"
    ],
    "@elektro/folder": [
        "CREATED",
        "UPDATED",
        "DELETED"
    ],
    "@elektro/annotationcollection": [
        "CREATED",
        "DELETED"
    ]
}

KEY = OKPKey.generate_key("Ed25519")


class _Intake:
    def __init__(self) -> None:
        self.received: list[dict] = []
        intake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                intake.received.append({"path": self.path, "headers": dict(self.headers), "body": body, "json": json.loads(body)})
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def of(self, identifier: str, count: int = 1, timeout: float = 10) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = [r for r in self.received if r["json"]["identifier"] == identifier]
            if len(found) >= count:
                return found
            time.sleep(0.05)
        return [r for r in self.received if r["json"]["identifier"] == identifier]


@pytest.fixture
def intake(settings):
    server = _Intake()
    settings.REKUEST_SERVICE = {"REKUEST_URL": server.url, "SERVICE": "elektro"}
    settings.INSTANCE = {
        "PRIVATE_KEY": KEY.as_pem(private=True).decode(),
        "TRUST_JWKS": {"keys": [{**trust.public_jwk(KEY), "service": "live.arkitekt.elektro"}]},
    }
    yield server
    server.server.shutdown()


def _organization():
    from authentikate.models import Organization

    return Organization.objects.get_or_create(slug="signals-test-org")[0]


def test_the_manifest_declares_every_model_signal():
    assert {s["identifier"]: s["kinds"] for s in service.manifest()["signals"]} == EXPECTED


def test_the_manifest_lists_what_elektro_hosts_with_its_descriptors():
    hosted = {s["identifier"]: s for s in service.manifest()["structures"]}
    # Everything signalled is hosted; a lens is hosted without ever being signalled.
    assert set(hosted) == {*EXPECTED, "@elektro/lens"}
    assert hosted["@elektro/folder"]["label"] == "Folder"
    array_keys = [d["key"] for d in hosted["@elektro/arraydataset"]["descriptors"]]
    assert array_keys == [d["key"] for d in hosted["@elektro/lens"]["descriptors"]]
    assert {"key": "@elektro/n_samples", "type": "INT", "description": "Its total extent along its TIME axes"} in hosted["@elektro/arraydataset"]["descriptors"]
    assert hosted["@elektro/tabledataset"]["descriptors"] == []


@pytest.mark.django_db(transaction=True)
def test_a_save_is_signalled_signed_by_this_instance(intake):
    from core.models import Experiment

    org = _organization()
    obj = Experiment.objects.create(name='signalled', organization=org)

    (received,) = intake.of("@elektro/experiment")
    assert (received["json"]["kind"], received["json"]["object"], received["json"]["organization"]) == ("CREATED", str(obj.pk), org.slug)
    assert received["path"] == "/agi/signal/elektro"
    verified = trust.verify("POST", received["path"], received["body"], received["headers"]["Authorization"], audience="live.arkitekt.rekuest")
    assert verified.issuer == "live.arkitekt.elektro"
