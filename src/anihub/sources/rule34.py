"""rule34.xxx (Gelbooru-engine dapi). Adult-only site: every post is questionable/explicit."""
from anihub.sources.engines import GelbooruEngine


class Rule34(GelbooruEngine):
    name = "rule34"
    title = "Rule34"
    api_url = "https://api.rule34.xxx/index.php"
    page_url_tpl = "https://rule34.xxx/index.php?page=post&s=view&id={id}"
    # rule34.xxx's own tag types (per its maintained rule34Py client library) put character/copyright in the
    # opposite order from the stock Gelbooru numbering GelbooruEngine defaults to -- a site can pick its own.
    TAG_TYPE_MAP = {0: "general", 1: "artist", 2: "character", 3: "copyright", 4: "meta"}
