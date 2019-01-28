"""
link.py
Writes to MongoDB Collection: links
"""

import regex as re
from bson.objectid import ObjectId

from sefaria.system.exceptions import DuplicateRecordError, InputError
from sefaria.system.database import db
from . import abstract as abst
from . import text


import logging
logger = logging.getLogger(__name__)


class Link(abst.AbstractMongoRecord):
    """
    A link between two texts (or more specifically, two references)
    """
    collection = 'links'
    history_noun = 'link'

    required_attrs = [
        "type",             # string of connection type
        "refs"              # list of refs connected
    ]
    optional_attrs = [
        "anchorText",       # string of dibbur hamatchil (largely deprecated) 
        "auto",             # bool whether generated by automatic process
        "generated_by",     # string in ("add_commentary_links", "add_links_from_text", "mishnah_map")
        "source_text_oid",  # oid of text from which link was generated
        "is_first_comment",  # set this flag to denote its the first comment link between the two texts in the link
        "first_comment_indexes", # Used when is_first_comment is True. List of the two indexes of the refs.
        "first_comment_section_ref", # Used when is_first_comment is True. First comment section ref.
        "inline_reference"  # dict with keys "data-commentator" and "data-order" to match an inline reference (itag)
    ]

    def _normalize(self):
        self.auto = getattr(self, 'auto', False)
        self.generated_by = getattr(self, "generated_by", None)
        self.source_text_oid = getattr(self, "source_text_oid", None)
        self.type = getattr(self, "type", "").lower()
        self.refs = [text.Ref(self.refs[0]).normal(), text.Ref(self.refs[1]).normal()]

        if getattr(self, "_id", None):
            self._id = ObjectId(self._id)

    def _validate(self):
        assert super(Link, self)._validate()

        if False in self.refs:
            return False

        return True

    def _pre_save(self):
        if getattr(self, "_id", None) is None:
            # Don't bother saving a connection that already exists, or that has a more precise link already
            # will also find the same link with the two refs reversed
            samelink = Link().load({"$or": [{"refs": self.refs}, {"refs": [self.refs[1], self.refs[0]]}]})

            if samelink:
                if not self.auto and self.type and not samelink.type:
                    samelink.type = self.type
                    samelink.save()
                    raise DuplicateRecordError(u"Updated existing link with new type: {}".format(self.type))

                elif self.auto and not samelink.auto:
                    samelink.auto = self.auto
                    samelink.generated_by = self.generated_by
                    samelink.source_text_oid = self.source_text_oid
                    samelink.type = self.type
                    samelink.refs = self.refs  #in case the refs are reversed. switch them around
                    samelink.save()
                    raise DuplicateRecordError(u"Updated existing link with auto generation data {} - {}".format(self.refs[0], self.refs[1]))

                else:
                    raise DuplicateRecordError(u"Link already exists {} - {}. Try editing instead.".format(self.refs[0], self.refs[1]))

            else:
                #find a potential link that already has a more precise ref of either of this link's refs.
                preciselink = Link().load(
                    {'$and':[text.Ref(self.refs[0]).ref_regex_query(), text.Ref(self.refs[1]).ref_regex_query()]}
                )

                if preciselink:
                    # logger.debug("save_link: More specific link exists: " + link["refs"][1] + " and " + preciselink["refs"][1])
                    raise DuplicateRecordError(u"A more precise link already exists: {} - {}".format(preciselink.refs[0], preciselink.refs[1]))
                # else: # this is a good new link

    def ref_opposite(self, from_ref, as_tuple=False):
        """
        Return the Ref in this link that is opposite the one matched by `from_ref`.
        The matching of from_ref uses Ref.regex().  Matches are to the specific ref, or below.
        If neither Ref matches from_ref, None is returned.
        :param from_ref: A Ref object
        :param as_tuple: If true, return a tuple (Ref,Ref), where the first Ref is the given from_ref,
        or one more specific, and the second Ref is the opposing Ref in the link.
        :return:
        """

        reg = re.compile(from_ref.regex())
        if reg.match(self.refs[1]):
            from_tref = self.refs[1]
            opposite_tref = self.refs[0]
        elif reg.match(self.refs[0]):
            from_tref = self.refs[0]
            opposite_tref = self.refs[1]
        else:
            return None

        if opposite_tref:
            try:
                if as_tuple:
                    return text.Ref(from_tref), text.Ref(opposite_tref)
                return text.Ref(opposite_tref)
            except InputError:
                return None


