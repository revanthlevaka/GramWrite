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
