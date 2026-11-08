"""
novelWriter - Spell Check Tests
===============================

This file is a part of novelWriter
Copyright (C) 2020 Veronica Berglyd Olsen and novelWriter contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import sys
import threading

from contextlib import nullcontext
from importlib.util import find_spec
from itertools import count, product
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from PyQt6.QtCore import QThreadPool
from pytestqt.qtbot import QtBot

from novelwriter import SHARED
from novelwriter.common import utf16CharMap
from novelwriter.constants import nwFiles
from novelwriter.core.project import NWProject
from novelwriter.core.spellcheck import FakeEnchant, SpellApple, SpellEnchant, UserDictionary
from novelwriter.editor.runnables import TextCheckDispatcher

from tests.helpers import buildTestProject
from tests.mocked import MockGuiMain, causeException, causeOSError

HAS_ENCHANT = find_spec("enchant") is not None
IS_DARWIN = sys.platform == "darwin"


@pytest.mark.core
def testUserDictionary_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the UserDictionary class."""
    project = NWProject()
    buildTestProject(project, fncPath)

    # Check that there is no file before we start
    dictFile = project.storage.getMetaFile(nwFiles.DICT_FILE)
    assert isinstance(dictFile, Path)
    assert not dictFile.exists()

    # Add a couple of words
    userDict = UserDictionary(project)
    assert userDict.add("foo") is True
    assert userDict.add("bar") is True
    assert userDict.add("bar") is False  # No duplicates

    # Check that we have them
    assert "foo" in userDict
    assert "bar" in userDict

    # Check the iterator
    assert sorted(userDict) == ["bar", "foo"]

    # Save the file, but fail
    with monkeypatch.context() as mp:
        mp.setattr("builtins.open", causeOSError)
        userDict.save()

    # There should be no file
    assert not dictFile.exists()

    # Break the path check
    with monkeypatch.context() as mp:
        mp.setattr("novelwriter.core.storage.ProjectStorage.getMetaFile", lambda *a: None)
        userDict.save()

    # There should still be no file
    assert not dictFile.exists()

    # Save proper
    userDict.save()
    assert dictFile.exists()

    # Clear the dictionary
    userDict._words = set()
    assert sorted(userDict) == []

    # Load the file, but fail
    with monkeypatch.context() as mp:
        mp.setattr("builtins.open", causeOSError)
        userDict.load()

    # No words loaded
    assert sorted(userDict) == []

    # Break the path check
    with monkeypatch.context() as mp:
        mp.setattr("novelwriter.core.storage.ProjectStorage.getMetaFile", lambda *a: None)
        userDict.load()

    # No words loaded
    assert sorted(userDict) == []

    # Load the words again, properly
    userDict.load()
    assert sorted(userDict) == ["bar", "foo"]


