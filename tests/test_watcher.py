from gramwrite.watcher import MAX_EXTRACT_CHARS, MacOSExtractor, TypedTextBuffer


def make_extractor_with_attrs(attrs, ranges=None, range_text=None):
    extractor = MacOSExtractor.__new__(MacOSExtractor)
    extractor._cached_pid = None
    extractor._cached_text_element = None
    extractor._read_attribute = lambda element, attr: attrs.get(element, {}).get(attr)
    extractor._read_range_attribute = lambda element, attr: (ranges or {}).get((element, attr))
    extractor._read_text_for_range = lambda element, location, length: (
        range_text.get((element, location, length)) if range_text else None
    )
    return extractor


def test_slice_text_around_range_centers_on_cursor():
    prefix = "A" * 420
    marker = "He walk to the store."
    suffix = "B" * 420
    text = prefix + marker + suffix

    snippet = MacOSExtractor._slice_text_around_range(text, len(prefix), 0)

    assert marker in snippet
    assert len(snippet) <= MAX_EXTRACT_CHARS
    assert snippet != text[-MAX_EXTRACT_CHARS:]


def test_find_text_descendant_walks_past_window_shell():
    attrs = {
        "window": {"AXRole": "AXWindow", "AXChildren": ["group"]},
        "group": {"AXRole": "AXGroup", "AXChildren": ["editor"]},
        "editor": {"AXRole": "AXTextArea", "AXValue": "INT. ROOM - DAY"},
    }
    extractor = make_extractor_with_attrs(attrs)

    assert extractor._find_text_descendant("window") == "editor"


def test_extract_text_from_element_uses_selected_range_when_value_is_large():
    prefix = "A" * 420
    marker = "He walk to the store."
    suffix = "B" * 420
    text = prefix + marker + suffix

    attrs = {
        "editor": {
            "AXRole": "AXTextArea",
            "AXSelectedText": "",
            "AXValue": text,
        }
    }
    ranges = {
        ("editor", "AXSelectedTextRange"): (len(prefix), 0),
    }
    extractor = make_extractor_with_attrs(attrs, ranges=ranges)

    snippet = extractor._extract_text_from_element("editor")

    assert snippet is not None
    assert marker in snippet
    assert snippet != text[-MAX_EXTRACT_CHARS:]


def test_typed_text_buffer_tracks_recent_input_per_app():
    buffer = TypedTextBuffer(max_chars=40, ttl_secs=60.0)

    buffer.record_text("com.generalcoffee.fadein", "He walk")
    buffer.record_text("com.generalcoffee.fadein", "s")
    buffer.record_backspace("com.generalcoffee.fadein")
    buffer.record_text("com.generalcoffee.fadein", " to the store.")

    assert buffer.snapshot("com.generalcoffee.fadein") == "He walk to the store."
    assert buffer.snapshot("com.openai.codex") is None