class LinkSet(abst.AbstractMongoSet):
    recordClass = Link

    def __init__(self, query_or_ref={}, page=0, limit=0):
        '''
        LinkSet can be initialized with a query dictionary, as any other MongoSet.
        It can also be initialized with a :py:class: `sefaria.text.Ref` object,
        and will use the :py:meth: `sefaria.text.Ref.regex()` method to return the set of Links that refer to that Ref or below.
        :param query_or_ref: A query dict, or a :py:class: `sefaria.text.Ref` object
        '''
        try:
            regex_list = query_or_ref.regex(as_list=True)
            ref_clauses = [{"refs": {"$regex": r}} for r in regex_list]
            super(LinkSet, self).__init__({"$or": ref_clauses}, page, limit, hint=[("refs", 1)])
        except AttributeError:
            super(LinkSet, self).__init__(query_or_ref, page, limit)

    def filter(self, sources):
        """
        Filter LinkSet according to 'sources' which may be either
        - a string, naming a text or category to include
        - an array of strings, naming multiple texts or categories to include

        ! Returns a list of Links, not a LinkSet
        """
        if isinstance(sources, basestring):
            return self.filter([sources])

        # Expand Categories
        categories = text.library.get_text_categories()
        expanded_sources = []
        for source in sources:
            expanded_sources += [source] if source not in categories else text.library.get_indexes_in_category(source)

        regexes = [text.Ref(source).regex() for source in expanded_sources]
        filtered = []
        for source in self:
            if any([re.match(regex, source.refs[0]) for regex in regexes] + [re.match(regex, source.refs[1]) for regex in regexes]):
                filtered.append(source)

        return filtered

    # This could be implemented with Link.ref_opposite, but we should speed test it first.
    def refs_from(self, from_ref, as_tuple=False, as_link=False):
        """
        Get a collection of Refs that are opposite the given Ref, or a more specific Ref, in this link set.
        Note that if from_ref is more specific than the criterion that created the linkSet,
        then the results of this function will implicitly be filtered according to from_ref.
        :param from_ref: A Ref object
        :param as_tuple: If true, return a collection of tuples (Ref,Ref), where the first Ref is the given from_ref,
        or one more specific, and the second Ref is the opposing Ref in the link.
        :return: List of Ref objects
        """
        reg = re.compile(from_ref.regex())
        refs = []
        for link in self:
            if reg.match(link.refs[1]):
                from_tref = link.refs[1]
                opposite_tref = link.refs[0]
            elif reg.match(link.refs[0]):
                from_tref = link.refs[0]
                opposite_tref = link.refs[1]
            else:
                opposite_tref = False

            if opposite_tref:
                try:
                    if as_link:
                        refs.append((link, text.Ref(opposite_tref)))
                    elif as_tuple:
                        refs.append((text.Ref(from_tref), text.Ref(opposite_tref)))
                    else:
                        refs.append(text.Ref(opposite_tref))
                except:
                    pass
        return refs

    @classmethod
    def get_first_ref_in_linkset(cls, base_text, dependant_text):
        """
        Given a linkset
        :param from_ref: A Ref object
        :param as_tuple: If true, return a collection of tuples (Ref,Ref), where the first Ref is the given from_ref,
        or one more specific, and the second Ref is the opposing Ref in the link.
        :return: List of Ref objects
        """
        retlink = None
        orig_ref = text.Ref(dependant_text)
        base_text_ref = text.Ref(base_text)
        ls = cls(
            {'$and': [orig_ref.ref_regex_query(), base_text_ref.ref_regex_query()],
             "generated_by": {"$ne": "add_links_from_text"}}
        )
        refs_from = ls.refs_from(base_text_ref, as_link=True)
        sorted_refs_from = sorted(refs_from, key=lambda r: r[1].order_id())
        if len(sorted_refs_from):
            retlink = sorted_refs_from[0][0]
        return retlink

    def summary(self, relative_ref):
        """
        Returns a summary of the counts and categories in this link set,
        relative to 'relative_ref'.
        """
        results = {}
        for link in self:
            ref = link.refs[0] if link.refs[1] == relative_ref.normal() else link.refs[1]
            try:
                oref = text.Ref(ref)
            except:
                continue
            cat  = oref.primary_category
            if (cat not in results):
                results[cat] = {"count": 0, "books": {}}
            results[cat]["count"] += 1
            if (oref.book not in results[cat]["books"]):
                results[cat]["books"][oref.book] = 0
            results[cat]["books"][oref.book] += 1

        return [{"name": key, "count": results[key]["count"], "books": results[key]["books"] } for key in results.keys()]


