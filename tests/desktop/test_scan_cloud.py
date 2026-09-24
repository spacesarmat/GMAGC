import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from gmagc_desktop.scan.cloud import PROMPT, SCHEMA, CloudScanner, draft_from_reply, prepare_image
from gmagc_desktop.scan.engine import ScanError, ScanUnavailableError

REPLY = {
    "modes": [
        {
            "name": "9CH",
            "channels": [
                {"dmx": 1, "name": "Total dimming", "template": "dimmer", "bits": 8, "ranges": []},
                {
                    "dmx": 3,
                    "name": "Macro",
                    "template": "control",
                    "bits": 8,
                    "ranges": [{"start": 0, "end": 5, "name": "null"}, {"start": 6, "end": 9, "name": "hop"}],
                },
            ],
        }
    ]
}


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    def __init__(self, reply=None, stop="end_turn", error=None):
        self.calls = []
        self.error = error
        text = json.dumps(REPLY if reply is None else reply)
        self.message = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeStream(self.message)


def scanner(client, key="sk-test"):
    return CloudScanner(lambda: key, lambda _key: client)


def png(size=(50, 50)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_photo_is_sent_as_an_image_with_the_schema_and_gives_a_cloud_draft():
    client = FakeClient()

    draft = scanner(client).scan(png())

    call = client.calls[0]
    block = call["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert call["messages"][0]["content"][1]["text"] == PROMPT
    assert draft.engine == "cloud" and draft.modes[0].name == "9CH"
    assert [c.template for c in draft.modes[0].channels] == ["dimmer", "control"]
    assert [(r.start, r.end, r.name) for r in draft.modes[0].channels[1].ranges] == [(0, 5, "null"), (6, 9, "hop")]


def test_a_pdf_is_sent_as_a_document():
    client = FakeClient()

    scanner(client).scan(b"%PDF-1.7 body")

    block = client.calls[0]["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == b"%PDF-1.7 body"


def test_no_key_means_the_cloud_is_unavailable_and_nothing_is_sent():
    client = FakeClient()

    with pytest.raises(ScanUnavailableError, match="ключ"):
        scanner(client, key="  ").scan(png())

    assert client.calls == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("AuthenticationError", ScanUnavailableError),
        ("RateLimitError", ScanError),
        ("APIConnectionError", ScanError),
        ("BadRequestError", ScanError),
        ("SomethingElse", ScanError),
    ],
)
def test_sdk_errors_become_scan_errors_without_leaking_details(name, expected):
    error = type(name, (Exception,), {})("secret sk-test details")

    with pytest.raises(expected) as caught:
        scanner(FakeClient(error=error)).scan(png())

    assert "sk-test" not in str(caught.value)


def test_a_refusal_or_a_cut_off_answer_is_reported():
    with pytest.raises(ScanError, match="отказалось"):
        scanner(FakeClient(stop="refusal")).scan(png())
    with pytest.raises(ScanError, match="слишком большая"):
        scanner(FakeClient(stop="max_tokens")).scan(png())


def test_broken_channels_are_dropped_and_an_empty_result_warns():
    reply = {
        "modes": [
            {
                "name": "x",
                "channels": [
                    {"dmx": 0, "name": "no address", "template": "custom", "bits": 8, "ranges": []},
                    {"dmx": 2, "name": "", "template": "custom", "bits": 8, "ranges": []},
                    {
                        "dmx": 4,
                        "name": "Ok",
                        "template": "nonsense",
                        "bits": 8,
                        "ranges": [{"start": 9, "end": 3, "name": "bad"}],
                    },
                ],
            },
            {"name": "empty", "channels": []},
        ]
    }

    draft = draft_from_reply(json.dumps(reply))

    assert [(m.name, [(c.dmx, c.template, c.ranges) for c in m.channels]) for m in draft.modes] == [
        ("x", [(4, "custom", ())])
    ]
    assert draft_from_reply('{"modes": []}').warnings == ("no_table",)
    with pytest.raises(ScanError):
        draft_from_reply("not json")


def test_a_big_photo_is_shrunk_and_a_small_one_is_kept():
    small = png()
    assert prepare_image(small) == (small, "image/png")

    big, media = prepare_image(png((5000, 3000)))
    assert media == "image/jpeg" and max(Image.open(io.BytesIO(big)).size) <= 2000

    with pytest.raises(ScanError):
        prepare_image(b"not an image")