@pytest.mark.core
def testFakeEnchant_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the FakeEnchant spell checker fallback."""
    project = NWProject()
    buildTestProject(project, fncPath)

    # Make package import fail
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "enchant", None)
        spChk = SpellEnchant(project)
        spChk.setLanguage("en_US")
        assert isinstance(spChk._enchant, FakeEnchant)

    # Request a non-existent dictionary
    spChk = SpellEnchant(project)
    spChk.setLanguage("whatchamajig")
    assert isinstance(spChk._enchant, FakeEnchant)

    # Request an empty language string
    # See #1096
    spChk = SpellEnchant(project)
    spChk.setLanguage("")
    assert isinstance(spChk._enchant, FakeEnchant)

    # FakeEnchant should handle requests
    fkChk = FakeEnchant()
    assert fkChk.tag == ""
    assert fkChk.provider.name == ""
    assert fkChk.check("whatchamajig") is True
    assert fkChk.suggest("whatchamajig") == []
    assert fkChk.add_to_session("whatchamajig") is None


class MockBroker:
    """Stand-in for enchant.Broker."""

    def request_dict(self, tag: str) -> None:
        """Mock dictionary request."""
        return


def mockEnchantModule(mp: pytest.MonkeyPatch) -> None:
    """Install a minimal enchant module."""
    enchant = ModuleType("enchant")
    enchant.__dict__["Broker"] = MockBroker
    enchant.__dict__["dict_exists"] = lambda tag: False
    enchant.__dict__["list_dicts"] = list
    mp.setitem(sys.modules, "enchant", enchant)


@pytest.mark.core
def testSpellEnchant_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the pyenchant spell checker."""
    if not HAS_ENCHANT:
        mockEnchantModule(monkeypatch)

    project = NWProject()
    buildTestProject(project, fncPath)

    # Break the enchant package, and check error handling
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "enchant", None)
        spChk = SpellEnchant(project)
        assert spChk.spellLanguage is None
        assert spChk.listDictionaries() == []
        assert spChk.describeDict() == ("", "")

        spChk.setLanguage("en_US")
        assert spChk.spellLanguage is None

        # Check that the FakeEnchant class is actually handling this
        assert isinstance(spChk._enchant, FakeEnchant)
        assert spChk.checkWord("word") is True
        assert spChk.suggestWords("word") == []
        spChk.addWord("word")
        assert "word" in spChk._userDict

    # Set the dict to None, and check enchant error handling
    spChk = SpellEnchant(project)
    spChk._enchant = None  # type: ignore
    assert spChk.checkWord("word") is True
    assert spChk.suggestWords("word") == []

    spChk.addWord("word")
    assert "word" not in spChk._userDict

    spChk.addWord("\n\t ")
    assert "\n\t " not in spChk._userDict

    assert spChk.describeDict() == ("", "")

    # Stand-in for a real enchant.Dict, so the rest of this test does not
    # depend on a dictionary actually being installed on the system.
    class MockDict:
        tag = "en_US"

        class provider:
            name = "Mock Provider"

        def check(self, word: str) -> bool:
            return True

        def suggest(self, word: str) -> list[str]:
            return []

        def add_to_session(self, word: str) -> None:
            return

    # Load the proper enchant package (twice)
    with monkeypatch.context() as mp:
        mp.setattr("enchant.dict_exists", lambda *a: True)
        mp.setattr("enchant.Broker.request_dict", lambda *a: MockDict())
        mp.setattr("enchant.list_dicts", lambda *a: [("en_US", None)])

        spChk = SpellEnchant(project)
        spChk.setLanguage("en_US")
        spChk.setLanguage("en_US")
        assert isinstance(spChk._enchant, MockDict)
        assert spChk.spellLanguage == "en_US"
        assert spChk.listDictionaries() != []
        assert spChk.describeDict() != ("", "")

        # Set to non-existent language
        mp.setattr("enchant.dict_exists", lambda *a: False)
        spChk.setLanguage("foo_bar")
        assert isinstance(spChk._enchant, FakeEnchant)

        # Block the broker from figuring out the language
        mp.setattr("enchant.dict_exists", lambda *a: True)
        mp.setattr("enchant.Broker.request_dict", lambda *a: None)
        spChk.setLanguage("en_US")
        assert isinstance(spChk._enchant, FakeEnchant)
        assert spChk.spellLanguage is None

        # Failing to add user words keeps the language loaded
        mp.setattr("enchant.Broker.request_dict", lambda *a: MockDict())
        mp.setattr(MockDict, "add_to_session", causeException)
        assert "word" in spChk._userDict
        spChk.setLanguage("en_US")
        assert spChk.spellLanguage == "en_US"