def process_index_title_change_in_links(indx, **kwargs):
    print "Cascading Links {} to {}".format(kwargs['old'], kwargs['new'])

    # ensure that the regex library we're using here is the same regex library being used in `Ref.regex`
    from text import re as reg_reg
    patterns = [pattern.replace(reg_reg.escape(indx.title), reg_reg.escape(kwargs["old"]))
                for pattern in text.Ref(indx.title).regex(as_list=True)]
    queries = [{'refs': {'$regex': pattern}} for pattern in patterns]
    links = LinkSet({"$or": queries})
    for l in links:
        l.refs = [r.replace(kwargs["old"], kwargs["new"], 1) if re.search(u'|'.join(patterns), r) else r for r in l.refs]
        try:
            l.save()
        except InputError: #todo: this belongs in a better place - perhaps in abstract
            logger.warning("Deleting link that failed to save: {} - {}".format(l.refs[0], l.refs[1]))
            l.delete()


def process_index_delete_in_links(indx, **kwargs):
    from sefaria.model.text import prepare_index_regex_for_dependency_process
    pattern = prepare_index_regex_for_dependency_process(indx)
    LinkSet({"refs": {"$regex": pattern}}).delete()


#get_link_counts() and get_book_link_collection() are used in Link Explorer.
#They have some client formatting code in them; it may make sense to move them up to sefaria.client or sefaria.helper
link_counts = {}
def get_link_counts(cat1, cat2):
    global link_counts
    key = cat1 + "-" + cat2
    if link_counts.get(key):
        return link_counts[key]

    titles = []
    for c in [cat1, cat2]:
        ts = text.library.get_indexes_in_category(c)
        if len(ts) == 0:
            return {"error": "No results for {}".format(c)}
        titles.append(ts)

    result = []
    for title1 in titles[0]:
        for title2 in titles[1]:
            re1 = r"^{} \d".format(title1)
            re2 = r"^{} \d".format(title2)
            links = LinkSet({"$and": [{"refs": {"$regex": re1}}, {"refs": {"$regex": re2}}]})  # db.links.find({"$and": [{"refs": {"$regex": re1}}, {"refs": {"$regex": re2}}]})
            if links.count():
                result.append({"book1": title1.replace(" ","-"), "book2": title2.replace(" ", "-"), "count": links.count()})

    link_counts[key] = result
    return result


# todo: check vis-a-vis commentary refactor
def get_category_commentator_linkset(cat, commentator):
    return LinkSet({"$or": [
                        {"$and": [{"refs": {"$regex": ur"{} \d".format(t)}},
                                  {"refs": {"$regex": "^{} on {}".format(commentator, t)}}
                                  ]
                         }
                        for t in text.library.get_indexes_in_category(cat)]
                    })


def get_category_category_linkset(cat1, cat2):
    """
    Return LinkSet of links between the given book and category.
    :param book: String
    :param cat: String
    :return:
    """
    queries = []
    titles = []
    regexes = []
    clauses = []

    for i, cat in enumerate([cat1, cat2]):
        queries += [{"$and": [{"categories": cat}, {'dependence': {'$in': [False, None]}}]}]
        titles += [text.library.get_indexes_in_category(cat)]
        if len(titles[i]) == 0:
            raise IndexError("No results for {}".format(queries[i]))

        regexes += [[]]
        for t in titles[i]:
            regexes[i] += text.Ref(t).regex(as_list=True)

        clauses += [[]]
        for rgx in regexes[i]:
            if cat1 == cat2:
                clauses[i] += [{"refs.{}".format(i): {"$regex": rgx}}]
            else:
                clauses[i] += [{"refs": {"$regex": rgx}}]

    return LinkSet({"$and": [{"$or": clauses[0]}, {"$or": clauses[1]}]})


def get_book_category_linkset(book, cat):
    """
    Return LinkSet of links between the given book and category.
    :param book: String
    :param cat: String
    :return:
    """
    titles = text.library.get_indexes_in_category(cat)
    if len(titles) == 0:
        return {"error": "No results for {}".format(query)}

    book_re = text.Ref(book).regex()
    cat_re = r'^({}) \d'.format('|'.join(titles)) #todo: generalize this regex

    return LinkSet({"$and": [{"refs": {"$regex": book_re}}, {"refs": {"$regex": cat_re}}]})


def get_book_link_collection(book, cat):
    """
    Format results of get_book_category_linkset for front end use by the Explorer.
    :param book: String
    :param cat: String
    :return:
    """
    links = get_book_category_linkset(book, cat)

    link_re = r'^(?P<title>.+) (?P<loc>\d.*)$'
    ret = []

    for link in links:
        l1 = re.match(link_re, link.refs[0])
        l2 = re.match(link_re, link.refs[1])
        ret.append({
            "r1": {"title": l1.group("title").replace(" ", "-"), "loc": l1.group("loc")},
            "r2": {"title": l2.group("title").replace(" ", "-"), "loc": l2.group("loc")}
        })
    return ret