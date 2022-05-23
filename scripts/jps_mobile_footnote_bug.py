import django

django.setup()

from sefaria.model import *
import re


# german_text = talmud_ref.text('en', vtitle='Talmud Bavli. German trans. by Lazarus Goldschmidt, 1929 [de]')
# Cross check against all of Talmud

def find_all_footnote_errors():
    from sefaria.tracker import modify_bulk_text
    corrected_text = {}

    def correct_text(s, en_tref, he_tref, v):
        nonlocal corrected_text
        # Todo does the CSS text exist
        re.sub(r"<sup>", "<sup class='endFootnote'>", s)
        if "<sup class='endFootnote'>" in s:
            print(s)
        corrected_text[en_tref] = s

    tanakh_indices = library.get_indexes_in_category("Tanakh", full_records=True)
    for index in tanakh_indices:
        if index.title != "Sefer Daniel; Opportunity in Exile":
            version = Version().load({"title": index.title,
                                      "versionTitle": "Tanakh: The Holy Scriptures, published by JPS"})
            print(f"Walking through {index.title}")
        if version == None:
            print("VERSION IS NONE")
            print(index.title)
        if version:
            version.walk_thru_contents(correct_text)

    # TODO - if I put inline one more, it gets stuck on Exodus, out here also stuck
    modify_bulk_text(1, version, corrected_text)


find_all_footnote_errors()
