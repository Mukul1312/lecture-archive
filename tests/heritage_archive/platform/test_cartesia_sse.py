"""Fixture-only tests for strict incremental Cartesia SSE framing."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.platform.cartesia.sse import (
    IncrementalSseParser,
    SseFrame,
    SseParseError,
)


class IncrementalSseParserTests(unittest.TestCase):
    def test_frames_crlf_and_lf_with_multibyte_data_split_across_chunks(self) -> None:
        """Decoding each HTTP chunk would corrupt an Odia scalar split between chunks."""
        parser = IncrementalSseParser(maximum_event_bytes=1024)
        odia = "ଓଡ଼ିଆ".encode("utf-8")
        wire = (
            b": heartbeat\r\n"
            b"event: chunk\r\n"
            b"data: {\"text\":\""
            + odia
            + b"\"}\r\n"
            b"data: tail\r\n"
            b"\r\n"
            b"data: done\n\n"
        )
        split = wire.index(odia) + 2

        parser.feed(wire[:split])
        parser.feed(wire[split : split + 1])
        parser.feed(wire[split + 1 :])
        parser.finish()

        self.assertEqual(
            parser.frames,
            (
                SseFrame(event="chunk", data=b'{"text":"' + odia + b'"}\ntail'),
                SseFrame(event=None, data=b"done"),
            ),
        )

    def test_blank_line_dispatches_empty_and_multiple_data_fields_exactly(self) -> None:
        """Dropping empty data or normalizing payload bytes would change provider evidence."""
        parser = IncrementalSseParser(maximum_event_bytes=128)

        emitted = parser.feed(b"event:\ndata:\ndata:  second \n\n")
        parser.finish()

        self.assertEqual(emitted, (SseFrame(event="", data=b"\n second "),))
        self.assertEqual(parser.frames, emitted)

    def test_comment_only_blocks_do_not_emit_frames(self) -> None:
        """Treating keepalive comments as provider events would break event contiguity."""
        parser = IncrementalSseParser(maximum_event_bytes=128)

        emitted = parser.feed(b": keepalive\n\n:\n\n")
        parser.finish()

        self.assertEqual(emitted, ())
        self.assertEqual(parser.frames, ())

    def test_completed_frames_survive_a_later_malformed_field(self) -> None:
        """A bad later event must not erase already-completed provider evidence."""
        parser = IncrementalSseParser(maximum_event_bytes=128)

        with self.assertRaisesRegex(SseParseError, "sse_malformed_field") as raised:
            parser.feed(b"data: retained\n\nretry: 3\n\n")

        self.assertEqual(raised.exception.reason_code, "sse_malformed_field")
        self.assertEqual(parser.frames, (SseFrame(event=None, data=b"retained"),))

    def test_invalid_utf8_is_rejected_only_after_split_bytes_form_a_frame(self) -> None:
        """Replacement decoding would silently mutate provider evidence."""
        parser = IncrementalSseParser(maximum_event_bytes=128)

        parser.feed(b"data: \xf0")
        with self.assertRaisesRegex(SseParseError, "sse_invalid_utf8") as raised:
            parser.feed(b"(\x8c(\n\n")

        self.assertEqual(raised.exception.reason_code, "sse_invalid_utf8")
        self.assertEqual(parser.frames, ())

    def test_colonless_field_and_bare_carriage_return_are_malformed(self) -> None:
        """Permissive line parsing would accept a wire shape outside the frozen grammar."""
        fixtures = (b"data\n\n", b"data: first\rdata: second\n\n")

        for wire in fixtures:
            with self.subTest(wire=wire):
                parser = IncrementalSseParser(maximum_event_bytes=128)
                with self.assertRaises(SseParseError) as raised:
                    parser.feed(wire)
                self.assertEqual(raised.exception.reason_code, "sse_malformed_field")

    def test_unterminated_final_frame_is_rejected(self) -> None:
        """EOF without a blank dispatch boundary is a truncated provider stream."""
        parser = IncrementalSseParser(maximum_event_bytes=128)
        parser.feed(b"event: chunk\ndata: partial\n")

        with self.assertRaises(SseParseError) as raised:
            parser.finish()

        self.assertEqual(raised.exception.reason_code, "sse_truncated")
        self.assertEqual(parser.frames, ())

    def test_event_wire_bytes_are_bounded_before_a_newline_arrives(self) -> None:
        """A peer withholding line endings must not grow the event buffer past its cap."""
        parser = IncrementalSseParser(maximum_event_bytes=12)

        with self.assertRaises(SseParseError) as raised:
            parser.feed(b"data: 1234567")

        self.assertEqual(raised.exception.reason_code, "sse_event_too_large")
        self.assertEqual(parser.frames, ())

    def test_event_bound_counts_each_nonblank_line_ending(self) -> None:
        """Many tiny fields must not bypass the wire-size cap through framing overhead."""
        parser = IncrementalSseParser(maximum_event_bytes=12)

        with self.assertRaises(SseParseError) as raised:
            parser.feed(b"data:\r\ndata:\r\n\r\n")

        self.assertEqual(raised.exception.reason_code, "sse_event_too_large")
        self.assertEqual(parser.frames, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
