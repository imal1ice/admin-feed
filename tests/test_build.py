"""Run with: python -m unittest discover tests"""
import io
import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock as mock
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import build


def alert(**kw):
    row = {"ts": "2026-11-01T00:00:00Z", "chain": "ethereum", "contract": "0x" + "ab" * 20, "label": "Gov", "event": "CallScheduled",
           "source": "OZ", "severity": "high", "message": "m", "block": 5, "tx_hash": "0x" + "cd" * 32}
    return {**row, **kw}


class Rss(unittest.TestCase):
    def test_on_chain_control_characters_do_not_break_the_feed(self):
        rows = [alert(message="title\x00\x08\x1b\x7f ￾<b>&", label="a\x0bb")]
        build.assign_guids(rows)
        desc = ET.fromstring(build.render_rss(rows)).find("channel/item/description").text
        self.assertIn("title", desc)
        self.assertIn("<b>&", desc)
        self.assertNotIn("\x00", desc)

    def test_guids_are_unique_and_earlier_ones_never_change(self):
        rows = [alert(message="a"), alert(message="b"), alert(message="a"), alert(block=6)]
        build.assign_guids(rows)
        guids = [r["guid"] for r in rows]
        self.assertEqual(len(set(guids)), 4)
        self.assertFalse(guids[0].endswith(":2"))
        later = rows + [alert(message="c")]
        build.assign_guids(later)
        self.assertEqual([r["guid"] for r in later[:4]], guids)


class Links(unittest.TestCase):
    def test_safe_queue_alert_links_to_the_queue_not_a_transaction(self):
        row = alert(source="Safe", event="SafeTxProposed", block=0, tx_hash="0x" + "11" * 32)
        self.assertEqual(build.tx_url(row), f"https://app.safe.global/transactions/queue?safe=eth:{row['contract']}")
        self.assertIn(">0x11111111…<", build.tx_link(row))

    def test_on_chain_safe_event_links_to_its_transaction(self):
        row = alert(source="Safe", event="AddedOwner", block=7)
        self.assertEqual(build.tx_url(row), f"https://etherscan.io/tx/{row['tx_hash']}")


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BlockDates(unittest.TestCase):
    def run_with(self, *answers):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build, "BLOCKTIMES", pathlib.Path(d) / "b.json"), \
                mock.patch("time.sleep"), mock.patch("urllib.request.urlopen", side_effect=list(answers)):
            return build.block_dates([alert(block=5, ts="2026-11-01T00:00:00Z")])

    def test_rpc_error_object_falls_back_to_the_alert_date(self):
        err = Answer(json.dumps({"error": {"code": -32005, "message": "rate limited"}}).encode())
        self.assertEqual(self.run_with(*[err] * 4), {5: "2026-11-01"})

    def test_garbage_and_dropped_connections_fall_back(self):
        import http.client
        self.assertEqual(self.run_with(Answer(b"<html>"), http.client.RemoteDisconnected("x"), ConnectionResetError(), TimeoutError()),
                         {5: "2026-11-01"})

    def test_retry_after_bad_answer_succeeds(self):
        good = Answer(json.dumps([{"id": 5, "result": {"timestamp": hex(86400)}}]).encode())
        self.assertEqual(self.run_with(Answer(b"{}"), good), {5: "1970-01-02"})

    def test_block_zero_is_never_fetched(self):
        with mock.patch("urllib.request.urlopen") as call, tempfile.TemporaryDirectory() as d, \
                mock.patch.object(build, "BLOCKTIMES", pathlib.Path(d) / "b.json"):
            build.block_dates([alert(block=0)])
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
