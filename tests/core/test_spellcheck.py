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

from importlib.util import find_spec
from pathlib import Path

import pytest

from novelwriter.constants import nwFiles
from novelwriter.core.project import NWProject
from novelwriter.core.spellcheck import FakeEnchant, SpellApple, SpellEnchant, UserDictionary, createSpellChecker

from tests.helpers import buildTestProject
from tests.mocked import MockGuiMain, causeOSError

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


@pytest.mark.core
@pytest.mark.skipif(not HAS_ENCHANT, reason="Requires pyenchant")
def testSpellEnchant_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the pyenchant spell checker."""
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


@pytest.mark.core
def testSpellEnchant_Cache(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
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


@pytest.mark.core
def testSpellCheck_Create(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test that the platform spell checker is created."""
    project = NWProject()
    buildTestProject(project, fncPath)

    with monkeypatch.context() as mp:
        mp.setattr("novelwriter.CONFIG.osDarwin", True)
        assert isinstance(createSpellChecker(project), SpellApple)

    with monkeypatch.context() as mp:
        mp.setattr("novelwriter.CONFIG.osDarwin", False)
        assert isinstance(createSpellChecker(project), SpellEnchant)


@pytest.mark.core
@pytest.mark.skipif(not IS_DARWIN, reason="Requires macOS")
def testSpellApple_Main(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test the macOS spell checker."""
    project = NWProject()
    buildTestProject(project, fncPath)

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

    # Add a word to the session and the user dictionary
    assert spChk.checkWord("zpqxyq") is False
    spChk.addWord("zpqxyq")
    assert spChk.checkWord("zpqxyq") is True
    assert "zpqxyq" in spChk._userDict

    # Words from the user dictionary are restored on language change
    spChk.setLanguage("en")
    assert spChk.checkWord("zpqxyq") is True

    # A new instance loads the user dictionary into its own session
    other = SpellApple(project)
    other.setLanguage("en")
    assert other.checkWord("zpqxyq") is True

    # Backend errors are handled
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "AppKit", None)
        spChk.setLanguage("en")
        assert spChk.spellLanguage is None
        assert spChk.listDictionaries() == []