@pytest.mark.core
def testSpellChecker_Cache(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the spell checker word cache."""
    project = NWProject()
    buildTestProject(project, fncPath)

    class MockEnchant(FakeEnchant):
        def check(self, word: str) -> bool:
            return word != "wrod"

    spChk = SpellEnchant(project)
    spChk._enchant = MockEnchant()
    assert spChk._cache == {}

    # Checked words should be cached with their result
    assert spChk.checkWord("word") is True
    assert spChk.checkWord("wrod") is False
    assert spChk._cache == {"word": True, "wrod": False}

    # Cached results should be returned without calling the checker,
    # which we verify by swapping in FakeEnchant, which always says True
    spChk._enchant = FakeEnchant()
    assert spChk.checkWord("wrod") is False  # Cached result
    assert spChk.checkWord("wrodd") is True  # New word, hits FakeEnchant
    assert spChk._cache == {"word": True, "wrod": False, "wrodd": True}

    # When the cache is full, it should be cleared before the next add
    with monkeypatch.context() as mp:
        mp.setattr("novelwriter.core.spellcheck.MAX_CACHE_SIZE", 2)
        assert spChk.checkWord("stuff") is True
        assert spChk._cache == {"stuff": True}

    # Adding a word to the dictionary should also add it to the cache
    spChk.addWord("zpqxy", save=False)
    assert spChk._cache == {"stuff": True, "zpqxy": True}
    assert spChk.checkWord("zpqxy") is True

    # Changing the language should clear the cache
    spChk.setLanguage(None)
    assert spChk._cache == {}


class MockNSSpellChecker:
    """Stand-in for NSSpellChecker on other platforms."""

    def __init__(self) -> None:
        self._words = {"hello", "world"}
        self._ignored: dict[int, set[str]] = {}
        self.closed: list[int] = []
        self.ranges: list[tuple[int, int]] = []

    def setLanguage_(self, language: str) -> bool:
        """Mock language selection."""
        return language in self.availableLanguages()

    def availableLanguages(self) -> list[str]:
        """Mock available languages."""
        return ["en", "de"]

    def checkSpellingOfString_startingAt_language_wrap_inSpellDocumentWithTag_wordCount_(
        self, word: str, start: int, language: str, wrap: bool, tag: int, count: None
    ) -> tuple[SimpleNamespace, int]:
        """Mock spell check of a single word."""
        known = word in self._words or word in self._ignored.get(tag, set())
        return SimpleNamespace(location=sys.maxsize if known else 0), 1

    def guessesForWordRange_inString_language_inSpellDocumentWithTag_(
        self, wordRange: SimpleNamespace, word: str, language: str, tag: int
    ) -> list[str]:
        """Mock spelling suggestions."""
        self.ranges.append((wordRange.location, wordRange.length))
        return ["hello"] if word == "helo" else []

    def ignoreWord_inSpellDocumentWithTag_(self, word: str, tag: int) -> None:
        """Mock ignoring a word in a spell document."""
        self._ignored.setdefault(tag, set()).add(word)

    def closeSpellDocumentWithTag_(self, tag: int) -> None:
        """Mock closing a spell document."""
        self.closed.append(tag)
        self._ignored.pop(tag, None)


def mockAppleModules(mp: pytest.MonkeyPatch) -> None:
    """Install minimal AppKit, Foundation and objc modules."""
    checker = MockNSSpellChecker()
    tags = count(1)

    appKit = ModuleType("AppKit")
    appKit.__dict__["NSSpellChecker"] = SimpleNamespace(
        sharedSpellChecker=lambda: checker,
        uniqueSpellDocumentTag=lambda: next(tags),
    )
    foundation = ModuleType("Foundation")
    foundation.__dict__["NSNotFound"] = sys.maxsize
    foundation.__dict__["NSMakeRange"] = lambda loc, length: SimpleNamespace(location=loc, length=length)

    objc = ModuleType("objc")
    objc.__dict__["autorelease_pool"] = nullcontext

    mp.setitem(sys.modules, "AppKit", appKit)
    mp.setitem(sys.modules, "Foundation", foundation)
    mp.setitem(sys.modules, "objc", objc)


@pytest.mark.core
def testSpellApple_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the macOS spell checker."""
    project = NWProject()
    buildTestProject(project, fncPath)

    # On macOS, check the system NSSpellChecker without assuming a language
    if IS_DARWIN:
        spChk = SpellApple(project)
        languages = spChk.listDictionaries()
        assert len(languages) > 0

        tag = languages[0][0]
        spChk.setLanguage(tag)
        assert spChk.spellLanguage == tag
        assert spChk.describeDict() == (tag, "AppleSpell")
        assert isinstance(spChk.checkWord("zpqxyq"), bool)
        assert isinstance(spChk.suggestWords("zpqxyq"), list)

        spChk.addWord("zpqxyq", save=False)
        spChk.setLanguage(tag)

        # Region tags stored by Enchant-based builds are accepted
        spChk.setLanguage("en_US")
        assert spChk.spellLanguage == "en_US"
        assert spChk.describeDict() == ("en_US", "AppleSpell")

    # The rest of the test uses a mock NSSpellChecker
    mockAppleModules(monkeypatch)

    spChk = SpellApple(project)
    assert spChk.spellLanguage is None
    assert spChk.describeDict() == ("", "")
    assert spChk.checkWord("helo") is True
    assert spChk.suggestWords("helo") == []

    # List languages
    languages = spChk.listDictionaries()
    assert len(languages) > 0
    assert languages == sorted(languages, key=lambda x: x[1])
    assert "en" in [tag for tag, _ in languages]

    # Invalid language
    spChk.setLanguage("whatchamajig")
    assert spChk.spellLanguage is None
    assert spChk.requestedLanguage == "whatchamajig"
    assert spChk.describeDict() == ("", "")
    assert spChk.checkWord("wrld") is True

    # Valid language
    spChk.setLanguage("en")
    assert spChk.spellLanguage == "en"
    assert spChk.describeDict() == ("en", "AppleSpell")
    assert spChk.checkWord("hello") is True
    assert spChk.checkWord("helo") is False
    assert spChk.checkWord("wrld") is False
    assert "hello" in spChk.suggestWords("helo")
    assert spChk._checker.ranges[-1] == (0, 4)

    # Suggestion ranges are measured in UTF-16 code units
    spChk.suggestWords("na\U0001d4d0ve")
    assert spChk._checker.ranges[-1] == (0, 6)
    spChk.suggestWords("\U0001f600helo")
    assert spChk._checker.ranges[-1] == (0, 6)

    # Add a word to the session and the user dictionary
    assert spChk.checkWord("zpqxyq") is False
    spChk.addWord("zpqxyq")
    assert spChk.checkWord("zpqxyq") is True
    assert "zpqxyq" in spChk._userDict

    # Words from the user dictionary are restored on language change
    oldTag = spChk._document
    spChk.setLanguage("en")
    assert spChk.checkWord("zpqxyq") is True

    # Loading a language closes the previous spell document
    assert spChk._document != oldTag
    assert spChk._checker.closed[-1] == oldTag
    assert oldTag not in spChk._checker._ignored

    # A new instance loads the user dictionary into its own session
    other = SpellApple(project)
    assert other._lock is spChk._lock
    other.setLanguage("en")
    assert other.checkWord("zpqxyq") is True

    # Backend errors are handled
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "AppKit", None)
        spChk.setLanguage("en")
        assert spChk.spellLanguage is None
        assert spChk.listDictionaries() == []

        # User words are skipped when no checker was ever loaded
        broken = SpellApple(project)
        broken.setLanguage("en")
        assert broken.spellLanguage is None


