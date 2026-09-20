"""rule34.xxx (Gelbooru-engine dapi). Adult-only site: every post is questionable/explicit."""
from anihub.sources.engines import GelbooruEngine


class Rule34(GelbooruEngine):
    name = "rule34"
    title = "Rule34"
    api_url = "https://api.rule34.xxx/index.php"
    page_url_tpl = "https://rule34.xxx/index.php?page=post&s=view&id={id}"
