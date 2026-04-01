from gramwrite.fountain_parser import FountainParser, FountainElement as ParserState

def test_empty_string():
    parser = FountainParser()
    assert parser.classify("").element == ParserState.UNKNOWN

def test_sluglines():
    parser = FountainParser()
    assert parser.classify("INT. OFFICE - DAY").element == ParserState.SLUGLINE
    assert parser.classify("EXT. HIGHWAY - NIGHT").element == ParserState.SLUGLINE
    assert parser.classify("I/E. CAR - CONTINUOUS").element == ParserState.SLUGLINE

def test_characters():
    parser = FountainParser()
    assert parser.classify("JOHN").element == ParserState.CHARACTER
    parser.reset_context()
    assert parser.classify("MARY JANE").element == ParserState.CHARACTER
    parser.reset_context()
    assert parser.classify("POLICE OFFICER (O.S.)").element == ParserState.CHARACTER
    parser.reset_context()
    assert parser.classify("John").element == ParserState.ACTION

    parser.reset_context()
    assert parser.classify("JOHN CARTER, JR.").element == ParserState.CHARACTER
    parser.reset_context()
    assert parser.classify("O'NEIL (V.O.)").element == ParserState.CHARACTER

def test_transitions():
    parser = FountainParser()
    assert parser.classify("CUT TO:").element == ParserState.TRANSITION
    parser.reset_context()
    assert parser.classify("> FADE OUT.").element == ParserState.TRANSITION
    
def test_parentheticals():
    parser = FountainParser()
    assert parser.classify("(sighs)").element == ParserState.PARENTHETICAL
    assert parser.classify(" (whispering) ").element == ParserState.PARENTHETICAL
    assert parser.classify("(beat)").element == ParserState.PARENTHETICAL

def test_general_action_dialogue():
    parser = FountainParser()
    assert parser.classify("JOHN").element == ParserState.CHARACTER
    assert parser.classify("I can't believe you did that.").element == ParserState.DIALOGUE
    parser.reset_context()
    assert parser.classify("He walked across the room.").element == ParserState.ACTION

# ─── Dual Dialogue Tests ─────────────────────────────────────────────────────

def test_dual_dialogue_detection():
    """Test ^ prefix for dual dialogue (Fountain syntax)."""
    parser = FountainParser()
    result = parser.classify("^I'm talking at the same time!")
    assert result.element == ParserState.DIALOGUE
    assert result.is_dual_dialogue is True
    assert result.text == "I'm talking at the same time!"
    assert result.should_check is True

def test_dual_dialogue_sets_context():
    """Dual dialogue should set dialogue block context."""
    parser = FountainParser()
    parser.classify("^First line of dual dialogue")
    # Next line should be treated as dialogue since we're in a dialogue block
    result = parser.classify("Second line continues")
    assert result.element == ParserState.DIALOGUE

# ─── Forced Action Tests ─────────────────────────────────────────────────────

def test_forced_action_detection():
    """Test ! prefix to force action line classification."""
    parser = FountainParser()
    result = parser.classify("!This is forced action")
    assert result.element == ParserState.ACTION
    assert result.is_forced_action is True
    assert result.text == "This is forced action"
    assert result.should_check is True

def test_forced_action_breaks_dialogue():
    """Forced action should break dialogue block context."""
    parser = FountainParser()
    parser.classify("JOHN")
    parser.classify("Some dialogue here")
    # Force action even though we're in dialogue block
    result = parser.classify("!Forced action line")
    assert result.element == ParserState.ACTION
    assert result.is_forced_action is True

# ─── Emphasis Detection Tests ────────────────────────────────────────────────

def test_emphasis_asterisk():
    """Test *text* emphasis pattern detection."""
    parser = FountainParser()
    result = parser.classify("He *really* meant it.")
    assert result.emphasis_spans is not None
    assert len(result.emphasis_spans) == 1
    start, end = result.emphasis_spans[0]
    assert result.text[start:end] == "*really*"

def test_emphasis_underscore():
    """Test _text_ emphasis pattern detection."""
    parser = FountainParser()
    result = parser.classify("She _whispered_ softly.")
    assert result.emphasis_spans is not None
    assert len(result.emphasis_spans) == 1
    start, end = result.emphasis_spans[0]
    assert result.text[start:end] == "_whispered_"

def test_emphasis_multiple():
    """Test multiple emphasis patterns in one line."""
    parser = FountainParser()
    result = parser.classify("He *shouted* and _cried_ at once.")
    assert result.emphasis_spans is not None
    assert len(result.emphasis_spans) == 2

def test_emphasis_in_dialogue():
    """Emphasis should be detected in dialogue blocks."""
    parser = FountainParser()
    parser.classify("JOHN")
    result = parser.classify("I *never* said that!")
    assert result.element == ParserState.DIALOGUE
    assert result.emphasis_spans is not None
    assert len(result.emphasis_spans) == 1

def test_no_emphasis():
    """Lines without emphasis should have empty emphasis_spans."""
    parser = FountainParser()
    result = parser.classify("Just a normal line.")
    assert result.emphasis_spans is not None
    assert len(result.emphasis_spans) == 0

# ─── Line Break Tests ────────────────────────────────────────────────────────

def test_line_break_html():
    """Test <br> and <br/> line break detection."""
    parser = FountainParser()
    result = parser.classify("First line<br>Second line")
    assert result.has_line_breaks is True

    result = parser.classify("First line<br/>Second line")
    assert result.has_line_breaks is True

    result = parser.classify("First line<br />Second line")
    assert result.has_line_breaks is True

def test_line_break_double_space():
    """Test double space line break detection."""
    parser = FountainParser()
    result = parser.classify("First line  Second line")
    assert result.has_line_breaks is True

def test_no_line_breaks():
    """Lines without breaks should have has_line_breaks=False."""
    parser = FountainParser()
    result = parser.classify("Just a normal line.")
    assert result.has_line_breaks is False

def test_line_breaks_in_action():
    """Line breaks should be detected in action lines."""
    parser = FountainParser()
    result = parser.classify("He walked in.<br>She looked up.")
    assert result.element == ParserState.ACTION
    assert result.has_line_breaks is True