def nonsenseWords() -> list[str]:
    """Generate unique letter-only words that are not in any dictionary."""
    return ["zpqx" + "".join(x) for x in product("bcdfghjklm", repeat=3)]


@pytest.mark.core
@pytest.mark.skipif(not IS_DARWIN, reason="Requires the macOS NSSpellChecker")
def testSpellApple_BackgroundTextCheck(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, mockGUI: MockGuiMain, fncPath: Path
):
    """Test the system NSSpellChecker through the editor's background
    text check, while the main thread uses the same checker.
    """
    project = NWProject()
    buildTestProject(project, fncPath)

    errors: list[BaseException | None] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errors.append(v))
    monkeypatch.setattr(threading, "excepthook", lambda a: errors.append(a.exc_value))

    spChk = SpellApple(project)
    if "en" not in [tag for tag, _ in spChk.listDictionaries()]:
        pytest.skip("No English dictionary available")
    spChk.setLanguage("en")
    assert spChk.spellLanguage == "en"
    monkeypatch.setattr(SHARED, "_spelling", spChk)

    # Each block has known words, an upper case word, a number, a wide
    # character, and unique misspellings that bypass the cache
    words = nonsenseWords()
    sentence = "The garden house was quiet and green today"
    payload = []
    expected = {}
    for index in range(len(words) // 2):
        first, second = words[2*index], words[2*index + 1]
        text = f"\U0001f600 {sentence} {first} NASA 42, {second}."
        utf16Map = utf16CharMap(text)
        payload.append((index, text, text, 0, utf16Map))
        expected[index] = [
            (utf16Map[text.index(w)], utf16Map[text.index(w) + len(w)], w) for w in (first, second)
        ]

    results = {}
    threads = set()

    def onResults(jobId: int, data: list) -> None:
        threads.add(threading.get_ident())
        results.update({index: spellErrors for index, spellErrors, _ in data})

    dispatcher = TextCheckDispatcher(mockGUI, onResults)
    for jobId, start in enumerate(range(0, len(payload), 50)):
        dispatcher.dispatch(jobId, payload[start:start+50], True, False)

    # The main thread keeps using the checker while the jobs run
    mainChecks: list[tuple[str, bool, bool]] = []
    mainCalls = count()

    def mainThreadWork() -> bool:
        call = next(mainCalls)
        word = f"zpqy{words[call % len(words)][4:]}"
        mainChecks.append((word, spChk.checkWord(word), False))
        mainChecks.append(("garden", spChk.checkWord("garden"), True))
        mainChecks.append(("suggest", isinstance(spChk.suggestWords("gardn"), list), True))
        mainChecks.append(("list", len(spChk.listDictionaries()) > 0, True))
        if call % 10 == 9:
            spChk.setLanguage("en")
            spChk.addWord("zpqyadded", save=False)
            mainChecks.append(("zpqyadded", spChk.checkWord("zpqyadded"), True))
        return len(results) == len(payload)

    qtbot.waitUntil(mainThreadWork, timeout=10000)
    pool = QThreadPool.globalInstance()
    assert pool is not None
    pool.waitForDone()

    assert errors == []
    assert threads == {threading.main_thread().ident}
    assert results == expected
    assert len(mainChecks) > 4
    assert [check for check in mainChecks if check[1] != check[2]] == []
    assert spChk.spellLanguage == "en"
